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
    head_ratio: float = 0.6,
    tail_ratio: float = 0.3,
) -> tuple[str, bool]:
    """Intelligently truncate content while preserving structure.

    Keeps the beginning and end of the document, which typically contain
    the most important information (title, headers, conclusion, signatures).

    Args:
        content: The document content to truncate.
        max_chars: Maximum number of characters to keep.
        head_ratio: Proportion of max_chars to keep from beginning (default 60%).
        tail_ratio: Proportion of max_chars to keep from end (default 30%).

    Returns:
        Tuple of (truncated_content, was_truncated).
        was_truncated is True if content was actually truncated.
    """
    if len(content) <= max_chars:
        return content, False

    head_chars = int(max_chars * head_ratio)
    tail_chars = int(max_chars * tail_ratio)

    head = content[:head_chars].rstrip()
    tail = content[-tail_chars:].lstrip()

    chars_removed = len(content) - head_chars - tail_chars
    marker = f"\n\n[... {chars_removed:,} characters truncated ...]\n\n"

    return f"{head}{marker}{tail}", True


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


@functools.lru_cache(maxsize=1)
def build_system_prompt() -> str:
    """Build the static system prompt that defines the LLM's task.

    This prompt is cached since it never changes during execution.

    Returns:
        System prompt string defining the document organization task.
    """
    template = _template_env.get_template("system_prompt.j2")
    return template.render()


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
) -> str:
    """Compute SHA256 hash of the prompt components.

    This creates a stable identifier for the "static" part of prompts
    (system prompt + organization instructions). When this hash changes,
    it indicates that LLM suggestions should be regenerated.

    Args:
        system_prompt: The system prompt template.
        organization_instructions: Document organization instructions (optional).

    Returns:
        Hexadecimal string representation of the SHA256 hash.
    """
    import hashlib

    # Combine system prompt and organization instructions
    combined = system_prompt
    if organization_instructions:
        combined += "\n" + organization_instructions

    # Compute SHA256 hash
    sha256_hash = hashlib.sha256()
    sha256_hash.update(combined.encode("utf-8"))

    return sha256_hash.hexdigest()
