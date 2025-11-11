"""Prompt building utilities for LLM interactions.

This module handles construction of system and user prompts for document
organization tasks, keeping prompt logic separate from LLM providers.
"""

import functools
import json
from pathlib import Path

from jinja2 import Environment, PackageLoader

# Initialize Jinja2 template environment
_template_env = Environment(loader=PackageLoader("docman", "prompt_templates"))

# Import FolderDefinition for type hints
from docman.repo_config import FolderDefinition


def _truncate_content_smart(
    content: str,
    max_chars: int = 4000,
) -> tuple[str, bool]:
    """Truncate content to fit within character limit.

    Keeps the beginning of the document up to max_chars, including the
    truncation marker. The final result will not exceed max_chars.

    Args:
        content: The document content to truncate.
        max_chars: Maximum number of characters to keep.

    Returns:
        Tuple of (truncated_content, was_truncated).
        was_truncated is True if content was actually truncated.
    """
    if len(content) <= max_chars:
        return content, False

    # Calculate approximate chars removed to determine marker length
    # Use upper bound estimate to ensure we don't exceed max_chars
    estimated_removed = len(content) - max_chars
    marker = f"\n\n[... {estimated_removed:,} characters truncated ...]"

    # Reserve space for the marker
    available_chars = max_chars - len(marker)
    if available_chars < 0:
        # Edge case: marker itself exceeds max_chars
        available_chars = 0

    truncated = content[:available_chars].rstrip()

    return f"{truncated}{marker}", True


def load_organization_instructions(repo_root: Path) -> str | None:
    """Load document organization instructions from repository config.

    Args:
        repo_root: The repository root directory.

    Returns:
        Document organization instructions content, or None if not found.
    """
    instructions_path = repo_root / ".docman" / "instructions.md"

    if not instructions_path.exists():
        return None

    try:
        content = instructions_path.read_text().strip()
        return content if content else None
    except Exception:
        # If we can't read the file, treat as if it doesn't exist
        return None


def load_or_generate_instructions(repo_root: Path) -> str | None:
    """Load instructions from file or generate from folder definitions.

    This helper function tries multiple sources for organization instructions:
    1. First tries to load from instructions.md file
    2. If that fails, tries to generate from folder definitions
    3. Returns None only if both approaches fail

    This allows code paths like regeneration to work regardless of whether
    the user originally used instructions.md or --auto-instructions.

    Args:
        repo_root: The repository root directory.

    Returns:
        Organization instructions content, or None if neither source is available.
    """
    # First try to load from instructions.md
    instructions = load_organization_instructions(repo_root)
    if instructions:
        return instructions

    # Fall back to generating from folder definitions
    from docman.repo_config import get_folder_definitions

    folder_definitions = get_folder_definitions(repo_root)
    if folder_definitions:
        return generate_instructions_from_folders(folder_definitions)

    # Both sources failed
    return None


def generate_instructions_from_folders(
    folders: dict[str, FolderDefinition]
) -> str:
    """Generate organization instructions from folder definitions.

    Creates markdown instructions for the LLM including folder hierarchy
    and variable pattern guidance.

    Args:
        folders: Dictionary mapping top-level folder names to FolderDefinition objects.

    Returns:
        Markdown-formatted instruction text for LLM consumption.
    """
    if not folders:
        return ""

    sections = []

    # Section 1: Folder Hierarchy
    sections.append("# Document Organization Structure\n")
    sections.append(
        "The following folder structure defines how documents should be organized:\n"
    )
    sections.append(_render_folder_hierarchy(folders, indent=0))

    # Section 2: Variable Pattern Guidance
    variable_patterns = _extract_variable_patterns(folders)
    if variable_patterns:
        sections.append("\n# Variable Pattern Extraction\n")
        sections.append(
            "Some folders use variable patterns (indicated by curly braces like {year}). "
            "Extract these values from the document content:\n"
        )
        for pattern, examples in variable_patterns.items():
            sections.append(f"\n**{pattern}**:")
            sections.append(examples)

    return "\n".join(sections)


