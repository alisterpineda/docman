# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`docman` is a CLI tool for organizing documents using AI-powered analysis.

**Workflow**: `plan` → `status` → `apply` or `reject`

**Core Technologies**:
- **docling** for document content extraction
- **LLM models** (Google Gemini) for intelligent organization suggestions
- **Pydantic** for structured output schemas and validation
- **SQLite database** for tracking documents, copies, and pending operations
- **OS-native credential managers** for secure API key storage

## Development Commands

### Setup
```bash
# Install dependencies (with dev extras)
uv sync --all-extras

# Install without dev dependencies
uv sync
```

### Testing
```bash
# Run all tests with coverage
uv run pytest

# Run specific test file
uv run pytest tests/unit/test_config.py

# Run specific test
uv run pytest tests/unit/test_config.py::test_ensure_app_config
```

### Linting and Type Checking
```bash
# Run ruff linter
uv run ruff check .

# Run mypy type checker
uv run mypy src/
```

### Database Migrations
```bash
# Create a new migration (after modifying models)
alembic revision --autogenerate -m "description"

# Run migrations to latest version
alembic upgrade head

# View migration history
alembic history
```

## Architecture

### Two-Tier Configuration System

1. **App-level config**: Global settings stored in OS-specific location
   - macOS: `~/Library/Application Support/docman/config.yaml`
   - Linux: `~/.config/docman/config.yaml`
   - Windows: `%APPDATA%\docman\config.yaml`
   - Stores: LLM provider configurations
   - Test override: `DOCMAN_APP_CONFIG_DIR` environment variable

2. **Repository-level config**: Project-specific settings stored in `<project>/.docman/`
   - `config.yaml`: Repository configuration
   - `instructions.md`: Document organization instructions (required for LLM prompts)

### Database Schema (SQLAlchemy + Alembic)

Three main tables model document tracking and operations:

1. **`documents`**: Canonical documents identified by content hash (SHA256)
   - Deduplication: Same content = same document, regardless of location
   - Stores extracted text content from docling

2. **`document_copies`**: Specific file instances (fungible)
   - Links to canonical document via `document_id`
   - Links to accepted operation via `accepted_operation_id` (nullable FK to `operations.id`)
   - Tracks: `repository_path`, `file_path`
   - Stale content detection: `stored_content_hash`, `stored_size`, `stored_mtime`
   - Garbage collection: `last_seen_at` (indexed)
   - **Organization status**: Enum field (`unorganized`, `organized`, `ignored`) - indexed
   - Unique constraint on (`repository_path`, `file_path`)

3. **`operations`**: LLM suggestions for file reorganization with lifecycle tracking
   - **Status tracking**: Enum field (`pending`, `accepted`, `rejected`) - indexed
   - **One PENDING per copy**: Partial unique index on `(document_copy_id) WHERE status='pending'`
   - **Historical preservation**: Operations NOT cascade-deleted; `document_copy_id` set to NULL when copy removed
   - Multiple historical operations (ACCEPTED/REJECTED) preserved for few-shot prompting
   - Stores: `suggested_directory_path`, `suggested_filename`, `reason`, `confidence`
   - Invalidation tracking: `prompt_hash` (indexed), `document_content_hash`, `model_name`
   - **Few-shot index**: Composite index on `(status, prompt_hash)` for fast historical lookup
   - Regenerates suggestions when prompt, content, or model changes
   - **On accept**: Status set to `ACCEPTED`, `DocumentCopy.accepted_operation_id` links to this operation
   - **On reject**: Status set to `REJECTED`, operation preserved for historical record

### LLM Integration Architecture

**Prompt Building** (`prompt_builder.py`):
- Uses Jinja2 templates in `src/docman/prompt_templates/`
- `system_prompt.j2`: Adaptive prompts based on provider capabilities
  - Uses `use_structured_output` flag to conditionally include/omit JSON format instructions
  - When structured output enabled: API enforces schema, prompt omits format details
  - When disabled: Includes explicit JSON format instructions for compatibility
- `user_prompt.j2`: Per-document prompt with file path, content, and organization instructions
- Smart content truncation: Keeps beginning (60%) and end (30%) of long documents
- Prompt hash caching: Avoids redundant LLM calls when prompts haven't changed

