# CLAUDE.md

## Overview

`docman` is a CLI tool for organizing documents using AI-powered analysis.

**Workflow**: `scan` → `plan` → `status` → `review`

**Core Technologies**: docling (extraction), LLM (Gemini/OpenAI), Pydantic (validation), SQLite (storage), OS keyring (credentials)

## Development Commands

```bash
# Setup
uv sync --all-extras    # with dev deps
uv sync                 # production only

# Testing
uv run pytest                                    # all tests
uv run pytest tests/unit/test_config.py         # specific file
uv run pytest tests/unit/test_config.py::TestClass::test_method  # specific test

# Lint & Type Check
uv run ruff check .
uv run mypy src/

# Database Migrations
alembic -c src/docman/alembic.ini revision --autogenerate -m "description"
alembic -c src/docman/alembic.ini upgrade head
alembic -c src/docman/alembic.ini history
```

## Architecture

### Two-Tier Configuration System

1. **App-level config**: OS-specific global settings
   - Paths: `~/Library/Application Support/docman/` (macOS), `~/.config/docman/` (Linux), `%APPDATA%\docman\` (Windows)
   - Stores LLM provider configs
   - Test override: `DOCMAN_APP_CONFIG_DIR` env var

2. **Repository-level config**: `<project>/.docman/config.yaml`
   - Folder definitions and variable patterns

### Database Schema (SQLAlchemy + Alembic)

**`documents`**: Canonical documents by content hash (SHA256)
- Stores extracted text content

**`document_copies`**: File instances (multiple can reference one document)
- FKs: `document_id`, `accepted_operation_id` (nullable)
- Fields: `repository_path`, `file_path`, `stored_content_hash`, `stored_size`, `stored_mtime`
- `organization_status`: enum (`unorganized`, `organized`, `ignored`) - indexed
- `last_seen_at` for garbage collection
- Unique: (`repository_path`, `file_path`)

**`operations`**: LLM suggestions with lifecycle tracking
- `status`: enum (`pending`, `accepted`, `rejected`) - indexed
- Partial unique index: one PENDING per copy
- Fields: `suggested_directory_path`, `suggested_filename`, `reason`
- Invalidation: `prompt_hash`, `document_content_hash`, `model_name`
- Historical ops preserved (not cascade-deleted) for few-shot prompting
- On accept: status=ACCEPTED, copy links via `accepted_operation_id`
- On reject: status=REJECTED, preserved for history

### LLM Integration Architecture

**Prompt Building** (`prompt_builder.py`):
- Jinja2 templates in `src/docman/prompt_templates/`
- `system_prompt.j2`: Adapts based on `use_structured_output` flag
- `user_prompt.j2`: XML-tagged content (`<organizationInstructions>`, `<documentContent filePath="...">`)
- Content truncation: 8000 char limit, configurable `head_ratio` (default 0.6 head/0.4 tail), paragraph-aware
- Prompt hash caching for LLM call deduplication

**Provider Abstraction** (`llm_providers.py`):
- `OrganizationSuggestion` Pydantic model: `suggested_directory_path`, `suggested_filename`, `reason`
- `LLMProvider` ABC with `supports_structured_output` property
- `GoogleGeminiProvider`: native structured output via `response_schema`
  - Exceptions: `GeminiSafetyBlockError`, `GeminiEmptyResponseError`
- `OpenAICompatibleProvider`: works with OpenAI API, LM Studio, vLLM
  - `supports_structured_output=True` for official API, `False` for custom endpoints
  - Exceptions: `OpenAIAPIError`, `OpenAIEmptyResponseError`
- Factory: `get_provider(config, api_key)`

**Configuration** (`llm_config.py`):
- Multiple providers, one active at a time
- API keys in OS keychain (never plaintext)

### Document Processing Flow

1. **Garbage Collection** (`cleanup_orphaned_copies()`): Runs at start of `scan`/`plan`, deletes orphaned copies, updates `last_seen_at`

2. **Discovery** (`repository.py`):
   - `discover_document_files(repo_root, root_path=None)`: recursive, `root_path` limits scope
   - `discover_document_files_shallow()`: non-recursive
   - Filters by `SUPPORTED_EXTENSIONS`

3. **Stale Detection** (`file_needs_rehashing()`): Compare `stored_size`/`stored_mtime`, rehash only if changed

4. **Content Extraction** (`processor.py`): docling `DocumentConverter`, reuse via `converter` param, compute content hash

5. **Database Storage** (`models.py`): Create/update `Document` and `DocumentCopy`

6. **Invalidation Check**: Compare `prompt_hash`, `document_content_hash`, `model_name`; regenerate if any differ

7. **LLM Suggestion** (`plan` command): Generate instructions → build prompts → call provider → store `Operation`

**Error Handling**:
- `scan`: extraction failures → `failed_count`, null content; hash failures → `failed_count`, no records
- `plan`: files without content → `skipped_count`; LLM failures → `skipped_count`, delete pending op

### Apply/Reject Workflow

**Reviewing Suggestions** (`status` command):
- Query `Operation` (status=PENDING) joined with `DocumentCopy`
- Display current path, suggested path, and reason
- Filter by file or directory path

**Review Operations** (`review` command):
- **Interactive mode** (default): [A]pply/[R]eject/[S]kip/[O]pen/[P]rocess/[Q]uit/[H]elp
  - **Apply**: Moves file, sets ACCEPTED + ORGANIZED
  - **Reject**: Sets REJECTED, preserves for history, no file move
  - **Skip**: Leaves PENDING
  - **Open**: Preview with system app
  - **Process**: Re-generate with optional LLM feedback
- **Bulk apply** (`--apply-all`): Options: `-y`, `--force`, `--dry-run`
  - Moves files, updates paths, sets ACCEPTED + ORGANIZED
- **Bulk reject** (`--reject-all`): Options: `-y`, `-r`, `--dry-run`
  - Sets REJECTED, preserves history, no file moves

**File Operations** (`file_operations.py`):
- `move_file()`: Uses `shutil.move()` for cross-filesystem support
- Conflict resolution: SKIP (raise error), OVERWRITE (replace), RENAME (add suffix)
- Creates target directories automatically (`create_dirs=True`)
- Exceptions: `FileConflictError`, `FileNotFoundError`, `FileOperationError`

### Organization Status Tracking

**Overview**: Each `DocumentCopy` has `organization_status`: `unorganized`, `organized`, or `ignored`.

**Status Lifecycle**:
1. New files: `unorganized`
2. After `review` (apply): `organized`
3. Via `docman ignore`: `ignored`
4. Via `docman unmark`: `unorganized`

**Behavior by Command**:
- **`plan`**: Skips `organized`/`ignored` by default. Use `--reprocess` to include all; resets to `unorganized` on detected changes.
- **`review`**: Apply sets `organized`; reject sets REJECTED without changing status.
- **`unmark`**: Resets to `unorganized`, deletes PENDING ops. Flags: `--all`, `-r`, `-y`.
- **`ignore`**: Sets `ignored`, deletes PENDING ops. Flags: `-r`, `-y`. Requires path.
- **`status`**: Shows organization status with pending operations.

**Invalidation**: With `--reprocess`, organized files reset to `unorganized` when content hash, prompt hash, or model changes. Without `--reprocess`, organized files are skipped.

**Example Workflows**:

```bash
# Standard workflow
docman scan -r                 # Or: docman plan --scan -r (combined)
docman plan
docman review --apply-all -y   # Marks as organized
docman plan                    # Skips organized files

