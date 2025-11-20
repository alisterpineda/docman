"""Prompt building utilities for LLM interactions.

This module handles construction of system and user prompts for document
organization tasks, keeping prompt logic separate from LLM providers.
"""

import functools
import json
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click
from jinja2 import Environment, PackageLoader

from docman.llm_providers import OrganizationSuggestion
from docman.repo_config import FolderDefinition

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# Initialize Jinja2 template environment
_template_env = Environment(loader=PackageLoader("docman", "prompt_templates"))


def _truncate_content_smart(
    content: str,
    max_chars: int = 8000,
    head_ratio: float = 0.6,
) -> tuple[str, bool, int, int]:
    """Truncate content preserving beginning and end.

    Keeps both the beginning and end of the document with a configurable split
    ratio. Attempts to find clean paragraph boundaries for breaks.

    For most documents (invoices, letters, reports), the beginning contains more
    critical information (headers, dates, parties, titles), so the default ratio
    favors the head content (60% head, 40% tail).

    Args:
        content: The document content to truncate.
        max_chars: Maximum number of characters to keep.
        head_ratio: Ratio of available space to allocate to the beginning of
            the document. Must be between 0.0 and 1.0 (exclusive). Default is
            0.6 (60% head, 40% tail).

    Returns:
        Tuple of (truncated_content, was_truncated, original_length, truncated_length).
        was_truncated is True if content was actually truncated.

    Raises:
        ValueError: If head_ratio is not between 0.0 and 1.0 (exclusive).
    """
    # Validate head_ratio
    if not (0.0 < head_ratio < 1.0):
        raise ValueError(
            f"head_ratio must be between 0.0 and 1.0 (exclusive), got {head_ratio}"
        )

    if len(content) <= max_chars:
        return content, False, len(content), len(content)

    # Calculate marker with actual omitted count
    omitted = len(content) - max_chars
    marker = f"\n\n<<<DOCMAN_TRUNCATION: {omitted:,} characters omitted>>>\n\n"

    # Split remaining space according to head_ratio
    available = max_chars - len(marker)
    if available < 0:
        # Edge case: marker itself exceeds max_chars
        available = 0
    head_chars = int(available * head_ratio)
    tail_chars = available - head_chars

    # Find paragraph boundaries for clean breaks
    if head_chars > 0:
        head_content = content[:head_chars]
        if "\n\n" in head_content:
            head = head_content.rsplit("\n\n", 1)[0]
        else:
            head = head_content.rstrip()
    else:
        head = ""

    if tail_chars > 0:
        tail_content = content[-tail_chars:]
        if "\n\n" in tail_content:
            tail = tail_content.split("\n\n", 1)[-1]
        else:
            tail = tail_content.lstrip()
    else:
        tail = ""

    result = f"{head}{marker}{tail}"
    return result, True, len(content), len(result)


def generate_instructions(repo_root: Path) -> str | None:
    """Generate organization instructions from folder definitions.

    Displays warnings for undefined variable patterns and provides fallback guidance.

    Args:
        repo_root: The repository root directory.

    Returns:
        Organization instructions content, or None if no folder definitions exist.
    """
    from docman.repo_config import (
        get_default_filename_convention,
        get_folder_definitions,
    )

    folder_definitions = get_folder_definitions(repo_root)
    if not folder_definitions:
        return None

    default_convention = get_default_filename_convention(repo_root)
    return generate_instructions_from_folders(
        folder_definitions, repo_root, default_convention
    )


