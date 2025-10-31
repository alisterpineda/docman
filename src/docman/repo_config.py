"""Repository-level configuration management for docman.

This module handles reading and writing repository-specific configuration,
particularly custom organization instructions stored in .docman/instructions.md.
"""

import os
import subprocess
from pathlib import Path


def get_instructions_path(repo_root: Path) -> Path:
    """Get the path to the repository's custom instructions file.

    Args:
        repo_root: The repository root directory.

    Returns:
        Path to .docman/instructions.md file.
    """
    return repo_root / ".docman" / "instructions.md"


def load_instructions(repo_root: Path) -> str | None:
    """Load custom organization instructions from the repository.

    Args:
        repo_root: The repository root directory.

    Returns:
        Instructions content, or None if not configured or empty.
    """
    instructions_path = get_instructions_path(repo_root)

    if not instructions_path.exists():
        return None

    try:
        content = instructions_path.read_text().strip()
        return content if content else None
    except Exception:
        return None


def save_instructions(repo_root: Path, content: str) -> None:
    """Save custom organization instructions to the repository.

    Creates .docman directory if it doesn't exist.

    Args:
        repo_root: The repository root directory.
        content: Instructions content to save.

    Raises:
        OSError: If file cannot be written.
    """
    instructions_path = get_instructions_path(repo_root)

    # Ensure .docman directory exists
    instructions_path.parent.mkdir(parents=True, exist_ok=True)

    # Write instructions
    instructions_path.write_text(content)


def edit_instructions_interactive(repo_root: Path) -> bool:
    """Open instructions file in user's preferred editor.

    Uses $EDITOR environment variable if set, otherwise falls back to
    sensible defaults (nano on Unix, notepad on Windows).

    If instructions file doesn't exist, creates it with a template.

    Args:
        repo_root: The repository root directory.

    Returns:
        True if editing was successful, False if editor not found or failed.

    Raises:
        OSError: If file operations fail.
    """
    instructions_path = get_instructions_path(repo_root)

    # Get editor from environment or use defaults
    editor = os.environ.get("EDITOR")

    if not editor:
        # Try common editors
        if os.name == "nt":  # Windows
            editor = "notepad"
        else:  # Unix-like
            # Try to find a suitable editor
            for candidate in ["nano", "vim", "vi"]:
                if subprocess.run(
                    ["which", candidate],
                    capture_output=True,
                    check=False,
                ).returncode == 0:
                    editor = candidate
                    break

    if not editor:
        return False

    # Create file with template if it doesn't exist
    if not instructions_path.exists():
        template = """# Document Organization Instructions

Add your custom instructions here for how documents should be organized in this repository.

## Examples:
- Organize invoices by year and month (e.g., finance/invoices/2024/01/)
- Keep all contracts in legal/contracts/
- Use lowercase and hyphens for directory names
"""
        instructions_path.parent.mkdir(parents=True, exist_ok=True)
        instructions_path.write_text(template)

    # Open editor
    try:
        subprocess.run([editor, str(instructions_path)], check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
