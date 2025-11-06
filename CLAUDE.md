# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`docman` is a CLI tool for organizing documents using AI-powered analysis.

**Workflow**: `plan` → `status` → `review`

**Core Technologies**:
- **docling** for document content extraction
- **LLM models**:
  - Cloud: Google Gemini (cross-platform)
  - Local: HuggingFace transformers (cross-platform) or MLX (Apple Silicon only)
- **Pydantic** for structured output schemas and validation
- **SQLite database** for tracking documents, copies, and pending operations
- **OS-native credential managers** for secure API key storage
- **Quantization**:
  - Transformers: bitsandbytes (Linux/Windows only)
  - MLX: Native Apple Silicon optimization (macOS only)

## Development Commands

### Setup
```bash
# Install all dependencies (dev + quantization + mlx)
uv sync --all-extras

# Install base + dev dependencies only (cross-platform)
uv sync --extra dev

# Install for macOS development (with MLX)
uv sync --extra dev --extra mlx

# Install for Linux/Windows development (with quantization)
uv sync --extra dev --extra quantization
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

### Local LLM Setup

**Overview**: docman supports both cloud LLM APIs (Google Gemini) and local models via HuggingFace. Local models run entirely on your machine, requiring no API keys or internet connection. Two local provider types are available:
- **Transformers**: Cross-platform, works on NVIDIA GPUs, AMD GPUs, and CPU
- **MLX**: Optimized for Apple Silicon (M1/M2/M3/M4), best performance on macOS

**Supported Local Models**:

**Transformers models** (cross-platform):
- **Recommended models**:
  - `google/gemma-2b-it` (small, efficient, instruction-tuned)
  - `meta-llama/Llama-2-7b-chat-hf` (good quality, requires access approval)
  - `mistralai/Mistral-7B-Instruct-v0.2` (excellent quality)
- **Pre-quantized options** (smaller downloads):
  - `TheBloke/Llama-2-7B-GPTQ` (GPTQ quantized)
  - `TheBloke/Mistral-7B-Instruct-v0.2-AWQ` (AWQ quantized)

**MLX models** (Apple Silicon only):
- **Recommended models**:
  - `mlx-community/gemma-3n-E4B-it-4bit` (small, optimized for Apple Silicon)
  - `mlx-community/Mistral-7B-Instruct-v0.2-4bit` (excellent quality)
  - `mlx-community/Llama-2-7b-chat-hf-4bit` (good quality)
- **Note**: MLX models are pre-quantized and optimized specifically for Apple Silicon

**NOT supported**:
- ❌ GGUF models (e.g., `*.gguf`) - use llama.cpp instead
- ❌ ONNX models - use native frameworks

**System Requirements**:

**For Transformers models**:
- **NVIDIA GPU recommended**: CUDA support for best performance
  - 4-bit quantization: ~3-4GB VRAM
  - 8-bit quantization: ~6-8GB VRAM
  - Full precision: ~12-16GB VRAM
- **CPU fallback**: Very slow (not recommended)

**For MLX models** (Apple Silicon only):
- **M1/M2/M3/M4 chips**: Optimized unified memory usage
  - 4-bit models: ~3-4GB RAM
  - 8-bit models: ~6-8GB RAM
- **Best performance**: Native Apple Silicon optimization
- **Note**: Only works on macOS with Apple Silicon

**Setup Steps**:

1. **Install dependencies** (platform-specific):
   ```bash
   # macOS (Apple Silicon) - Recommended: Use MLX models
   uv sync --extra mlx  # Base + MLX support (no bitsandbytes)

   # Linux/Windows (NVIDIA GPU) - Use transformers with quantization
   uv sync --extra quantization  # Base + bitsandbytes for runtime quantization

   # Any platform - Full precision or pre-quantized models only
   uv sync  # Base dependencies (transformers, torch, no bitsandbytes/mlx)
   ```

   **Platform Notes**:
   - **macOS**: `bitsandbytes` (runtime quantization) not available → use MLX or pre-quantized models
   - **Linux/Windows**: Best performance with NVIDIA GPU + `quantization` extra
   - **All platforms**: Cloud providers (Google Gemini) work everywhere

2. **Download a model** (automated or manual):
   ```bash
   # Recommended: Use docman's built-in downloader
   # Transformers model:
   docman llm download-model google/gemma-3n-E4B

   # MLX model (Apple Silicon):
   docman llm download-model mlx-community/gemma-3n-E4B-it-4bit

   # Alternative: Manual download with HuggingFace CLI
   pip install huggingface-hub
   huggingface-cli download google/gemma-3n-E4B
   ```

3. **Add local provider**:
   ```bash
   # Interactive wizard (recommended) - offers to download model automatically
   docman llm add

   # Or use command-line arguments - also offers to download if not present

   # Transformers model:
   docman llm add \
     --name my-local-model \
     --provider local \
     --model google/gemma-3n-E4B \
     --quantization 4bit

   # MLX model (Apple Silicon - no quantization flag needed):
   docman llm add \
     --name my-mlx-model \
     --provider local \
     --model mlx-community/gemma-3n-E4B-it-4bit
   ```
   Note: docman automatically detects MLX models and routes them to the MLX provider.

4. **Test the provider**:
   ```bash
   docman llm test my-local-model
   ```

**Understanding Quantization**:

There are three types of quantization/model formats:

1. **MLX pre-quantized models** (Apple Silicon only):
   - Models optimized for Apple Silicon using MLX framework
   - Examples: `mlx-community/gemma-3n-E4B-it-4bit`, `mlx-community/Mistral-7B-Instruct-v0.2-4bit`
   - **Advantage**: Best performance on Apple Silicon, smaller downloads, optimized by MLX community
   - **Usage**: Download and use as-is, docman automatically detects and routes to MLX provider
   - **Note**: Only works on macOS with M1/M2/M3/M4 chips

2. **Transformers pre-quantized models** (cross-platform):
   - Models already quantized and uploaded to HuggingFace (GPTQ, AWQ formats)
   - Examples: `TheBloke/Llama-2-7B-GPTQ`, `TheBloke/Mistral-7B-Instruct-v0.2-AWQ`
   - **Advantage**: Smaller download size, faster to load, optimized by model creators
   - **Usage**: Download and use as-is, docman automatically detects and skips runtime quantization

3. **Runtime quantization** (via bitsandbytes, transformers only):
   - Quantization applied when loading a full-precision model
   - Example: Download `google/gemma-3n-E4B` → docman quantizes to 4-bit at runtime
   - **Advantage**: More control, works with any transformers model
   - **Disadvantage**: Larger downloads, slower initial load
   - **Note**: Only available for transformers models, not MLX

**When to use each**:
- **MLX models (Apple Silicon)**: Best performance on macOS
  ```bash
  docman llm add --provider local --model mlx-community/gemma-3n-E4B-it-4bit
  # No --quantization flag needed! Auto-detected as MLX.
  ```
- **Transformers pre-quantized**: Fast setup, works on all platforms
  ```bash
  docman llm add --provider local --model TheBloke/Mistral-7B-Instruct-v0.2-GPTQ
  # No --quantization flag needed! Auto-detected as pre-quantized.
  ```
- **Runtime quantization**: When pre-quantized version not available
  ```bash
  docman llm add --provider local --model google/gemma-3n-E4B --quantization 4bit
  ```

**Configuration Options**:
- `model`: HuggingFace model identifier (e.g., `google/gemma-3n-E4B`)
- `quantization`: `4bit`, `8bit`, or `None` (auto-skipped for pre-quantized models)
- `model_path`: Optional custom path to model files (defaults to HF cache)
- `endpoint`: Reserved for future vLLM/TGI support (not used currently)

**Quantization Trade-offs** (for runtime quantization):
- **4-bit**: Lowest memory (~3-4GB VRAM), minimal quality loss, fastest loading
- **8-bit**: Balanced memory (~6-8GB VRAM) and quality
- **Full precision**: Highest memory (~12-16GB VRAM), best quality, slowest loading

**Troubleshooting**:

*Model not found*:
```
Error: Model 'google/gemma-3n-E4B' not found.
```
Solution: Download the model first:
```bash
# Recommended
docman llm download-model google/gemma-3n-E4B