def generate_instructions_from_folders(
    folders: dict[str, FolderDefinition],
    repo_root: Path,
    default_filename_convention: str | None = None,
) -> str:
    """Generate organization instructions from folder definitions.

    Creates markdown instructions for the LLM including folder hierarchy,
    filename conventions, and variable pattern guidance. Displays warnings for
    undefined patterns and provides fallback guidance.

    Args:
        folders: Dictionary mapping top-level folder names to FolderDefinition objects.
        repo_root: The repository root directory.
        default_filename_convention: Optional default filename convention for the repository.

    Returns:
        Markdown-formatted instruction text for LLM consumption.
    """
    if not folders:
        return ""

    sections = []

    # Detect existing directories for variable patterns
    existing_dirs = _detect_existing_directories(folders, repo_root)

    # Section 1: Folder Hierarchy
    sections.append("# Document Organization Structure\n")
    sections.append(
        "The following folder structure defines how documents should be organized:\n"
    )
    sections.append(_render_folder_hierarchy(folders, indent=0, existing_dirs=existing_dirs))

    # Section 2: Filename Conventions
    filename_patterns = _extract_filename_patterns(folders, default_filename_convention)
    if filename_patterns or default_filename_convention:
        sections.append("\n# Filename Conventions\n")
        sections.append(
            "Files should be renamed according to the following conventions. "
            "The original file extension must be preserved.\n"
        )

        # Add default convention if set
        if default_filename_convention:
            sections.append(f"\n**Default Convention**: `{default_filename_convention}`")
            sections.append(
                "\n  - This convention applies to all folders unless overridden below"
            )

        # Add folder-specific conventions
        if filename_patterns:
            sections.append("\n**Folder-Specific Conventions**:")
            for folder_path, convention in filename_patterns.items():
                sections.append(f"\n  - `{folder_path}`: `{convention}`")

    # Section 3: Variable Pattern Guidance
    variable_patterns = _extract_variable_patterns(
        folders, repo_root, default_filename_convention
    )
    if variable_patterns:
        sections.append("\n# Variable Pattern Extraction\n")
        sections.append(
            "Some folders and filename conventions use variable patterns (indicated by curly braces like {year}). "
            "Extract these values from the document content:\n"
        )
        for pattern, examples in variable_patterns.items():
            sections.append(f"\n**{pattern}**:")
            sections.append(examples)

    return "\n".join(sections)


def _render_folder_hierarchy(
    folders: dict[str, FolderDefinition],
    indent: int = 0,
    existing_dirs: dict[str, list[str]] | None = None,
    current_path: str = "",
) -> str:
    """Recursively render folder hierarchy as markdown list.

    Args:
        folders: Dictionary of folder names to FolderDefinition objects.
        indent: Current indentation level.
        existing_dirs: Dictionary mapping folder paths to existing directory values.
        current_path: Current path in the folder hierarchy.

    Returns:
        Markdown-formatted folder tree.
    """
    lines = []
    prefix = "  " * indent

    for name, definition in folders.items():
        # Build full path for this folder
        if current_path:
            folder_path = f"{current_path}/{name}"
        else:
            folder_path = name

        # Add folder name and description (only if description is present)
        if definition.description:
            lines.append(f"{prefix}- **{name}/** - {definition.description}")
        else:
            lines.append(f"{prefix}- **{name}/**")

        # Show existing values for variable pattern folders
        if existing_dirs and folder_path in existing_dirs:
            values = existing_dirs[folder_path]
            values_str = ", ".join(values)
            lines.append(f"{prefix}  Existing: {values_str}")

        # Recursively add subfolders
        if definition.folders:
            lines.append(
                _render_folder_hierarchy(
                    definition.folders, indent + 1, existing_dirs, folder_path
                )
            )

    return "\n".join(lines)


def _extract_filename_patterns(
    folders: dict[str, FolderDefinition],
    default_convention: str | None = None,
) -> dict[str, str]:
    """Extract folder-specific filename conventions.

    Args:
        folders: Dictionary of folder names to FolderDefinition objects.
        default_convention: Default filename convention (not included in output).

    Returns:
        Dictionary mapping folder paths to their filename conventions.
    """
    patterns = {}

    def collect_patterns(
        folder_dict: dict[str, FolderDefinition], path_prefix: str = ""
    ) -> None:
        """Recursively collect filename conventions from folder structure."""
        for name, definition in folder_dict.items():
            current_path = f"{path_prefix}/{name}" if path_prefix else name

            # Add filename convention if set
            if definition.filename_convention:
                patterns[current_path] = definition.filename_convention

            # Recurse into subfolders
            if definition.folders:
                collect_patterns(definition.folders, current_path)

    collect_patterns(folders)
    return patterns