# Re-organize after config changes
docman plan --reprocess        # Includes organized, resets on changes
# For content changes: docman scan --rescan -r first

# Ignore/unmark files
docman ignore archives/ -r -y  # Excluded from plans
docman unmark archives/ -r -y  # Re-enable
```

### Folder Definition System

**Overview**: Define document organization hierarchies and filename conventions in `.docman/config.yaml`. Variable patterns must be defined before use.

**Architecture** (`repo_config.py`):
- **`FolderDefinition`**: Dataclass with optional `description`, `filename_convention`, nested `folders`
- **Storage**: YAML under `organization.folders` and `organization.variable_patterns`
- **Variable patterns**: Placeholders (`{year}`, `{company}`) with optional predefined values/aliases
- **Filename conventions**: Repository default with folder overrides; extension always preserved
- **YAML errors**: Detects malformed config with actionable messages

**Validation**:
- One variable pattern per hierarchy level (e.g., `{year}` and `{category}` can't be siblings)
- Validated on add and config load

**Commands** (all support `--path` for repository location):

*Patterns:*
- `pattern add <name> --desc "..."` / `pattern list` / `pattern show <name>` / `pattern remove <name>`

*Pattern values:*
- `pattern value add <pattern> <value> [--desc] [--alias-of]` / `value list` / `value remove`

*Folders:*
- `define <path> [--desc] [--filename-convention]`: Define folder (creates nested structure)
- `config set-default-filename-convention "<pattern>"`: Set repository default
- `config list-dirs`: Display folder tree

**Example**:
```bash
# Define patterns
docman pattern add year --desc "4-digit year (YYYY)"
docman pattern add company --desc "Company name"
docman pattern value add company "Acme Corp." --desc "Main company"
docman pattern value add company "XYZ Corp" --alias-of "Acme Corp."

# Set conventions and structure
docman config set-default-filename-convention "{year}-{month}-{description}"
docman define Financial/invoices/{year} \
  --desc "Invoices by year" \
  --filename-convention "{company}-invoice-{year}-{month}"

