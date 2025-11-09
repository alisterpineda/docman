"""Prompt building utilities for LLM interactions.

This module handles construction of system and user prompts for document
organization tasks, keeping prompt logic separate from LLM providers.
"""

import functools
from pathlib import Path

from jinja2 import Environment, PackageLoader

# Initialize Jinja2 template environment
_template_env = Environment(loader=PackageLoader("docman", "prompt_templates"))


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
    additional_instructions: str | None = None,
) -> str:
    """Build the dynamic user prompt for a specific document.

    Args:
        file_path: Current path of the file being analyzed.
        document_content: Extracted text content from the document.
        organization_instructions: Document organization instructions.
        additional_instructions: Optional additional steering instructions for
            re-processing a specific document.

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
        additional_instructions=additional_instructions,
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