def _extract_variable_patterns(
    folders: dict[str, FolderDefinition],
    repo_root: Path,
    default_filename_convention: str | None = None,
) -> dict[str, str]:
    """Extract all variable patterns from folder definitions and filename conventions.

    Displays warnings for undefined patterns and provides fallback guidance.

    Args:
        folders: Dictionary of folder names to FolderDefinition objects.
        repo_root: The repository root directory.
        default_filename_convention: Optional default filename convention.

    Returns:
        Dictionary mapping variable patterns to extraction guidance.
    """
    import re

    patterns = {}

    def collect_patterns(folder_dict: dict[str, FolderDefinition]) -> None:
        """Recursively collect patterns from folder structure."""
        for name, definition in folder_dict.items():
            # Check if folder name contains variables (e.g., {year}, {category})
            if "{" in name and "}" in name:
                # Extract variable name
                matches = re.findall(r"\{(\w+)\}", name)
                for var_name in matches:
                    if var_name not in patterns:
                        patterns[var_name] = _get_pattern_guidance(var_name, repo_root)

            # Check if filename convention contains variables
            if definition.filename_convention and "{" in definition.filename_convention:
                matches = re.findall(r"\{(\w+)\}", definition.filename_convention)
                for var_name in matches:
                    if var_name not in patterns:
                        patterns[var_name] = _get_pattern_guidance(var_name, repo_root)

            # Recurse into subfolders
            if definition.folders:
                collect_patterns(definition.folders)

    # Collect from folder structure
    collect_patterns(folders)

    # Also check default filename convention
    if default_filename_convention and "{" in default_filename_convention:
        matches = re.findall(r"\{(\w+)\}", default_filename_convention)
        for var_name in matches:
            if var_name not in patterns:
                patterns[var_name] = _get_pattern_guidance(var_name, repo_root)

    return patterns


def _get_pattern_guidance(variable_name: str, repo_root: Path) -> str:
    """Generate extraction guidance for a specific variable pattern.

    Loads user-defined pattern from repository config. If pattern is not defined,
    displays a warning to the user and returns LLM-friendly fallback guidance.

    Args:
        variable_name: The variable name (e.g., "year", "category").
        repo_root: The repository root directory.

    Returns:
        Guidance text for extracting this variable. Either user-defined description
        or fallback instruction to infer from context.
    """
    from docman.repo_config import get_variable_patterns

    # Load user-defined patterns
    patterns = get_variable_patterns(repo_root)

    # Check if pattern is defined
    if variable_name not in patterns:
        # Display user-facing warning
        click.secho(
            f"⚠️  Variable pattern '{variable_name}' is undefined - LLM will infer from context",
            fg="yellow",
        )
        click.echo(
            f"    Tip: Define with: docman pattern add {variable_name} --desc '...'"
        )

        # Return LLM-friendly fallback guidance
        return f"\n  - Infer {variable_name} from document context"

    # Get the pattern object
    pattern = patterns[variable_name]

    # Build guidance with description
    lines = [f"\n  - {pattern.description}"]

    # Add known values if any
    if pattern.values:
        lines.append("\n  - Known values:")
        for pv in pattern.values:
            if pv.description:
                lines.append(f"\n    - \"{pv.value}\" - {pv.description}")
            else:
                lines.append(f"\n    - \"{pv.value}\"")
            # Add aliases
            if pv.aliases:
                aliases_str = ", ".join(f'"{a}"' for a in pv.aliases)
                lines.append(f"\n      (Also known as: {aliases_str})")

    return "".join(lines)


def _detect_existing_directories(
    folders: dict[str, FolderDefinition],
    repo_root: Path,
) -> dict[str, list[str]]:
    """Detect existing directory values for variable pattern folders.

    Traverses the folder definition structure and checks the filesystem
    to find existing subdirectories for variable pattern folders. Handles
    nested variable patterns by exploring all actual directories.

    Args:
        folders: Dictionary mapping folder names to FolderDefinition objects.
        repo_root: The repository root directory.

    Returns:
        Dictionary mapping folder paths (containing variable patterns) to lists
        of existing directory names found on disk.
    """
    existing: dict[str, list[str]] = {}

    def collect_existing(
        folder_dict: dict[str, FolderDefinition],
        current_path: str = "",
        disk_paths: list[Path] | None = None,
    ) -> None:
        """Recursively collect existing directories for variable patterns.

        Args:
            folder_dict: Current level of folder definitions.
            current_path: Path with placeholders (e.g., "Clients/{client}").
            disk_paths: List of actual disk paths to check (handles variable expansion).
        """
        if disk_paths is None:
            disk_paths = [repo_root]

        for name, definition in folder_dict.items():
            # Build path to this folder (with placeholders)
            if current_path:
                folder_path = f"{current_path}/{name}"
            else:
                folder_path = name

            # Check if this folder name is a variable pattern
            if "{" in name and "}" in name:
                # Collect values from all current disk paths
                all_values: set[str] = set()
                next_disk_paths: list[Path] = []

                for disk_path in disk_paths:
                    if disk_path.exists() and disk_path.is_dir():
                        try:
                            for item in disk_path.iterdir():
                                # Skip hidden directories and files
                                if item.name.startswith("."):
                                    continue
                                # Only include directories
                                if item.is_dir():
                                    all_values.add(item.name)
                                    next_disk_paths.append(item)
                        except PermissionError:
                            pass  # Skip directories we can't read

                # Sort alphabetically and limit to 10
                if all_values:
                    sorted_values = sorted(all_values)
                    existing[folder_path] = sorted_values[:10]

                # Recurse into subfolders with expanded disk paths
                if definition.folders:
                    collect_existing(definition.folders, folder_path, next_disk_paths)
            else:
                # Literal folder name - update disk paths accordingly
                next_disk_paths = [dp / name for dp in disk_paths]

                # Recurse into subfolders
                if definition.folders:
                    collect_existing(definition.folders, folder_path, next_disk_paths)

    collect_existing(folders)
    return existing


