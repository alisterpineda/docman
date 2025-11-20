# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`docman` is a CLI tool for organizing documents using AI-powered analysis.

**Workflow**: `scan` → `plan` → `status` → `review`

**Core Technologies**:
- **docling** for document content extraction
- **LLM models** (Google Gemini, OpenAI-compatible APIs) for intelligent organization suggestions
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

# Run specific test class
uv run pytest tests/unit/test_config.py::TestEnsureAppConfig

# Run specific test method
uv run pytest tests/unit/test_config.py::TestEnsureAppConfig::test_creates_config_directory
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
alembic -c src/docman/alembic.ini revision --autogenerate -m "description"

# Run migrations to latest version
alembic -c src/docman/alembic.ini upgrade head

# View migration history
alembic -c src/docman/alembic.ini history
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
   - `config.yaml`: Repository configuration (stores folder definitions and variable patterns)

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
   - Stores: `suggested_directory_path`, `suggested_filename`, `reason`
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
  - Describes input structure: organization instructions and document content with XML boundaries
- `user_prompt.j2`: Per-document prompt with XML-tagged content boundaries
  - Organization instructions wrapped in `<organizationInstructions>` XML tags
  - Document content wrapped in `<documentContent>` XML tags with `filePath` attribute
  - File path embedded directly in `<documentContent filePath="...">` for clear association
  - Clean structure without markdown headers, using only XML boundaries
- Smart content truncation: Keeps beginning and end of long documents in equal parts, with paragraph-aware breaks
- Prompt hash caching: Avoids redundant LLM calls when prompts haven't changed

**Provider Abstraction** (`llm_providers.py`):
- `OrganizationSuggestion` Pydantic model: Defines response schema with field validation
- `LLMProvider` abstract base class with `supports_structured_output` property
- `GoogleGeminiProvider` implementation
  - Uses native structured output via `generation_config` with `response_schema`
  - `supports_structured_output = True`: API guarantees schema compliance
  - Custom exceptions: `GeminiSafetyBlockError`, `GeminiEmptyResponseError`
  - Response normalization checks `response.text` and `response.candidates`
- `OpenAICompatibleProvider` implementation
  - Works with: OpenAI official API, LM Studio, text-generation-webui, vLLM
  - `supports_structured_output = True` for official OpenAI API (uses JSON schema mode)
  - `supports_structured_output = False` for custom endpoints (relies on prompt guidance)
  - Custom exceptions: `OpenAIAPIError`, `OpenAIEmptyResponseError`
  - Handles markdown code block wrapping in responses from custom endpoints
- Factory pattern via `get_provider(config, api_key)`
- Output schema: `suggested_directory_path`, `suggested_filename`, `reason`

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
   - Generate organization instructions from folder definitions
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
- Display current path, suggested path, and reason
- Filter by file or directory path

**Review Operations** (`review` command):
- **Interactive mode** (default): Per-operation prompts with [A]pply/[R]eject/[S]kip/[O]pen/[P]rocess/[Q]uit/[H]elp
  - **Apply**: Moves file, marks operation as ACCEPTED, sets organization_status=ORGANIZED
  - **Reject**: Marks operation as REJECTED (preserves for historical record), does NOT move file
  - **Skip**: Leaves operation as PENDING for later review
  - **Open**: Opens file with default system application for preview
  - **Process**: Re-generate suggestion with optional LLM feedback (allows refining suggestions)
- **Bulk apply mode** (`--apply-all`): Auto-apply all operations
  - Options: `-y` (skip confirmation), `--force` (overwrite conflicts), `--dry-run` (preview only)
  - File operations via `file_operations.py` module
  - Updates `DocumentCopy.file_path` after successful move
  - Sets `status=ACCEPTED`, links via `DocumentCopy.accepted_operation_id`
  - Sets `DocumentCopy.organization_status=ORGANIZED`
- **Bulk reject mode** (`--reject-all`): Mark all operations as REJECTED
  - Options: `-y` (skip confirmation), `-r` (recursive), `--dry-run` (preview only)
  - Does NOT move files or change organization status
  - Preserves operations for historical record and few-shot prompting

**File Operations** (`file_operations.py`):
- `move_file()`: Uses `shutil.move()` for cross-filesystem support
- Conflict resolution strategies: SKIP (raise error), OVERWRITE (replace), RENAME (add suffix)
- Creates target directories automatically (`create_dirs=True`)
- Custom exceptions: `FileConflictError`, `FileNotFoundError`, `FileOperationError`