**Provider Abstraction** (`llm_providers.py`):
- `OrganizationSuggestion` Pydantic model: Defines response schema with field validation
- `LLMProvider` abstract base class with `supports_structured_output` property
- `GoogleGeminiProvider` implementation (currently supported)
  - Uses native structured output via `generation_config` with `response_schema`
  - `supports_structured_output = True`: API guarantees schema compliance
  - Custom exceptions: `GeminiSafetyBlockError`, `GeminiEmptyResponseError`
  - Response normalization checks `response.text` and `response.candidates`
- Factory pattern via `get_provider(config, api_key)`
- Output schema: `suggested_directory_path`, `suggested_filename`, `reason`, `confidence` (0.0-1.0)

**Configuration** (`llm_config.py`):
- Manages multiple provider configurations
- One active provider at a time
- API keys stored in OS keychain (never in plaintext config files)

### Document Processing Flow

1. **Garbage Collection** (`cleanup_orphaned_copies()`):
   - Runs at start of `plan` command
   - Deletes `DocumentCopy` for files that no longer exist on disk
   - Updates `last_seen_at` for existing files

2. **Discovery** (`repository.py`):
   - `discover_document_files(repo_root, root_path=None)`: Recursive file finding
     - `root_path` parameter limits walk to subdirectory (defaults to `repo_root`)
   - `discover_document_files_shallow()`: Non-recursive
   - Filters by `SUPPORTED_EXTENSIONS` (PDF, DOCX, TXT, etc.)

3. **Stale Content Detection** (`file_needs_rehashing()`):
   - Checks `stored_size` and `stored_mtime` vs current file
   - Only rehashes if metadata changed (performance optimization)
   - If content changed: updates/creates `Document`, invalidates `Operation`

4. **Content Extraction** (`processor.py`):
   - Uses docling `DocumentConverter` to extract text content
   - Accepts optional `converter` parameter for reuse (performance optimization)
   - `plan` command creates single converter instance for all files
   - Computes content hash for deduplication

5. **Database Storage** (`models.py`):
   - Create/update `Document` (by content hash)
   - Create/update `DocumentCopy` with stored metadata

6. **Invalidation Check** (multi-factor):
   - Compares: `prompt_hash`, `document_content_hash`, `model_name`
   - Regenerates if any changed

7. **LLM Suggestion** (`cli.py` `plan` command):
   - Load organization instructions from `.docman/instructions.md`
   - Build prompts using `prompt_builder.py`
   - Call LLM provider for suggestions
   - Store in `Operation` with all tracking fields

**Error Handling**:
- **Content extraction failures**: File counted in `failed_count`, no `Operation` created
- **LLM API failures**: File skipped, counted in `skipped_count`, no `Operation` created
- **No double counting**: Extraction failures don't increment `skipped_count`
- **Stale operations cleanup**: Existing `Operation` deleted if file now fails processing
- **Summary statistics**: Shows distinct counts for failed (extraction) vs skipped (LLM) files

### Apply/Reject Workflow

**Reviewing Suggestions** (`status` command):
- Query `Operation` (status=PENDING) joined with `DocumentCopy`
- Display current path, suggested path, confidence, and reason
- Filter by file or directory path
- Color-coded confidence: green (≥80%), yellow (≥60%), red (<60%)

**Applying Operations** (`apply` command):
- **Interactive mode** (default): Per-operation prompts with [A]pply/[S]kip/[Q]uit/[H]elp
- **Bulk mode** (`-y` flag): Auto-apply all without prompts
- File operations via `file_operations.py` module
- Updates `DocumentCopy.file_path` after successful move
- **Marks operation as ACCEPTED**: Sets `status=ACCEPTED`, links via `DocumentCopy.accepted_operation_id`
- Sets `DocumentCopy.organization_status=ORGANIZED`
- Operation preserved for historical record and few-shot prompting
- Options: `--force` (overwrite conflicts), `--dry-run` (preview only)

**Rejecting Operations** (`reject` command):
- **Marks operations as REJECTED**: Sets `status=REJECTED`, preserves operation for historical record
- Does NOT move files or change organization status
- Preserves `Document` and `DocumentCopy` records
- Supports recursive (`-r`) and non-recursive directory filtering