def serialize_folder_definitions(
    folders: dict[str, FolderDefinition],
    default_filename_convention: str | None = None,
) -> str:
    """Serialize folder definitions to JSON for hashing purposes.

    Args:
        folders: Dictionary mapping folder names to FolderDefinition objects.
        default_filename_convention: Optional default filename convention.

    Returns:
        JSON string representation of folder structure and default convention.
    """
    # Convert FolderDefinitions to dict representation
    serializable: dict[str, Any] = {
        "folders": {name: folder.to_dict() for name, folder in folders.items()},
    }

    # Include default convention if set
    if default_filename_convention:
        serializable["default_filename_convention"] = default_filename_convention

    # Convert to JSON with sorted keys for stable hashing
    return json.dumps(serializable, sort_keys=True)


def _generate_schema_example() -> str:
    """Generate a JSON example from the OrganizationSuggestion model.

    Creates a JSON object with field names as keys and their descriptions
    (from Pydantic Field metadata) as placeholder values. This ensures the
    template always matches the actual Pydantic model schema.

    Returns:
        JSON string with field names and placeholder descriptions.
    """
    schema = OrganizationSuggestion.model_json_schema()
    properties = schema.get("properties", {})

    # Build example with human-readable placeholder values
    example = {}
    for field_name, field_info in properties.items():
        # Use field description if available, otherwise create a placeholder
        if "description" in field_info:
            example[field_name] = field_info["description"]
        else:
            # Create a sensible placeholder based on field name
            placeholder = field_name.replace("_", " ").replace("-", " ")
            example[field_name] = f"<{placeholder}>"

    return json.dumps(example, indent=4)