# Alternative
huggingface-cli download google/gemma-3n-E4B
```

*Out of memory (OOM)*:
```
Error: Out of memory (OOM) error loading model. Try using 4-bit quantization.
```
Solution: Use more aggressive quantization or reduce model size:
```bash
# If using 8-bit, try 4-bit
docman llm add --provider local --model google/gemma-3n-E4B --quantization 4bit

# If using full precision, try 8-bit
docman llm add --provider local --model google/gemma-3n-E4B --quantization 8bit
```

*No GPU detected*:
Warning: CPU inference will be very slow (minutes per document). Consider:
- Using a cloud LLM provider instead (Google Gemini)
- Running on a machine with CUDA-enabled GPU
- Using a smaller model

*JSON parsing errors*:
Local models sometimes produce malformed JSON. The system attempts to extract JSON from various formats:
- Plain JSON: `{"key": "value"}`
- Markdown code blocks: ` ```json ... ``` `
- Embedded in text: Extracts largest valid JSON object

If repeated JSON errors occur, consider:
- Switching to a cloud provider (more reliable structured output)
- Using a different local model
- Checking model-specific prompt formatting requirements

*bitsandbytes not available on macOS*:
```
ImportError: Quantization requires bitsandbytes, which is not available on macOS.
```
Cause: Trying to use `--quantization 4bit` or `--quantization 8bit` on macOS.

Solution: Use one of these alternatives:
```bash
# 1. MLX models (best for Apple Silicon)
uv sync --extra mlx
docman llm add --provider local --model mlx-community/gemma-3n-E4B-it-4bit

