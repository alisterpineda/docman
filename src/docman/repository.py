"""Repository detection and file discovery utilities for docman."""

from pathlib import Path

import click


class RepositoryError(Exception):
    """Raised when repository-related operations fail."""

    pass


def find_repository_root(start_path: Path | None = None) -> Path | None:
    """
    Find the repository root by searching for .docman/ directory.

    Walks up the directory tree from start_path looking for a .docman/ directory.

    Args:
        start_path: The directory to start searching from. Defaults to current directory.

    Returns:
        Path to the repository root (directory containing .docman/), or None if not found.
    """
    if start_path is None:
        start_path = Path.cwd()

    current = start_path.resolve()

    # Walk up the directory tree
    while True:
        docman_dir = current / ".docman"
        if docman_dir.exists() and docman_dir.is_dir():
            return current

        # Check if we've reached the root
        parent = current.parent
        if parent == current:
            # We've reached the filesystem root without finding .docman/
            return None

        current = parent


def validate_repository(repo_root: Path) -> bool:
    """
    Validate that a repository is properly configured.

    Checks if .docman/config.yaml exists in the repository root.

    Args:
        repo_root: The repository root directory.

    Returns:
        True if the repository is valid, False otherwise.
    """
    docman_dir = repo_root / ".docman"
    config_file = docman_dir / "config.yaml"

    return docman_dir.exists() and docman_dir.is_dir() and config_file.exists()


def get_repository_root(start_path: Path | None = None) -> Path:
    """
    Get the repository root, raising an error if not in a repository.

    Args:
        start_path: The directory to start searching from. Defaults to current directory.

    Returns:
        Path to the repository root.

    Raises:
        RepositoryError: If not in a docman repository or repository is invalid.
    """
    repo_root = find_repository_root(start_path)

    if repo_root is None:
        click.secho(
            "Error: Not in a docman repository. Run 'docman init' to create one.",
            fg="red",
            err=True,
        )
        raise RepositoryError("Not in a docman repository")

    if not validate_repository(repo_root):
        click.secho(
            f"Error: Invalid docman repository at {repo_root}. "
            f"Missing .docman/config.yaml file.",
            fg="red",
            err=True,
        )
        raise RepositoryError("Invalid docman repository")

    return repo_root


# Docling-supported file extensions
SUPPORTED_EXTENSIONS = {
    # Documents
    ".pdf",
    ".docx",
    ".doc",
    ".pptx",
    ".ppt",
    ".xlsx",
    ".xls",
    # Text formats
    ".txt",
    ".md",
    ".html",
    ".htm",
}

# Directories to exclude from file discovery
EXCLUDED_DIRS = {
    ".docman",
    ".git",
    ".svn",
    ".hg",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".env",
    ".tox",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}


def discover_document_files(repo_root: Path, root_path: Path | None = None) -> list[Path]:
    """
    Discover all document files in the repository.

    Recursively finds all files with docling-supported extensions,
    excluding common non-document directories.

    Args:
        repo_root: The repository root directory.
        root_path: The starting directory for the walk. If None, defaults to repo_root.
                   Must be within repo_root. Files are still returned as paths relative
                   to repo_root.

    Returns:
        List of file paths relative to the repository root.
    """
    document_files = []

    # Default to repo_root if no root_path specified
    if root_path is None:
        root_path = repo_root

    def should_exclude_dir(dir_path: Path) -> bool:
        """Check if a directory should be excluded from search."""
        return dir_path.name in EXCLUDED_DIRS

    def walk_directory(current_dir: Path) -> None:
        """Recursively walk through directory tree."""
        try:
            for item in current_dir.iterdir():
                # Skip excluded directories
                if item.is_dir():
                    if not should_exclude_dir(item):
                        walk_directory(item)
                # Check if file has supported extension
                elif item.is_file():
                    if item.suffix.lower() in SUPPORTED_EXTENSIONS:
                        # Store relative path
                        rel_path = item.relative_to(repo_root)
                        document_files.append(rel_path)
        except PermissionError:
            # Skip directories we don't have permission to read
            pass

    walk_directory(root_path)
    return sorted(document_files)


def discover_document_files_shallow(repo_root: Path, directory: Path) -> list[Path]:
    """
    Discover document files in a single directory (non-recursive).

    Finds all files with docling-supported extensions in the specified
    directory only, without recursing into subdirectories.

    Args:
        repo_root: The repository root directory.
        directory: The directory to search in (must be within repo_root).

    Returns:
        List of file paths relative to the repository root.
    """
    document_files = []

    try:
        for item in directory.iterdir():
            # Only process files, skip directories
            if item.is_file():
                if item.suffix.lower() in SUPPORTED_EXTENSIONS:
                    # Store relative path
                    rel_path = item.relative_to(repo_root)
                    document_files.append(rel_path)
    except PermissionError:
        # Skip directories we don't have permission to read
        pass

    return sorted(document_files)