**File Operations** (`file_operations.py`):
- `move_file()`: Uses `shutil.move()` for cross-filesystem support
- Conflict resolution strategies: SKIP (raise error), OVERWRITE (replace), RENAME (add suffix)
- Creates target directories automatically (`create_dirs=True`)
- Custom exceptions: `FileConflictError`, `FileNotFoundError`, `FileOperationError`

### Organization Status Tracking

**Overview**: Each `DocumentCopy` has an `organization_status` field that tracks whether the file has been organized, is still unorganized, or should be ignored.

**Status Lifecycle**:
1. **New files**: Start as `unorganized`
2. **After `apply`**: Changed to `organized`
3. **User marks as ignored**: Changed to `ignored` via `docman ignore`
4. **User wants to re-process**: Reset to `unorganized` via `docman unmark`

**Behavior by Command**:
- **`plan`**:
  - Skips files with status `organized` or `ignored` by default (saves LLM costs)
  - Use `--reprocess` flag to process all files regardless of status
  - If file content or prompt changes, status automatically resets to `unorganized` (triggers regeneration)
- **`apply`**:
  - Sets status to `organized` after successfully moving file
  - Also sets to `organized` if file is already at target location (no-op)
- **`reject`**:
  - Marks `Operation` as REJECTED but does NOT change organization status
  - Allows file to be re-planned next time (new PENDING operation will be created)
- **`unmark`**:
  - Sets status to `unorganized`
  - Deletes any PENDING `Operation` (preserves historical ACCEPTED/REJECTED operations)
  - Supports `--all` flag and `-r` (recursive) for directories
- **`ignore`**:
  - Sets status to `ignored`
  - Deletes any PENDING `Operation` (preserves historical ACCEPTED/REJECTED operations)
  - Supports `-r` (recursive) for directories
  - Requires a path argument (no `--all` flag)
- **`status`**:
  - Displays organization status alongside pending operations

**Invalidation & Auto-Reset**:
When `plan` detects changes to files marked as `organized`, it automatically resets status to `unorganized`:
- Document content hash changes (file modified)
- Prompt hash changes (instructions or model updated)
- Model name changes (different LLM used)

This ensures organized files are re-analyzed when conditions change, but saves costs when nothing has changed.

**Example Workflows**:

*Standard workflow (organize once)*:
```bash
docman plan              # Creates suggestions for all unorganized files
docman apply --all -y    # Applies suggestions, marks as organized
docman plan              # Skips organized files, no LLM calls
```

*Re-organize after instruction changes*:
```bash
# Edit .docman/instructions.md with new organization rules
docman plan              # Auto-resets organized files to unorganized (prompt changed)
                        # Generates new suggestions for all files
```

*Force re-processing*:
```bash
docman plan --reprocess  # Processes all files regardless of status
```

*Ignore specific directories*:
```bash
docman ignore archives/ -r -y   # Mark all files in archives/ as ignored
docman plan                      # Skips ignored files
docman unmark archives/ -r -y   # Reset to unorganized to re-process
```

### CLI Structure (`cli.py`)

Main commands:
- `docman init [directory]`: Initialize repository
- `docman plan [path]`: Analyze documents and generate LLM organization suggestions
  - `--reprocess`: Reprocess all files, including those already organized or ignored
  - Shows warnings when duplicates detected to save LLM costs
- `docman status [path]`: Review pending operations (shows paths, confidence, reasons, organization status)
  - Groups duplicate files together visually
  - Shows conflict warnings when multiple files target same destination
- `docman apply [path]`: Apply pending operations (interactive or bulk with `-y`)
- `docman reject [path]`: Reject/delete pending operations without applying
- `docman dedupe [path]`: Find and resolve duplicate files
  - Interactive mode (default): Review each duplicate group, choose which copy to keep
  - Bulk mode (`-y`): Auto-delete duplicates, keep first copy
  - `--dry-run`: Preview changes without deleting files
- `docman unmark [path]`: Reset organization status to 'unorganized' for specified files
  - `--all`: Unmark all files in repository
  - `-r`: Recursively unmark files in subdirectories
