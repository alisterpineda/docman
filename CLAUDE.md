# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`docman` is a CLI tool for organizing documents using AI-powered analysis.

**Workflow**: `plan` → `status` → `apply` or `reject`

**Core Technologies**:
- **docling** for document content extraction
- **LLM models** (Google Gemini) for intelligent organization suggestions
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
   - Tracks: `repository_path`, `file_path`
   - Stale content detection: `stored_content_hash`, `stored_size`, `stored_mtime`
   - Garbage collection: `last_seen_at` (indexed)
   - Unique constraint on (`repository_path`, `file_path`)

3. **`pending_operations`**: LLM suggestions for file reorganization
   - One per document copy (unique constraint on `document_copy_id`)
   - Stores: `suggested_directory_path`, `suggested_filename`, `reason`, `confidence`
   - Invalidation tracking: `prompt_hash` (system prompt + instructions + model), `document_content_hash`, `model_name`
   - Regenerates suggestions when prompt, content, or model changes

### LLM Integration Architecture

**Prompt Building** (`prompt_builder.py`):
- Uses Jinja2 templates in `src/docman/prompt_templates/`
- `system_prompt.j2`: Static task definition (cached)
- `user_prompt.j2`: Per-document prompt with file path, content, and organization instructions
- Smart content truncation: Keeps beginning (60%) and end (30%) of long documents
- Prompt hash caching: Avoids redundant LLM calls when prompts haven't changed

**Provider Abstraction** (`llm_providers.py`):
- `LLMProvider` abstract base class
- `GoogleGeminiProvider` implementation (currently supported)
- Factory pattern via `get_provider(config, api_key)`
- Structured output: JSON with `suggested_directory_path`, `suggested_filename`, `reason`, `confidence`

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
   - `discover_document_files()`: Recursive file finding
   - `discover_document_files_shallow()`: Non-recursive
   - Filters by `SUPPORTED_EXTENSIONS` (PDF, DOCX, TXT, etc.)

3. **Stale Content Detection** (`file_needs_rehashing()`):
   - Checks `stored_size` and `stored_mtime` vs current file
   - Only rehashes if metadata changed (performance optimization)
   - If content changed: updates/creates `Document`, invalidates `PendingOperation`

4. **Content Extraction** (`processor.py`):
   - Uses docling to extract text content
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
   - Store in `PendingOperation` with all tracking fields

### Apply/Reject Workflow

**Reviewing Suggestions** (`status` command):
- Query `PendingOperation` joined with `DocumentCopy`
- Display current path, suggested path, confidence, and reason
- Filter by file or directory path
- Color-coded confidence: green (≥80%), yellow (≥60%), red (<60%)

**Applying Operations** (`apply` command):
- **Interactive mode** (default): Per-operation prompts with [A]pply/[S]kip/[Q]uit/[H]elp
- **Bulk mode** (`-y` flag): Auto-apply all without prompts
- File operations via `file_operations.py` module
- Updates `DocumentCopy.file_path` after successful move
- Deletes `PendingOperation` after applying
- Options: `--force` (overwrite conflicts), `--dry-run` (preview only)

**Rejecting Operations** (`reject` command):
- Deletes `PendingOperation` records without moving files
- Preserves `Document` and `DocumentCopy` records
- Supports recursive (`-r`) and non-recursive directory filtering

**File Operations** (`file_operations.py`):
- `move_file()`: Uses `shutil.move()` for cross-filesystem support
- Conflict resolution strategies: SKIP (raise error), OVERWRITE (replace), RENAME (add suffix)
- Creates target directories automatically (`create_dirs=True`)
- Custom exceptions: `FileConflictError`, `FileNotFoundError`, `FileOperationError`

### CLI Structure (`cli.py`)

Main commands:
- `docman init [directory]`: Initialize repository
- `docman plan [path]`: Analyze documents and generate LLM organization suggestions
- `docman status [path]`: Review pending operations (shows paths, confidence, reasons)
- `docman apply [path]`: Apply pending operations (interactive or bulk with `-y`)
- `docman reject [path]`: Reject/delete pending operations without applying
- `docman llm`: Manage LLM providers (add, list, show, test, set-active, remove)
- `docman config`: Manage repository configuration (set-instructions, show-instructions)

### Testing Structure

- **Unit tests** (`tests/unit/`): Test modules in isolation (config, models, file_operations, etc.)
- **Integration tests** (`tests/integration/`): Test full command workflows
  - `test_apply_integration.py`: Apply command (interactive & bulk modes)
  - `test_status_integration.py`: Status command
  - `test_reject_integration.py`: Reject command
  - `test_plan_integration.py`: Plan command
- Uses `CliRunner` from Click for CLI testing
- Test fixtures in `conftest.py`
- Current coverage: 77% (261 tests passing)

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
2. Compare with stored `prompt_hash`, `document_content_hash`, `model_name` in `PendingOperation`
3. Regenerate suggestions if any differ
4. This avoids unnecessary LLM API calls

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
