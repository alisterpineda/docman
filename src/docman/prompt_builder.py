"""Prompt building utilities for LLM interactions.

This module handles construction of system and user prompts for document
organization tasks, keeping prompt logic separate from LLM providers.
"""

import functools
import json
from pathlib import Path
from typing import Any

import click
from jinja2 import Environment, PackageLoader

# Initialize Jinja2 template environment
_template_env = Environment(loader=PackageLoader("docman", "prompt_templates"))

# Import FolderDefinition for type hints
from docman.repo_config import FolderDefinition


def _truncate_content_smart(
    content: str,
    max_chars: int = 8000,
) -> tuple[str, bool, int, int]:
    """Truncate content preserving beginning and end.

    Keeps both the beginning and end of the document with an even 50/50 split
    of available space. Attempts to find clean paragraph boundaries for breaks.

    Args:
        content: The document content to truncate.
        max_chars: Maximum number of characters to keep.

    Returns:
        Tuple of (truncated_content, was_truncated, original_length, truncated_length).
        was_truncated is True if content was actually truncated.
    """
    if len(content) <= max_chars:
        return content, False, len(content), len(content)

    # Calculate marker with actual omitted count
    omitted = len(content) - max_chars
    marker = f"\n\n[... {omitted:,} characters omitted ...]\n\n"

    # Split remaining space evenly
    available = max_chars - len(marker)
    if available < 0:
        # Edge case: marker itself exceeds max_chars
        available = 0
    head_chars = available // 2
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

    # Return pattern description formatted as guidance
    description = patterns[variable_name]
    return f"\n  - {description}"


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
    return template.render(use_structured_output=use_structured_output)


def build_user_prompt(
    file_path: str,
    document_content: str,
    organization_instructions: str | None = None,
) -> str:
    """Build the dynamic user prompt for a specific document.

    Args:
        file_path: Current path of the file being analyzed.
        document_content: Extracted text content from the document.
        organization_instructions: Document organization instructions.

    Returns:
        User prompt string with document-specific information.
    """
    # Apply smart truncation to content
    content, was_truncated, original_length, truncated_length = _truncate_content_smart(
        document_content
    )

    # Render template
    template = _template_env.get_template("user_prompt.j2")
    return template.render(
        file_path=file_path,
        content=content,
        was_truncated=was_truncated,
        original_length=original_length,
        organization_instructions=organization_instructions,
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