### Organization Status Tracking

**Overview**: Each `DocumentCopy` has an `organization_status` field that tracks whether the file has been organized, is still unorganized, or should be ignored.

**Status Lifecycle**:
1. **New files**: Start as `unorganized`
2. **After `review` (apply)**: Changed to `organized`
3. **User marks as ignored**: Changed to `ignored` via `docman ignore`
4. **User wants to re-process**: Reset to `unorganized` via `docman unmark`

**Behavior by Command**:
- **`plan`**:
  - Skips files with status `organized` or `ignored` by default (saves LLM costs)
  - Use `--reprocess` flag to process all files regardless of status
  - When `--reprocess` is used and changes are detected (content, prompt, or model), status resets to `unorganized`
- **`review`** (apply action):
  - Sets status to `organized` after successfully moving file
  - Also sets to `organized` if file is already at target location (no-op)
- **`review`** (reject action):
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
When `plan --reprocess` processes files marked as `organized` and detects changes, it resets status to `unorganized`:
- Document content hash changes (file modified)
- Prompt hash changes (instructions or model updated)
- Model name changes (different LLM used)

**Note**: Without `--reprocess`, organized files are skipped entirely (filtered out of the query). The auto-reset only applies when `--reprocess` is used and changes are detected.

**Example Workflows**:

*Standard two-step workflow*:
```bash
docman scan -r                  # Scan entire repository, extract content
docman plan                     # Generate LLM suggestions for scanned files
docman review --apply-all -y   # Apply suggestions, marks as organized
docman plan                    # Skips organized files, no LLM calls
```

*Combined workflow (scan + plan in one step)*:
```bash
docman plan --scan -r          # Scan and generate suggestions in one command
docman review --apply-all -y   # Apply suggestions
```

*Add new documents*:
```bash
docman scan new_folder/        # Scan only new documents
docman plan                    # Generate suggestions for newly scanned files
```

*Re-organize after folder definition changes*:
```bash
# Update folder definitions or variable patterns in .docman/config.yaml
docman plan --reprocess   # Process all files including organized ones
                          # Resets organized files to unorganized when prompt changes detected
                          # Generates new suggestions for all files
```

*Force re-processing*:
```bash
docman scan --rescan -r        # Re-scan all files (if content changed)
docman plan --reprocess        # Reprocess all files regardless of status
```

*Ignore specific directories*:
```bash
docman ignore archives/ -r -y   # Mark all files in archives/ as ignored
docman plan                      # Skips ignored files
docman unmark archives/ -r -y   # Reset to unorganized to re-process
```

### Folder Definition System

**Overview**: Provides structured way for users to define document organization hierarchies and filename conventions without writing full instructions manually. Definitions are stored in `.docman/config.yaml` as recursive tree structure.

**Architecture** (`repo_config.py`):
- **`FolderDefinition`**: Dataclass with optional `description`, optional `filename_convention`, and nested `folders` dict
  - `description` is optional and can be None for self-documenting structures (e.g., folders organized purely by variable patterns)
- **Storage**: YAML format in `.docman/config.yaml` under `organization.folders`
- **Variable patterns**: Supports placeholders like `{year}`, `{company}`, `{family_member}` in both folder paths and filename conventions
  - **User-defined**: All variable patterns must be explicitly defined before use
  - **Storage**: Patterns stored in `.docman/config.yaml` under `organization.variable_patterns`
    - Simple format: `{name: description}` (backward compatible)
    - Extended format with values: `{name: {description: ..., values: [...]}}`
  - **Dataclasses**: `PatternValue` (value, description, aliases), `VariablePattern` (description, values)
  - **Functions**: `get_variable_patterns()`, `set_variable_pattern()`, `remove_variable_pattern()`, `get_pattern_values()`, `add_pattern_value()`, `remove_pattern_value()`
  - **Predefined values**: Optional predefined values with descriptions and aliases to help LLM recognize known entities
- **Default filename convention**: Repository-level default stored at `organization.default_filename_convention`
- **Filename convention inheritance**: Folders inherit default convention unless overridden with folder-specific convention
- **Extension preservation**: Filename conventions apply to base name only; original extension always preserved
- **YAML error handling**: Detects malformed config (e.g., merge conflicts) with actionable error messages
- **Tree operations**: Functions for loading (`get_folder_definitions`, `get_default_filename_convention`), saving (`add_folder_definition`, `set_default_filename_convention`), and displaying

