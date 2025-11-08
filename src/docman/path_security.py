"""
Path security validation module for docman.

This module provides security validation for LLM-suggested file paths to prevent
path traversal attacks and ensure all file operations remain within the repository.
"""

from pathlib import Path


class PathSecurityError(Exception):
    """Raised when path validation fails due to security concerns."""

    pass


def validate_path_component(path_str: str, allow_empty: bool = False) -> str:
    """
    Validate a single path component (directory or filename).

    Args:
        path_str: The path component to validate
        allow_empty: If True, allows empty strings (for optional directory paths)

    Returns:
        The validated path string

    Raises:
        PathSecurityError: If the path component fails validation

    Security checks:
        - Rejects parent directory traversal (..)
        - Rejects absolute paths
        - Rejects null bytes
        - Rejects empty strings (unless allow_empty=True)
        - Rejects OS-specific invalid characters
    """
    # Check for empty path
    if not path_str:
        if allow_empty:
            return path_str
        raise PathSecurityError("Path component cannot be empty")

    # Check for null bytes (potential for path injection)
    if "\0" in path_str:
        raise PathSecurityError("Path component cannot contain null bytes")

    # Convert to Path object for analysis
    path = Path(path_str)

    # Check for absolute paths
    if path.is_absolute():
        raise PathSecurityError(
            f"Path component cannot be absolute: {path_str}"
        )

    # Check for parent directory traversal
    # This catches both ".." and paths containing ".." like "safe/../danger"
    parts = path.parts
    if ".." in parts:
        raise PathSecurityError(
            f"Path component cannot contain parent directory traversal (..): {path_str}"
        )

    # Check for OS-specific invalid characters
    # Windows: < > : " | ? *
    # Unix: generally more permissive, but we'll use conservative set
    invalid_chars = {"<", ">", ":", '"', "|", "?", "*", "\0"}
    for char in invalid_chars:
        if char in path_str:
            raise PathSecurityError(
                f"Path component contains invalid character '{char}': {path_str}"
            )

    return path_str


def validate_target_path(
    base_path: Path, suggested_dir: str, suggested_filename: str
) -> Path:
    """
    Validate and construct a safe target path within the repository.

    This function ensures that the combination of base_path, suggested_dir, and
    suggested_filename results in a path that is safely contained within base_path.

    Args:
        base_path: The repository root path (must be absolute)
        suggested_dir: The suggested directory path (relative, may be empty)
        suggested_filename: The suggested filename (must not be empty)

    Returns:
        A validated Path object guaranteed to be within base_path

    Raises:
        PathSecurityError: If validation fails or path escapes repository
        ValueError: If base_path is not absolute

    Security guarantees:
        - Returned path is always within base_path
        - Path traversal attempts (..) are rejected
        - Absolute paths in suggestions are rejected
        - Symlink attacks are prevented via resolve()
    """
    # Ensure base_path is absolute
    if not base_path.is_absolute():
        raise ValueError(f"Base path must be absolute: {base_path}")

    # Validate individual components first
    validate_path_component(suggested_dir, allow_empty=True)
    validate_path_component(suggested_filename, allow_empty=False)

    # Construct the full path
    if suggested_dir:
        full_path = base_path / suggested_dir / suggested_filename
    else:
        full_path = base_path / suggested_filename

    # Resolve to absolute path (handles symlinks, ., .., etc.)
    # This is critical for security - resolve() normalizes the path
    resolved_full = full_path.resolve()
    resolved_base = base_path.resolve()

    # Verify the resolved path is within the base path
    try:
        # relative_to() will raise ValueError if resolved_full is not within resolved_base
        resolved_full.relative_to(resolved_base)
    except ValueError:
        raise PathSecurityError(
            f"Suggested path escapes repository.\n"
            f"  Repository: {resolved_base}\n"
            f"  Suggested: {resolved_full}\n"
            f"  Directory: {suggested_dir!r}\n"
            f"  Filename: {suggested_filename!r}"
        )

    # Return the validated path
    return resolved_full


def validate_repository_path(path: Path, repo_root: Path) -> None:
    """
    Validate that a path is within the repository boundaries.

    This is a defense-in-depth check that can be used before file operations
    to ensure paths haven't been manipulated.

    Args:
        path: The path to validate (should be absolute or will be resolved)
        repo_root: The repository root path

    Raises:
        PathSecurityError: If path is outside repository boundaries
    """
    resolved_path = path.resolve()
    resolved_root = repo_root.resolve()

    try:
        resolved_path.relative_to(resolved_root)
    except ValueError:
        raise PathSecurityError(
            f"Path is outside repository boundaries.\n"
            f"  Repository: {resolved_root}\n"
            f"  Path: {resolved_path}"
        )