def _render_folder_hierarchy(
    folders: dict[str, FolderDefinition], indent: int = 0
) -> str:
    """Recursively render folder hierarchy as markdown list.

    Args:
        folders: Dictionary of folder names to FolderDefinition objects.
        indent: Current indentation level.

    Returns:
        Markdown-formatted folder tree.
    """
    lines = []
    prefix = "  " * indent

    for name, definition in folders.items():
        # Add folder name and description
        lines.append(f"{prefix}- **{name}/** - {definition.description}")

        # Recursively add subfolders
        if definition.folders:
            lines.append(_render_folder_hierarchy(definition.folders, indent + 1))

    return "\n".join(lines)


def _extract_variable_patterns(
    folders: dict[str, FolderDefinition]
) -> dict[str, str]:
    """Extract all variable patterns from folder definitions with usage guidance.

    Args:
        folders: Dictionary of folder names to FolderDefinition objects.

    Returns:
        Dictionary mapping variable patterns to extraction guidance.
    """
    patterns = {}

    def collect_patterns(folder_dict: dict[str, FolderDefinition]) -> None:
        """Recursively collect patterns from folder structure."""
        for name, definition in folder_dict.items():
            # Check if folder name contains variables (e.g., {year}, {category})
            if "{" in name and "}" in name:
                # Extract variable name
                import re

                matches = re.findall(r"\{(\w+)\}", name)
                for var_name in matches:
                    if var_name not in patterns:
                        patterns[var_name] = _get_pattern_guidance(var_name)

            # Recurse into subfolders
            if definition.folders:
                collect_patterns(definition.folders)

    collect_patterns(folders)
    return patterns


def _get_pattern_guidance(variable_name: str) -> str:
    """Generate extraction guidance for a specific variable pattern.

    Args:
        variable_name: The variable name (e.g., "year", "category").

    Returns:
        Guidance text for extracting this variable.
    """
    # Common pattern guidance
    guidance_map = {
        "year": (
            "\n  - Extract 4-digit year (YYYY format) from document content or metadata"
            "\n  - Examples: 2024, 2025"
            "\n  - Check document dates, invoice dates, fiscal year references"
        ),
        "month": (
            "\n  - Extract 2-digit month (MM format) from document content or metadata"
            "\n  - Examples: 01 for January, 12 for December"
            "\n  - Use leading zeros (e.g., 01 not 1)"
        ),
        "category": (
            "\n  - Determine category based on document type and content"
            "\n  - Use lowercase with hyphens for multi-word categories"
            "\n  - Examples: office-supplies, utilities, travel, meals"
        ),
        "company": (
            "\n  - Extract company name from document header, sender, or subject"
            "\n  - Use lowercase with hyphens for multi-word names"
            "\n  - Remove Inc., LLC, Ltd. suffixes"
            "\n  - Examples: acme-corp, global-tech"
        ),
        "client": (
            "\n  - Extract client/customer name from document"
            "\n  - Use lowercase with hyphens for multi-word names"
            "\n  - Examples: smith-industries, jones-llc"
        ),
        "project": (
            "\n  - Extract project name or code from document"
            "\n  - Use lowercase with hyphens"
            "\n  - Examples: website-redesign, mobile-app, q4-campaign"
        ),
    }

    # Return specific guidance or generic guidance
    return guidance_map.get(
        variable_name.lower(),
        f"\n  - Extract {variable_name} value from document content"
        "\n  - Use lowercase with hyphens for multi-word values"
        "\n  - Be consistent with naming",
    )


def serialize_folder_definitions(folders: dict[str, FolderDefinition]) -> str:
    """Serialize folder definitions to JSON for hashing purposes.

    Args:
        folders: Dictionary mapping folder names to FolderDefinition objects.

    Returns:
        JSON string representation of folder structure.
    """
    # Convert FolderDefinitions to dict representation
    serializable = {name: folder.to_dict() for name, folder in folders.items()}

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
    content, was_truncated = _truncate_content_smart(document_content)

    # Render template
    template = _template_env.get_template("user_prompt.j2")
    return template.render(
        file_path=file_path,
        content=content,
        was_truncated=was_truncated,
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