**Validation Rules**:
- **Single variable pattern per level**: At any given level in the hierarchy, only ONE unique variable pattern is allowed as a sibling
  - ✓ Allowed: `Parent/{child}` and `Parent/{child}/subdir` (same variable, extending path)
  - ✗ Rejected: `Parent/{child}` and `Parent/{child_alt}` (different variables at same level)
  - ✓ Allowed: `Financial/{year}` and `Personal/{category}` (different parents, no conflict)
  - ✓ Allowed: `Parent/literal` and `Parent/{variable}` (mixing literals with variables is permitted)
- **Validation timing**: Enforced both when adding definitions (`docman define`) AND when loading config from disk
  - On add: Validates before creating new folder entries
  - On load: Validates entire tree structure via `get_folder_definitions()`
- **Error messages**: Clear, actionable errors indicating which variable pattern conflicts and at what path
  - Example: `"Cannot define 'Parent/{child_alt}': Multiple different variable patterns are not allowed at the same level. '{child}' already exists as a sibling."`

**Commands**:
- `docman pattern add <name> --desc "description"`: Add or update a variable pattern definition
  - Example: `docman pattern add year --desc "4-digit year in YYYY format"`
  - Patterns must be defined before use in folder paths or filename conventions
  - `--desc` is required
  - `--path` option to specify repository location (default: current directory)
- `docman pattern list`: List all defined variable patterns with descriptions
  - Shows value count if pattern has predefined values
  - `--path` option to specify repository location
- `docman pattern show <name>`: Show details of a specific variable pattern
  - Displays values and aliases if defined
  - `--path` option to specify repository location
- `docman pattern remove <name>`: Remove a variable pattern (requires confirmation or `-y` flag)
  - `--path` option to specify repository location
- `docman pattern value add <pattern> <value> [--desc "..."] [--alias-of "canonical"]`: Add a value to a pattern
  - `--desc`: Optional description for the value
  - `--alias-of`: Add as an alias of an existing canonical value
  - `--path` option to specify repository location
  - Example: `docman pattern value add company "Acme Corp." --desc "Main company"`
  - Example: `docman pattern value add company "XYZ Corp" --alias-of "Acme Corp."`
- `docman pattern value list <pattern>`: List all values for a pattern
  - `--path` option to specify repository location
- `docman pattern value remove <pattern> <value>`: Remove a value or alias (requires confirmation or `-y` flag)
  - If removing a canonical value, all its aliases are also removed
  - If removing an alias, only the alias is removed
  - `--path` option to specify repository location
- `docman define <path> [--desc "description"] [--filename-convention "pattern"]`: Define/update folder with optional description and filename convention
  - Path uses `/` separator (e.g., `Financial/invoices/{year}`)
  - `--desc` is optional - omit for self-documenting structures where variable patterns provide sufficient context
  - Creates nested structure automatically
  - Updates existing folders without losing children (preserves existing description if --desc not provided)
  - `--filename-convention` sets folder-specific naming pattern (e.g., `{year}-{month}-invoice`)
  - **Note**: All variables used must be defined first via `docman pattern add`
- `docman config set-default-filename-convention "<pattern>"`: Set repository-wide default filename convention
  - Pattern uses variable placeholders (e.g., `{year}-{month}-{description}`)
  - Applied to all folders unless overridden by folder-specific convention
  - `--path` option to specify repository location
  - **Note**: All variables used must be defined first via `docman pattern add`
- `docman config list-dirs`: Display folder tree with box-drawing characters and filename conventions
  - `--path` option to specify repository location
  - Shows default convention at top if set
  - Visual tree structure shows folder-specific conventions

