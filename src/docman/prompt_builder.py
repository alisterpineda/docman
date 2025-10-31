"""Prompt building utilities for LLM interactions.

This module handles construction of system and user prompts for document
organization tasks, keeping prompt logic separate from LLM providers.
"""

from pathlib import Path

from docman.repository import EXCLUDED_DIRS


def get_directory_structure(repo_root: Path) -> str:
    """Get a flat list of all directories in the repository.

    Args:
        repo_root: The repository root directory.

    Returns:
        Markdown list of directory paths (e.g., "- /dir1\n- /dir1/dir2").
        Returns empty string if no directories found.
    """
    directories = []

    def should_exclude_dir(dir_path: Path) -> bool:
        """Check if a directory should be excluded."""
        return dir_path.name in EXCLUDED_DIRS

    def walk_directory(current_dir: Path, relative_path: str = "") -> None:
        """Recursively walk through directory tree."""
        try:
            for item in current_dir.iterdir():
                if item.is_dir() and not should_exclude_dir(item):
                    # Calculate relative path
                    if relative_path:
                        item_relative = f"{relative_path}/{item.name}"
                    else:
                        item_relative = f"/{item.name}"
                    directories.append(item_relative)
                    # Recurse into subdirectory
                    walk_directory(item, item_relative)
        except PermissionError:
            # Skip directories we don't have permission to read
            pass

    walk_directory(repo_root)

    if not directories:
        return ""

    # Sort directories for consistent output
    directories.sort()

    # Format as markdown list
    return "\n".join(f"- {d}" for d in directories)


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


def build_system_prompt() -> str:
    """Build the static system prompt that defines the LLM's task.

    Returns:
        System prompt string defining the document organization task.
    """
    return """You are a document organization assistant. Your task is to analyze \
documents and suggest how they should be organized in a file system.

You will be provided with:
1. A list of existing directories in the repository
2. Document organization instructions
3. The current file path
4. The document's content

Based on this information, suggest an appropriate directory path and filename for \
the document.

Provide your suggestion in the following JSON format:
{
    "suggested_directory_path": "path/to/directory",
    "suggested_filename": "filename.ext",
    "reason": "Brief explanation for this organization",
    "confidence": 0.85
}

Guidelines:
1. suggested_directory_path should be a relative path with forward slashes \
(e.g., "finance/invoices/2024")
2. suggested_filename should include the file extension from the original file
3. reason should be a brief explanation (1-2 sentences) of why this makes sense
4. confidence should be a float between 0.0 and 1.0 indicating how confident you \
are in this suggestion
5. Base your suggestions on the document's content, file type (e.g., PDF, DOCX), \
date (if present), and any other relevant metadata you can extract
6. Follow the document organization instructions provided

Return ONLY the JSON object, no additional text or markdown formatting."""


def build_user_prompt(
    file_path: str,
    document_content: str,
    directory_structure: str | None = None,
    organization_instructions: str | None = None,
) -> str:
    """Build the dynamic user prompt for a specific document.

    Args:
        file_path: Current path of the file being analyzed.
        document_content: Extracted text content from the document.
        directory_structure: Optional markdown list of existing directories.
        organization_instructions: Document organization instructions.

    Returns:
        User prompt string with document-specific information.
    """
    # Truncate content if too long (keep first 4000 chars)
    truncated_content = document_content[:4000]
    if len(document_content) > 4000:
        truncated_content += "\n... (content truncated)"

    # Build prompt sections
    sections = []

    # Directory structure (if provided)
    if directory_structure:
        sections.append("## Existing Directory Structure\n")
        sections.append(directory_structure)

    # Document organization instructions (if provided)
    if organization_instructions:
        sections.append("\n## Document Organization Instructions\n")
        sections.append(organization_instructions)

    # Current file information
    sections.append("\n## Current File\n")
    sections.append(f"Path: {file_path}")

    # Document content
    sections.append("\n## Document Content\n")
    sections.append(truncated_content)

    return "\n".join(sections)