# 2. Pre-quantized transformers models
docman llm add --provider local --model TheBloke/Mistral-7B-Instruct-v0.2-GPTQ

# 3. Full precision (no quantization flag)
docman llm add --provider local --model google/gemma-3n-E4B

# 4. Cloud provider (easiest)
docman llm add --provider google
```

*MLX dependencies not installed* (Apple Silicon):
```
ImportError: MLX dependencies not installed.
```
Solution: Install MLX dependencies:
```bash
uv sync --extra mlx
# Or: pip install mlx mlx-lm
```

*MLX on non-macOS platform*:
```
Error: MLX models are only supported on macOS with Apple Silicon.
```
Cause: Trying to use an MLX model on Linux or Windows.

Solution: Use a transformers model instead:
```bash
# Replace MLX model with transformers equivalent
uv sync --extra quantization
docman llm add --provider local --model google/gemma-3n-E4B --quantization 4bit
# Or use cloud provider
docman llm add --provider google
```

**Performance Considerations**:
- **First inference**: Slow (model loading, ~30-60s for 4-bit)
- **Subsequent inferences**: Fast (model cached in memory)
- **Memory footprint**: Model stays loaded until process exits
- **Batch processing**: Reuses loaded model across all documents in `plan` command

**Migration from Cloud to Local**:

Existing cloud provider users can add a local provider without disrupting current setup:
```bash
# Add local provider
docman llm add --provider local --model google/gemma-3n-E4B --quantization 4bit --name local-model

# Switch to local provider
docman llm set-active local-model