**Example Usage**:
```bash
# Step 1: Define variable patterns (required before use in folder paths or filename conventions)
docman pattern add year --desc "4-digit year in YYYY format"
docman pattern add month --desc "2-digit month in MM format (01-12)"
docman pattern add description --desc "Brief description of document content"
docman pattern add company --desc "Company name extracted from document"
docman pattern add category --desc "Document category (e.g., utilities, office-supplies)"

# Step 2: Set default filename convention for repository
docman config set-default-filename-convention "{year}-{month}-{description}"

# Step 3: Define top-level folder
docman define Financial --desc "Financial documents"

# Step 4: Define nested structure with folder-specific filename convention
docman define Financial/invoices/{year} \
  --desc "Invoices by year (YYYY format)" \
  --filename-convention "{company}-invoice-{year}-{month}"

# Step 5: Define parallel structure using default convention
docman define Financial/receipts/{category} --desc "Personal receipts by category"

# Step 6: View defined structure with conventions
docman config list-dirs
# Output:
# Default Filename Convention:
#   {year}-{month}-{description}
#
# Folder Structure:
# Financial
# ├─ invoices [filename: {company}-invoice-{year}-{month}]
# │  └─ {year}
# └─ receipts
#    └─ {category}

# Example with optional descriptions (self-documenting structure):
# Step 1: Define variable patterns first
docman pattern add FirstName --desc "First name of family member"
docman pattern add Year --desc "4-digit year in YYYY format"

# Step 2: Define folders without descriptions (structure is self-explanatory via variable patterns)
docman define Health
docman define Health/{FirstName}
docman define Health/{FirstName}/{Year}
docman define Career
docman define Career/{FirstName}/{Year}

# The folder structure and variable pattern descriptions provide sufficient context for the LLM
# to understand that Health and Career are top-level categories organized by person and year.
```

**LLM Integration** (`prompt_builder.py`):
- **Auto-generated instructions**: Folder definitions and filename conventions can be used to automatically generate organization instructions
- **`generate_instructions_from_folders()`**: Converts folder structure and filename conventions to markdown instructions for LLM
  - Accepts `repo_root` parameter to load user-defined variable patterns
  - Accepts `default_filename_convention` parameter for repository-level default
  - Generates three sections: folder hierarchy, filename conventions, and variable pattern extraction guidance
  - **Permissive validation**: Displays warnings for undefined variable patterns but continues execution with fallback guidance
- **Generated content includes**:
  - Folder hierarchy tree with descriptions
  - Default filename convention (if set) with inheritance rules
  - Folder-specific filename conventions (overrides)
  - User-defined variable pattern descriptions (loaded from `.docman/config.yaml`)
  - Extension preservation rules
- **Variable Pattern System**:
  - **User-defined only**: No hard-coded patterns; all variables must be explicitly defined via `docman pattern add`
  - **Storage**: Patterns stored in `.docman/config.yaml` under `organization.variable_patterns`
  - **Structure**: Simple `{name: description}` or extended `{name: {description: ..., values: [...]}}`
  - **Predefined values**: Patterns can have predefined values with descriptions and aliases
    - Values help LLM recognize known entities (e.g., company names)
    - Aliases map alternative names to canonical values (e.g., "XYZ Corp" → "Acme Corp.")
    - Generated prompt guidance includes "Known values:" section with values, descriptions, and aliases
  - **Validation**: Using undefined variables in folder paths or filename conventions displays warnings and provides LLM-friendly fallback guidance ("Infer {variable} from document context")
- **Prompt hash consistency**: All operations use same hash computation logic
  - Includes: system prompt + organization instructions + model name
  - Hash computed inline in CLI using `hashlib.sha256()` (not via dedicated function)
  - Changes to folder structure, filename conventions, or variable patterns automatically invalidate existing operations

**Example Workflow**:
```bash
# Step 1: Define variable patterns first (required for use in folder paths and filename conventions)
docman pattern add year --desc "4-digit year in YYYY format"
docman pattern add month --desc "2-digit month in MM format (01-12)"
docman pattern add company --desc "Company name extracted from invoice header"
docman pattern add category --desc "Document category (e.g., utilities, office-supplies)"
docman pattern add description --desc "Brief description of document content"

# Step 2: Set default filename convention
docman config set-default-filename-convention "{year}-{month}-{description}"

# Step 3: Define folder structure with specific conventions
docman define Financial/invoices/{year} \
  --desc "Invoices by year (YYYY format)" \
  --filename-convention "{company}-invoice-{year}-{month}"
docman define Financial/receipts/{category} --desc "Receipts by category"

# Step 4: Use folder definitions to generate instructions automatically
docman scan -r
docman plan

# Folder definitions and filename conventions are automatically converted to LLM instructions:
# - Folder hierarchy with descriptions
# - Default filename convention: {year}-{month}-{description}
# - Folder-specific override for invoices: {company}-invoice-{year}-{month}
# - Variable pattern descriptions from user-defined patterns
# - Extension preservation rules
```