# Generate suggestions
docman scan -r && docman plan
```

**LLM Integration** (`prompt_builder.py`):
- `generate_instructions_from_folders()`: Converts to LLM instructions (hierarchy, conventions, patterns)
- Predefined values included as "Known values:" with aliases
- Prompt hash includes instructions + model; changes invalidate operations

### CLI Structure (`cli.py`)

**Commands Summary**:
- `init`: Initialize repository
- `scan`: Extract document content (`-r`, `--rescan`)
- `plan`: Generate LLM suggestions (`-r`, `--reprocess`, `--scan`)
- `status`: View pending operations (shows duplicates, conflicts)
- `review`: Process operations (`--apply-all`/`--reject-all`)
- `dedupe`: Resolve duplicates (`-y`, `--dry-run`, `-r`)
- `define`: Define folder hierarchies
- `pattern`: Manage variable patterns
- `unmark`: Reset status (`--all`, `-r`, `-y`)
- `ignore`: Exclude from processing (`-r`, `-y`)
- `llm`: Manage LLM providers
- `config`: Repository settings
- `debug-prompt`: Debug LLM prompts

Use `docman <command> --help` for detailed options.

### Duplicate Document Handling

**Architecture**: Content-based deduplication via SHA256 hash.

**Key Components**:
1. **`documents` table**: One record per unique content
2. **`document_copies` table**: Multiple copies reference same document
3. **`find_duplicate_groups()`**: Identifies documents with multiple copies
4. **`detect_target_conflicts()`**: Finds operations targeting same destination

**Workflow**:
```bash
docman scan -r && docman dedupe && docman plan && docman review --apply-all -y
# Or: docman dedupe -y (bulk) / docman dedupe --dry-run (preview)
```

**Command Behaviors**:
- **status**: Groups duplicates with sub-numbering `[1a], [1b]`, shows conflicts with `CONFLICT` indicator
- **plan**: Warns when duplicates detected, shows estimated LLM cost savings
- **dedupe**: Interactive (choose copy) or bulk (`-y` keeps first), supports `--dry-run` and path filtering

**Cost Optimization**: Deduplicating before `plan` saves (N-1) LLM calls per duplicate group.

### Testing Structure

- **Unit tests** (`tests/unit/`): Test modules in isolation (config, models, file_operations, llm_config, prompt_builder, processor, repository, database, helpers)
- **Integration tests** (`tests/integration/`): Test full command workflows (one file per command)
- Uses `CliRunner` from Click; fixtures in `conftest.py`

**Test Isolation**: Global `autouse` fixture `isolate_app_config` in `conftest.py` automatically sets `DOCMAN_APP_CONFIG_DIR` to temp directory for every test. Tests never touch real user data.

## Key Patterns

### Credential Storage
API keys NEVER in plaintext:
```python
keyring.set_password("docman_llm", provider_name, api_key)
api_key = keyring.get_password("docman_llm", provider_name)
```

### Database Sessions
```python
with next(get_session()) as session:
    # queries here
```

### Error Handling in CLI
```python
click.secho("Error message", fg="red", err=True)
raise click.Abort()
```

### Content Hashing
Always use `compute_content_hash()` from `models.py` for consistent SHA256.

### Stale Content Detection
`file_needs_rehashing(copy, file_path)` checks if `stored_size`/`stored_mtime` differ. Only rehash when True.

### Prompt Hash Caching
Hash = SHA256(system_prompt + organization_instructions + model_name). Compare with stored `Operation` fields; regenerate if any differ.

### DocumentConverter Reuse
```python
converter = DocumentConverter()
for file_path in files:
    content = extract_content(file_path, converter=converter)
```

### Directory Scoping
```python
files = discover_document_files(repo_root, root_path=subdir_path)  # Efficient
```

### Structured Output
Set `supports_structured_output` property in provider class. Template adapts via `use_structured_output` flag.

## Typical Development Workflow

**Adding a new command**:
1. Add to `cli.py` with Click decorators
2. Implement queries using SQLAlchemy session pattern
3. Add tests in `tests/integration/test_<command>_integration.py`
4. Update CLAUDE.md

**Modifying file operations**:
1. Update `file_operations.py`
2. Add unit tests in `tests/unit/test_file_operations.py`
3. Test SKIP, OVERWRITE, RENAME conflict strategies

**Database schema changes**:
1. Modify `models.py`
2. Generate migration: `alembic revision --autogenerate -m "description"`
3. Review in `alembic/versions/`, apply: `alembic upgrade head`
4. Update tests

**Adding a new LLM provider**:
1. Create class in `llm_providers.py` inheriting `LLMProvider`
2. Implement `generate_suggestions()` and `test_connection()`
3. Set `supports_structured_output` property
4. Handle schema (Pydantic for structured) or JSON parsing (unstructured)
5. Add to `get_provider()` and `list_available_models()`
6. Test both prompt modes