# Switch back to cloud if needed
docman llm set-active google-default
```

**Default Behavior**:
- **New installations**: Interactive wizard defaults to local provider
- **Existing installations**: No changes; cloud providers continue to work
- **Backward compatibility**: All existing commands and configs unchanged

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
- **Cloud Providers**:
  - `GoogleGeminiProvider` implementation
    - Uses native structured output via `generation_config` with `response_schema`
    - `supports_structured_output = True`: API guarantees schema compliance
    - Custom exceptions: `GeminiSafetyBlockError`, `GeminiEmptyResponseError`
    - Response normalization checks `response.text` and `response.candidates`
- **Local Providers**:
  - `LocalTransformerProvider` implementation (cross-platform)
    - Lazy model loading (loads on first inference, not initialization)
    - Supports quantization via `bitsandbytes` (4-bit, 8-bit)
    - `supports_structured_output = False`: Requires manual JSON parsing
    - Uses `extract_json_from_text()` utility to parse free-form model outputs
    - Handles markdown code blocks, embedded JSON, and malformed responses
  - `LocalMLXProvider` implementation (Apple Silicon only)
    - Lazy model loading (loads on first inference, not initialization)
    - Uses Apple's MLX framework via `mlx_lm.load()` and `mlx_lm.generate()`
    - `supports_structured_output = False`: Requires manual JSON parsing
    - Platform check: Only works on macOS (Darwin) systems
    - Optimized for Apple Silicon unified memory architecture
    - No quantization config needed (models are pre-quantized)
  - `is_mlx_model()` utility: Detects MLX models by name pattern (`mlx` or `mlx-community`)
- Factory pattern via `get_provider(config, api_key)` (api_key optional for local)
  - **Auto-routing**: MLX models automatically routed to `LocalMLXProvider`
  - **Platform-aware**: MLX provider only instantiated on macOS
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

**Review Operations** (`review` command):
- **Interactive mode** (default): Per-operation prompts with [A]pply/[R]eject/[S]kip/[Q]uit/[H]elp
  - **Apply**: Moves file, marks operation as ACCEPTED, sets organization_status=ORGANIZED
  - **Reject**: Marks operation as REJECTED (preserves for historical record), does NOT move file
  - **Skip**: Leaves operation as PENDING for later review
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
  - If file content or prompt changes, status automatically resets to `unorganized` (triggers regeneration)
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
When `plan` detects changes to files marked as `organized`, it automatically resets status to `unorganized`:
- Document content hash changes (file modified)
- Prompt hash changes (instructions or model updated)
- Model name changes (different LLM used)

This ensures organized files are re-analyzed when conditions change, but saves costs when nothing has changed.

**Example Workflows**:

*Standard workflow (organize once)*:
```bash
docman plan                    # Creates suggestions for all unorganized files
docman review --apply-all -y   # Applies suggestions, marks as organized
docman plan                    # Skips organized files, no LLM calls
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
- `docman review [path]`: Review and process pending operations
  - Interactive mode (default): Choose [A]pply, [R]eject, or [S]kip for each operation
  - Bulk apply mode: `--apply-all` with optional `-y`, `--force`, `--dry-run`
  - Bulk reject mode: `--reject-all` with optional `-y`, `-r` (recursive), `--dry-run`
- `docman dedupe [path]`: Find and resolve duplicate files
  - Interactive mode (default): Review each duplicate group, choose which copy to keep
  - Bulk mode (`-y`): Auto-delete duplicates, keep first copy
  - `--dry-run`: Preview changes without deleting files
- `docman unmark [path]`: Reset organization status to 'unorganized' for specified files
  - `--all`: Unmark all files in repository
  - `-r`: Recursively unmark files in subdirectories
- `docman ignore [path]`: Mark files as 'ignored' to exclude from future plan runs
  - `-r`: Recursively ignore files in subdirectories
- `docman llm`: Manage LLM providers
  - `add`: Add new provider (interactive wizard or command-line)
  - `list`: List all configured providers
  - `show`: Show details of a provider
  - `test`: Test provider connection
  - `set-active`: Set active provider
  - `remove`: Remove a provider
  - `download-model`: Download HuggingFace models for local inference
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
docman plan                    # Shows duplicate warning with count
docman status                  # Duplicates grouped with [1a], [1b] numbering
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
  - `test_review_integration.py`: Review command (interactive mode with apply/reject/skip, bulk apply mode, bulk reject mode)
  - `test_status_integration.py`: Status command
  - `test_plan_integration.py`: Plan command (includes mutation tests: stale content, deleted files, model changes, error handling)
    - `test_plan_skips_file_on_llm_failure`: Verifies LLM failures skip files without creating pending operations
    - `test_plan_extraction_failure_not_double_counted`: Confirms extraction failures counted only in `failed_count`
- Uses `CliRunner` from Click for CLI testing
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