**Example Workflow with Predefined Values**:
```bash
# Define pattern with predefined values for better LLM recognition
docman pattern add company --desc "Company name extracted from document"

# Add known companies with descriptions and aliases
docman pattern value add company "Acme Corp." --desc "Current name after 2020 merger"
docman pattern value add company "XYZ Corporation" --alias-of "Acme Corp."
docman pattern value add company "XYZ Corp" --alias-of "Acme Corp."
docman pattern value add company "Beta Industries" --desc "Technology partner"

# View pattern details
docman pattern show company
# Output:
# Pattern: company
#   Description: Company name extracted from document
#   Values:
#     • Acme Corp. - Current name after 2020 merger
#       Aliases: XYZ Corporation, XYZ Corp
#     • Beta Industries - Technology partner

# LLM prompt will include:
# - Known values:
#     - "Acme Corp." - Current name after 2020 merger
#       (Also known as: "XYZ Corporation", "XYZ Corp")
#     - "Beta Industries" - Technology partner
```

### CLI Structure (`cli.py`)

**Workflow**: `scan` → `plan` → `status` → `review`

Main commands:
- `docman init [directory]`: Initialize repository
- `docman scan [path]`: Scan and extract content from documents (prerequisite for plan)
  - `-r, --recursive`: Recursively scan subdirectories
  - `--rescan`: Force re-scan of already-scanned files
  - Discovers document files and extracts content using docling
  - Stores documents in database without generating LLM suggestions
- `docman plan [path]`: Generate LLM organization suggestions for scanned documents
  - `--reprocess`: Reprocess all files, including those already organized or ignored
  - `--scan`: Run scan first, then generate suggestions (combines both steps)
  - Shows warnings when duplicates detected to save LLM costs
  - Shows warnings for unscanned files
  - **Note**: Requires documents to be scanned first via `docman scan` (or use `--scan` flag)
- `docman status [path]`: Review pending operations (shows paths, reasons, organization status)
  - Groups duplicate files together visually
  - Shows conflict warnings when multiple files target same destination
- `docman review [path]`: Review and process pending operations
  - Interactive mode (default): Choose [A]pply, [R]eject, [S]kip, [O]pen, or [P]rocess for each operation
  - Bulk apply mode: `--apply-all` with optional `-y`, `--force`, `--dry-run`
  - Bulk reject mode: `--reject-all` with optional `-y`, `-r` (recursive), `--dry-run`
- `docman debug-prompt <file_path>`: Debug LLM prompts for a specific file
  - Shows the system prompt and user prompt that would be sent to the LLM
  - Useful for troubleshooting organization suggestions
- `docman dedupe [path]`: Find and resolve duplicate files
  - Interactive mode (default): Review each duplicate group, choose which copy to keep
  - Bulk mode (`-y`): Auto-delete duplicates, keep first copy
  - `--dry-run`: Preview changes without deleting files
  - `-r`: Include files in subdirectories (only applies when path is a directory)
- `docman define <path> [--desc "description"]`: Define folder hierarchies for document organization
  - Supports variable patterns like `{year}`, `{company}` (must be defined first using `docman pattern add`)
  - Stores definitions in `.docman/config.yaml`
- `docman pattern`: Manage variable pattern definitions for use in folder paths and filename conventions
  - `pattern add <name> --desc "description"`: Add or update a variable pattern
  - `pattern list`: List all defined variable patterns
  - `pattern show <name>`: Show details of a specific pattern (includes values and aliases)
  - `pattern remove <name>`: Remove a variable pattern (requires confirmation or `-y` flag)
  - `pattern value add <pattern> <value> [--desc "..."] [--alias-of "..."]`: Add a value or alias
  - `pattern value list <pattern>`: List all values for a pattern
  - `pattern value remove <pattern> <value>`: Remove a value or alias (requires confirmation or `-y` flag)
- `docman unmark [path]`: Reset organization status to 'unorganized' for specified files
  - `--all`: Unmark all files in repository
  - `-r`: Recursively unmark files in subdirectories
  - `-y`: Skip confirmation prompts
- `docman ignore <path>`: Mark files as 'ignored' to exclude from future plan runs
  - `-r`: Recursively ignore files in subdirectories
  - `-y`: Skip confirmation prompts
- `docman llm`: Manage LLM providers (add, list, show, test, set-active, remove)
- `docman config`: Manage repository configuration (set-default-filename-convention, list-dirs)