- `docman ignore [path]`: Mark files as 'ignored' to exclude from future plan runs
  - `-r`: Recursively ignore files in subdirectories
- `docman llm`: Manage LLM providers (add, list, show, test, set-active, remove)
- `docman config`: Manage repository configuration (set-instructions, show-instructions)

### Duplicate Document Handling

**Architecture**: docman uses content-based deduplication at the database level.

**Key Components**:
1. **Canonical Documents** (`documents` table): One record per unique content (SHA256 hash)
2. **Document Copies** (`document_copies` table): Multiple copies can reference same document
3. **Duplicate Detection**: `find_duplicate_groups()` identifies documents with multiple copies
4. **Conflict Detection**: `detect_target_conflicts()` finds operations targeting same destination

**Workflow for Managing Duplicates**:
```bash
# Standard workflow with deduplication
docman plan              # Shows duplicate warning with count
docman status            # Duplicates grouped with [1a], [1b] numbering
docman dedupe            # Interactively resolve duplicates
docman plan              # Generate suggestions for remaining files
docman apply --all -y    # Apply suggestions (no conflicts)

# Quick bulk deduplication
docman dedupe -y         # Auto-resolve, keep first copy of each
docman dedupe --dry-run  # Preview what would be deleted

# Scope to specific directory
docman dedupe docs/      # Only deduplicate files in docs/
```

**Status Command Enhancements**:
- **Duplicate Grouping**: Files with same content grouped together
  - Sub-numbering: `[1a], [1b], [1c]` for copies in same group
  - Shows content hash for each group
- **Conflict Warnings**: Visual `⚠️ CONFLICT` indicators when files target same destination
- **Summary Statistics**: Shows duplicate group count and files with conflicts
- **Tip Display**: Suggests running `docman dedupe` when duplicates detected

**Plan Command Warnings**:
- Detects duplicates after processing completes
- Shows warning: "Found X duplicate document(s) with Y total copies"
- Estimates potential LLM cost savings from deduplicating first
- Example: "~15 LLM call(s) could be saved by deduplicating first"

**Dedupe Command Features**:
- **Discovery**: Finds all document groups with 2+ copies
- **Path Filtering**: Optional path argument limits scope
- **Interactive Mode**:
  - Shows all copies with metadata (size, modified time)
  - User chooses which copy to keep (or skip group)
  - Options: number (keep), 'a' (keep all), 's' (skip)
- **Bulk Mode** (`-y` flag):
  - Automatically keeps first copy, deletes rest
  - No prompts, fast execution
- **Dry Run** (`--dry-run`):
  - Shows what would be deleted
  - Works with both interactive and bulk modes
- **Database Cleanup**: Deletes `DocumentCopy` and cascades to `Operation`

**Example Duplicate Group Display**:
```
[Group 1/2] 3 copies, hash: abc12345...

  [1] inbox/report.pdf
      Size: 145.2 KB, Modified: 2025-01-15 10:30:45
  [2] backup/old/report.pdf
      Size: 145.2 KB, Modified: 2025-01-10 09:15:22
  [3] downloads/report.pdf
      Size: 145.2 KB, Modified: 2025-01-14 14:20:10

Which copy do you want to keep?
  Enter number to keep that copy
  Enter 'a' to keep all (skip this group)
  Enter 's' to skip this group

Your choice [1]:
```

**Cost Optimization**:
- Duplicates result in N LLM API calls for same content
- Running `dedupe` before `plan` saves (N-1) calls per duplicate group
- Plan command shows estimated savings when duplicates detected
- Example: 100 duplicate invoices = 100 LLM calls → dedupe first = 1 call

### Testing Structure

- **Unit tests** (`tests/unit/`): Test modules in isolation (config, models, file_operations, etc.)
- **Integration tests** (`tests/integration/`): Test full command workflows
  - `test_apply_integration.py`: Apply command (interactive & bulk modes)
  - `test_status_integration.py`: Status command
  - `test_reject_integration.py`: Reject command
  - `test_plan_integration.py`: Plan command (includes mutation tests: stale content, deleted files, model changes, error handling)
    - `test_plan_skips_file_on_llm_failure`: Verifies LLM failures skip files without creating pending operations
    - `test_plan_extraction_failure_not_double_counted`: Confirms extraction failures counted only in `failed_count`