def get_examples(
    session: "Session",
    repo_root: Path,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Get accepted operations where file was actually moved to suggested location.

    Only includes examples where:
    1. Operation status is ACCEPTED
    2. DocumentCopy file_path matches the suggestion (directory_path/filename)
    3. File actually exists at that location on disk

    Args:
        session: SQLAlchemy database session.
        repo_root: Path to the repository root.
        limit: Maximum number of examples to return.

    Returns:
        List of dicts with: file_path, content, suggestion (dict with
        suggested_directory_path, suggested_filename, reason).
    """
    from docman.models import Document, DocumentCopy, Operation, OperationStatus

    repository_path = str(repo_root)

    # Query accepted operations with their document copies and documents
    query = (
        session.query(Operation, DocumentCopy, Document)
        .join(DocumentCopy, Operation.document_copy_id == DocumentCopy.id)
        .join(Document, DocumentCopy.document_id == Document.id)
        .filter(DocumentCopy.repository_path == repository_path)
        .filter(Operation.status == OperationStatus.ACCEPTED)
        .order_by(Operation.created_at.desc())
    )

    examples: list[dict[str, Any]] = []

    for operation, copy, document in query:
        # Check if the file is at the suggested location
        # Normalize paths to use forward slashes for cross-platform compatibility
        # (Windows stores paths with backslashes, but suggestions use forward slashes)
        expected_path = f"{operation.suggested_directory_path}/{operation.suggested_filename}"
        normalized_copy_path = copy.file_path.replace("\\", "/")
        if normalized_copy_path != expected_path:
            # File was not moved to the suggested location (user modified suggestion)
            continue

        # Verify file actually exists on disk
        full_path = repo_root / copy.file_path
        if not full_path.exists():
            continue

        # Check that document has content
        if not document.content:
            continue

        # Build example dict
        example = {
            "file_path": copy.file_path,
            "content": document.content,
            "suggestion": {
                "suggested_directory_path": operation.suggested_directory_path,
                "suggested_filename": operation.suggested_filename,
                "reason": operation.reason,
            },
        }
        examples.append(example)

        if len(examples) >= limit:
            break

    return examples


def format_examples(
    examples: list[dict[str, Any]],
    max_content_chars: int = 500,
    head_ratio: float = 0.6,
) -> str:
    """Format examples as XML with JSON output for inclusion in prompts.

    Uses _truncate_content_smart() for content truncation with smaller
    char limit but same default head/tail ratio as main document.

    Args:
        examples: List of example dicts from get_examples().
        max_content_chars: Maximum characters for example content.
        head_ratio: Ratio of space to allocate to beginning of content.

    Returns:
        Formatted XML string with examples, or empty string if no examples.
    """
    if not examples:
        return ""

    formatted_examples: list[str] = []

    for example in examples:
        file_path = example["file_path"]
        content = example["content"]
        suggestion = example["suggestion"]

        # Truncate content using the same smart truncation as main documents
        truncated_content, was_truncated, original_len, _ = _truncate_content_smart(
            content,
            max_chars=max_content_chars,
            head_ratio=head_ratio,
        )

        # Build exampleContent tag with truncation attributes if needed
        if was_truncated:
            example_content_tag = (
                f'<exampleContent filePath="{escape(file_path)}" '
                f'truncated="true" originalChars="{original_len}">'
            )
        else:
            example_content_tag = f'<exampleContent filePath="{escape(file_path)}">'

        # Format the expected output as JSON
        expected_output = json.dumps(suggestion, indent=4)

        # Build the example XML
        example_xml = (
            f"<example>\n"
            f"{example_content_tag}\n"
            f"{truncated_content}\n"
            f"</exampleContent>\n"
            f"<expectedOutput>\n"
            f"{expected_output}\n"
            f"</expectedOutput>\n"
            f"</example>"
        )
        formatted_examples.append(example_xml)

    return "\n\n".join(formatted_examples)


@functools.lru_cache(maxsize=2)
def build_system_prompt(use_structured_output: bool = False) -> str:
    """Build the static system prompt that defines the LLM's task.

    This prompt is cached for both structured and unstructured output modes.

    Args:
        use_structured_output: If True, omits JSON formatting instructions
            (since the API enforces the schema). If False, includes detailed
            JSON format instructions for models without structured output support.

    Returns:
        System prompt string defining the document organization task.
    """
    template = _template_env.get_template("system_prompt.j2")

    # Generate schema example only when needed (for unstructured output)
    json_schema_example = None
    if not use_structured_output:
        json_schema_example = _generate_schema_example()

    return template.render(
        use_structured_output=use_structured_output,
        json_schema_example=json_schema_example,
    )


def build_user_prompt(
    file_path: str,
    document_content: str,
    organization_instructions: str | None = None,
    examples: str | None = None,
    head_ratio: float = 0.6,
) -> str:
    """Build the dynamic user prompt for a specific document.

    Args:
        file_path: Current path of the file being analyzed.
        document_content: Extracted text content from the document.
        organization_instructions: Document organization instructions.
        examples: Formatted examples from previously organized documents.
        head_ratio: Ratio of available space to allocate to the beginning of
            the document when truncating. Must be between 0.0 and 1.0 (exclusive).
            Default is 0.6 (60% head, 40% tail).

    Returns:
        User prompt string with document-specific information.
    """
    # Apply smart truncation to content
    content, was_truncated, original_length, truncated_length = _truncate_content_smart(
        document_content, head_ratio=head_ratio
    )

    # Render template
    template = _template_env.get_template("user_prompt.j2")
    return template.render(
        file_path=file_path,
        content=content,
        was_truncated=was_truncated,
        original_length=original_length,
        organization_instructions=organization_instructions,
        examples=examples,
    )


def clear_prompt_cache() -> None:
    """Clear cached prompts.

    Useful for testing or when templates are modified during development.
    """
    build_system_prompt.cache_clear()


def compute_prompt_hash(
    system_prompt: str,
    organization_instructions: str | None = None,
    model_name: str | None = None,
) -> str:
    """Compute SHA256 hash of the prompt components.

    This creates a stable identifier for the "static" part of prompts
    (system prompt + organization instructions + model name). When this hash changes,
    it indicates that LLM suggestions should be regenerated.

    Args:
        system_prompt: The system prompt template.
        organization_instructions: Document organization instructions (optional).
        model_name: LLM model name (optional).

    Returns:
        Hexadecimal string representation of the SHA256 hash.
    """
    import hashlib

    # Combine system prompt, organization instructions, and model name
    combined = system_prompt
    if organization_instructions:
        combined += "\n" + organization_instructions
    if model_name:
        combined += "\n" + model_name

    # Compute SHA256 hash
    sha256_hash = hashlib.sha256()
    sha256_hash.update(combined.encode("utf-8"))

    return sha256_hash.hexdigest()
