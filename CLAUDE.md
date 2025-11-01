# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`docman` is a CLI tool for organizing documents using AI-powered analysis. It uses:
- **docling** for document content extraction
- **LLM models** (Google Gemini, with more providers planned) for intelligent organization suggestions
- **SQLite database** for tracking documents, copies, and pending operations
- **OS-native credential managers** (Keychain, Secret Service, Windows Credential Manager) for secure API key storage

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
   - Unique constraint on (`repository_path`, `file_path`)

3. **`pending_operations`**: LLM suggestions for file reorganization
   - One per document copy (unique constraint on `document_copy_id`)
   - Stores: `suggested_directory_path`, `suggested_filename`, `reason`, `confidence`
   - `prompt_hash`: SHA256 of system prompt + organization instructions
   - Used to invalidate stale suggestions when prompts change

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

1. **Discovery** (`repository.py`):
   - `discover_document_files()`: Recursive file finding
   - `discover_document_files_shallow()`: Non-recursive
   - Filters by `SUPPORTED_EXTENSIONS` (PDF, DOCX, TXT, etc.)

2. **Content Extraction** (`processor.py`):
   - Uses docling to extract text content
   - Computes content hash for deduplication

3. **Database Storage** (`models.py`):
   - Create/update `Document` (by content hash)
   - Create/update `DocumentCopy` (by repo + file path)

4. **LLM Suggestion** (`cli.py` `plan` command):
   - Load organization instructions from `.docman/instructions.md`
   - Build prompts using `prompt_builder.py`
   - Call LLM provider for suggestions
   - Store in `PendingOperation` with prompt hash

5. **Prompt Hash Validation**:
   - Compare current prompt hash with stored hash
   - Skip LLM call if hash matches (content already analyzed with same instructions)
   - Regenerate suggestions if prompt changed

### CLI Structure (`cli.py`)

Main command groups:
- `docman init [directory]`: Initialize repository
- `docman plan [path]`: Analyze documents and generate organization suggestions
- `docman reset`: Clear pending operations
- `docman llm`: Manage LLM providers (add, list, show, test, set-active, remove)

### Testing Structure

- **Unit tests** (`tests/unit/`): Test individual modules in isolation
- **Integration tests** (`tests/integration/`): Test full command workflows
- Uses `CliRunner` from Click for testing CLI commands
- Test fixtures in `conftest.py`

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

### Prompt Hash Caching
When modifying prompts or organization instructions:
1. Compute new prompt hash using `compute_prompt_hash()`
2. Compare with stored `prompt_hash` in `PendingOperation`
3. Regenerate suggestions if hash differs
4. This avoids unnecessary LLM API calls
