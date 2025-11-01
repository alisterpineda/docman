"""File operations for docman - moving and organizing documents."""

import shutil
from enum import Enum
from pathlib import Path


class ConflictResolution(Enum):
    """Strategy for handling file conflicts when target already exists."""

    SKIP = "skip"  # Skip the operation, leave both files unchanged
    OVERWRITE = "overwrite"  # Replace target with source
    RENAME = "rename"  # Rename source with suffix (e.g., file_1.pdf)


class FileOperationError(Exception):
    """Base exception for file operation errors."""

    pass


class FileConflictError(FileOperationError):
    """Raised when target file already exists."""

    def __init__(self, source: Path, target: Path) -> None:
        """Initialize conflict error."""
        self.source = source
        self.target = target
        super().__init__(f"Target file already exists: {target}")


class FileNotFoundError(FileOperationError):
    """Raised when source file doesn't exist."""

    def __init__(self, source: Path) -> None:
        """Initialize not found error."""
        self.source = source
        super().__init__(f"Source file not found: {source}")


def move_file(
    source: Path,
    target: Path,
    conflict_resolution: ConflictResolution = ConflictResolution.SKIP,
    create_dirs: bool = True,
) -> Path:
    """
    Move a file from source to target location.

    Args:
        source: Source file path (must exist)
        target: Target file path
        conflict_resolution: Strategy for handling conflicts when target exists
        create_dirs: Whether to create target directories if they don't exist

    Returns:
        The final path where the file was moved to

    Raises:
        FileNotFoundError: If source file doesn't exist
        FileConflictError: If target exists and conflict_resolution is SKIP
        FileOperationError: For other file operation errors
        PermissionError: If insufficient permissions
    """
    # Validate source exists
    if not source.exists():
        raise FileNotFoundError(source)

    if not source.is_file():
        raise FileOperationError(f"Source is not a file: {source}")

    # Ensure target is absolute
    target = target.resolve()

    # Check if source and target are the same
    if source.resolve() == target:
        # No-op: file is already at target location
        return target

    # Handle target directory creation
    if create_dirs:
        target.parent.mkdir(parents=True, exist_ok=True)
    elif not target.parent.exists():
        raise FileOperationError(f"Target directory does not exist: {target.parent}")

    # Handle conflict if target exists
    if target.exists():
        if conflict_resolution == ConflictResolution.SKIP:
            raise FileConflictError(source, target)
        elif conflict_resolution == ConflictResolution.OVERWRITE:
            # Remove target before moving
            target.unlink()
        elif conflict_resolution == ConflictResolution.RENAME:
            # Find an available filename
            target = _get_unique_filename(target)

    # Perform the move
    try:
        # shutil.move handles cross-filesystem moves automatically
        final_path = shutil.move(str(source), str(target))
        return Path(final_path)
    except PermissionError as e:
        raise PermissionError(f"Permission denied moving {source} to {target}: {e}") from e
    except Exception as e:
        raise FileOperationError(f"Failed to move {source} to {target}: {e}") from e


def _get_unique_filename(path: Path) -> Path:
    """
    Generate a unique filename by appending a number suffix.

    Args:
        path: Original path

    Returns:
        A unique path that doesn't exist

    Examples:
        file.pdf -> file_1.pdf
        file_1.pdf -> file_2.pdf
    """
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent

    counter = 1
    while True:
        new_path = parent / f"{stem}_{counter}{suffix}"
        if not new_path.exists():
            return new_path
        counter += 1