- Uses `CliRunner` from Click for CLI testing
- Test fixtures in `conftest.py`
- Current coverage: 79% (258 tests passing)

## Key Patterns

### Credential Storage
API keys are NEVER stored in plaintext. Use `keyring` library:
```python
import keyring
keyring.set_password("docman", provider_name, api_key)  # Store
api_key = keyring.get_password("docman", provider_name)  # Retrieve
```

### Database Sessions
Use context manager pattern:
```python
with next(get_session()) as session:
    # Use session here
    pass
```

### Error Handling in CLI
Use Click's conventions:
```python
click.secho("Error message", fg="red", err=True)
raise click.Abort()
```

### Content Hashing
Always use `compute_content_hash()` from `models.py` for consistent SHA256 hashing.

### Stale Content Detection
Use `file_needs_rehashing(copy, file_path)` to efficiently check if file changed:
- Returns `True` if `stored_size` or `stored_mtime` differ (needs rehash)
- Returns `False` if metadata matches (skip rehashing for performance)
- Always update stored metadata after processing

### Prompt Hash Caching
When modifying prompts, instructions, or model:
1. Compute new prompt hash using `compute_prompt_hash(system_prompt, instructions, model_name)`
2. Compare with stored `prompt_hash`, `document_content_hash`, `model_name` in `Operation`
3. Regenerate suggestions if any differ
4. This avoids unnecessary LLM API calls

### DocumentConverter Reuse
For batch document processing, reuse the `DocumentConverter` instance:
```python
from docling.document_converter import DocumentConverter

converter = DocumentConverter()
for file_path in files:
    content = extract_content(file_path, converter=converter)
```
Avoids expensive re-initialization on each file. The `plan` command uses this pattern.

### Directory Scoping
When discovering files in subdirectories, pass `root_path` to limit filesystem traversal:
```python
# Efficient: walks only subdir/
files = discover_document_files(repo_root, root_path=subdir_path)

# Inefficient: walks entire repo, then filters
files = [f for f in discover_document_files(repo_root) if f.startswith(subdir_path)]
```
The `plan` command uses scoped discovery for subdirectory operations.

### Structured Output and Provider Capabilities
When adding new LLM providers, declare capabilities and adapt prompts:
```python
# In provider class
@property
def supports_structured_output(self) -> bool:
    return True  # or False for providers without schema support

# In CLI code
system_prompt = build_system_prompt(
    use_structured_output=provider.supports_structured_output
)
```
- Providers with structured output: Configure API schema (Pydantic model), omit format instructions from prompt
- Providers without: Include JSON format instructions in prompt, parse manually
- Template conditionals adapt automatically based on `use_structured_output` flag

## Typical Development Workflow

**Adding a new command**:
1. Add command function to `cli.py` with Click decorators
2. Implement database queries using SQLAlchemy session pattern
3. Add integration tests in `tests/integration/test_<command>_integration.py`
4. Update this CLAUDE.md with command description

**Modifying file operations**:
1. Update `file_operations.py` (uses `shutil.move` for filesystem ops)
2. Add unit tests in `tests/unit/test_file_operations.py`
3. Test conflict resolution: SKIP, OVERWRITE, RENAME strategies

**Database schema changes**:
1. Modify models in `models.py`
2. Generate migration: `alembic revision --autogenerate -m "description"`
3. Review generated migration in `alembic/versions/`
4. Apply: `alembic upgrade head`
5. Update tests to reflect schema changes

**Adding a new LLM provider**:
1. Create provider class in `llm_providers.py` inheriting from `LLMProvider`
2. Implement `generate_suggestions()` and `test_connection()` methods
3. Override `supports_structured_output` property if provider supports native schemas
4. If structured output supported: Configure API with `OrganizationSuggestion` Pydantic model
5. If not supported: Parse JSON response manually in `generate_suggestions()`
6. Add to factory function `get_provider()` and `list_available_models()`
7. Test both structured and unstructured prompt modes