### Duplicate Document Handling

**Architecture**: docman uses content-based deduplication at the database level.

**Key Components**:
1. **Canonical Documents** (`documents` table): One record per unique content (SHA256 hash)
2. **Document Copies** (`document_copies` table): Multiple copies can reference same document
3. **Duplicate Detection**: `find_duplicate_groups()` in `cli.py` identifies documents with multiple copies
4. **Conflict Detection**: `detect_target_conflicts()` in `cli.py` finds operations targeting same destination

**Workflow for Managing Duplicates**:
```bash
# Standard workflow with deduplication
docman scan -r                 # Scan repository
docman status                  # Shows duplicate warning with count
docman dedupe                  # Interactively resolve duplicates
docman plan                    # Generate suggestions for remaining files
docman review --apply-all -y   # Apply suggestions (no conflicts)

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
  - Options: number (keep), 'a' or 'all' (keep all), 's' or 'skip' (skip group)
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
  Enter 'a' or 'all' to keep all (skip this group)
  Enter 's' or 'skip' to skip this group

Your choice [1]:
```

**Cost Optimization**:
- Duplicates result in N LLM API calls for same content
- Running `dedupe` before `plan` saves (N-1) calls per duplicate group
- Plan command shows estimated savings when duplicates detected
- Example: 100 duplicate invoices = 100 LLM calls → dedupe first = 1 call

### Testing Structure

- **Unit tests** (`tests/unit/`): Test modules in isolation
  - `test_config.py`: App-level config operations (22 tests)
  - `test_repo_config.py`: Repository config operations including `FolderDefinition` serialization, folder definition CRUD, YAML error handling (53 tests)
  - `test_file_operations.py`: File move operations and conflict resolution
  - `test_models.py`: Database model operations
  - `test_llm_config.py`: LLM provider configuration
  - `test_prompt_builder.py`: Prompt generation and template rendering
  - `test_processor.py`: Document content extraction
  - `test_repository.py`: File discovery functions
  - Additional unit tests for helpers, security, and duplicate queries
- **Integration tests** (`tests/integration/`): Test full command workflows
  - `test_review_integration.py`: Review command (interactive mode with apply/reject/skip/open/process, bulk apply mode, bulk reject mode)
  - `test_status_integration.py`: Status command
  - `test_plan_integration.py`: Plan command (includes mutation tests: stale content, deleted files, model changes, error handling)
    - `test_plan_skips_file_on_llm_failure`: Verifies LLM failures skip files without creating pending operations
    - `test_plan_extraction_failure_not_double_counted`: Confirms extraction failures counted only in `failed_count`
  - `test_config_integration.py`: Config commands including `define` and `list-dirs` (39 tests)
  - `test_scan_integration.py`: Scan command
  - `test_dedupe_integration.py`: Dedupe command
  - `test_init_integration.py`: Init command
  - `test_llm_commands_integration.py`: LLM provider management commands
  - `test_debug_prompt_integration.py`: Debug-prompt command
  - `test_database_integration.py`: Database operations
  - `test_app_config_integration.py`: App-level configuration
- Uses `CliRunner` from Click for CLI testing
- Test fixtures in `conftest.py`
- **Test isolation**: Global `autouse` fixture in `conftest.py` automatically isolates ALL tests from user app data
  - The `isolate_app_config` fixture runs for every test automatically (function-scoped)
  - Uses pytest's `tmp_path` to create isolated app config directory per test
  - Sets `DOCMAN_APP_CONFIG_DIR` environment variable to the isolated directory
  - Ensures tests NEVER touch the real user config directory or database
  - No need to manually set the environment variable in individual tests

## Key Patterns

### Credential Storage
API keys are NEVER stored in plaintext. Use `keyring` library:
```python
import keyring
keyring.set_password("docman_llm", provider_name, api_key)  # Store
api_key = keyring.get_password("docman_llm", provider_name)  # Retrieve
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
1. Compute new prompt hash inline using `hashlib.sha256()` with system prompt + organization instructions + model name
2. Compare with stored `prompt_hash`, `document_content_hash`, `model_name` in `Operation`
3. Regenerate suggestions if any differ
4. This avoids unnecessary LLM API calls

Note: While `compute_prompt_hash()` exists in `prompt_builder.py`, the CLI computes hashes inline for consistency.

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
