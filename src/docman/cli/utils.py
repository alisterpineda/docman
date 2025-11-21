"""
Shared CLI utility functions for docman.

This module contains common utility functions used across multiple CLI commands,
including database decorators, cleanup functions, and duplicate detection utilities.
"""

from pathlib import Path

import click
from sqlalchemy import func

from docman.config import ensure_app_config
from docman.database import ensure_database
from docman.models import (
    DocumentCopy,
    Operation,
    OperationStatus,
    get_utc_now,
)


def require_database(f):
    """Decorator to ensure database and app config are initialized before command runs.

    This decorator should be applied to commands that need database access.
    Commands that don't touch the database (like --help, llm, config) skip this overhead.
    """
    def wrapper(*args, **kwargs):
        try:
            ensure_app_config()
        except OSError as e:
            click.secho(
                f"Warning: Failed to initialize app config: {e}", fg="yellow", err=True
            )

        try:
            ensure_database()
        except Exception as e:
            click.secho(
                f"Warning: Failed to initialize database: {e}", fg="yellow", err=True
            )

        return f(*args, **kwargs)

    # Preserve function metadata for Click
    wrapper.__name__ = f.__name__
    wrapper.__doc__ = f.__doc__
    return wrapper


def cleanup_orphaned_copies(session, repo_root: Path) -> tuple[int, int]:
    """Clean up document copies for files that no longer exist.

    This function performs garbage collection by:
    1. Checking all DocumentCopy records for the repository
    2. Verifying if the file still exists on disk
    3. Deleting copies for missing files (cascades to Operation)
    4. Updating last_seen_at for files that exist

    Args:
        session: SQLAlchemy database session.
        repo_root: Path to the repository root directory.

    Returns:
        Tuple of (deleted_count, updated_count).
    """
    repository_path = str(repo_root)

    # Query all copies for this repository
    copies = (
        session.query(DocumentCopy)
        .filter(DocumentCopy.repository_path == repository_path)
        .all()
    )

    deleted_count = 0
    updated_count = 0
    current_time = get_utc_now()

    for copy in copies:
        file_path = repo_root / copy.file_path

        if not file_path.exists():
            # File no longer exists - delete the copy (cascades to pending operations)
            session.delete(copy)
            deleted_count += 1
        else:
            # File exists - update last_seen_at
            copy.last_seen_at = current_time
            updated_count += 1

    session.commit()
    return deleted_count, updated_count


def find_duplicate_groups(session, repo_root: Path) -> dict[int, list[DocumentCopy]]:
    """Find all documents that have multiple copies in the repository.

    Groups DocumentCopy records by their document_id to identify duplicates.

    Args:
        session: SQLAlchemy database session.
        repo_root: Path to the repository root directory.

    Returns:
        Dictionary mapping document_id to list of DocumentCopy records.
        Only includes documents with 2 or more copies (duplicates).
    """
    repository_path = str(repo_root)

    # Query to find documents with multiple copies
    # First, get document_ids that have count > 1
    duplicate_doc_ids = (
        session.query(DocumentCopy.document_id)
        .filter(DocumentCopy.repository_path == repository_path)
        .group_by(DocumentCopy.document_id)
        .having(func.count(DocumentCopy.id) > 1)
        .all()
    )

    # Extract just the IDs
    doc_ids = [doc_id for (doc_id,) in duplicate_doc_ids]

    if not doc_ids:
        return {}

    # Now get all copies for these documents, ordered by ID for predictable behavior
    copies = (
        session.query(DocumentCopy)
        .filter(
            DocumentCopy.document_id.in_(doc_ids),
            DocumentCopy.repository_path == repository_path,
        )
        .order_by(DocumentCopy.id)
        .all()
    )

    # Group by document_id
    groups: dict[int, list[DocumentCopy]] = {}
    for copy in copies:
        if copy.document_id not in groups:
            groups[copy.document_id] = []
        groups[copy.document_id].append(copy)

    return groups


def detect_target_conflicts(
    session, repo_root: Path
) -> dict[str, list[tuple[Operation, DocumentCopy]]]:
    """Detect pending operations that would create filename conflicts.

    Identifies cases where multiple files would be moved to the same target location.

    Args:
        session: SQLAlchemy database session.
        repo_root: Path to the repository root directory.

    Returns:
        Dictionary mapping target path to list of (Operation, DocumentCopy) tuples.
        Only includes target paths with multiple operations (conflicts).
    """
    repository_path = str(repo_root)

    # Query all pending operations with their copies
    ops = (
        session.query(Operation, DocumentCopy)
        .join(DocumentCopy, Operation.document_copy_id == DocumentCopy.id)
        .filter(DocumentCopy.repository_path == repository_path)
        .filter(Operation.status == OperationStatus.PENDING)
        .all()
    )

    # Group by target path
    target_paths: dict[str, list[tuple[Operation, DocumentCopy]]] = {}
    for op, copy in ops:
        # Build target path
        if op.suggested_directory_path:
            target = f"{op.suggested_directory_path}/{op.suggested_filename}"
        else:
            target = op.suggested_filename

        if target not in target_paths:
            target_paths[target] = []
        target_paths[target].append((op, copy))

    # Return only paths with conflicts (multiple files to same location)
    conflicts = {path: ops for path, ops in target_paths.items() if len(ops) > 1}

    return conflicts


def detect_conflicts_in_operations(
    pending_ops: list[tuple[Operation, DocumentCopy]], repo_root: Path
) -> dict[str, list[tuple[Operation, DocumentCopy]]]:
    """Detect conflicts within a specific list of pending operations.

    Identifies cases where multiple operations would move files to the same target location.

    Args:
        pending_ops: List of (Operation, DocumentCopy) tuples to check.
        repo_root: Path to the repository root directory.

    Returns:
        Dictionary mapping target path to list of (Operation, DocumentCopy) tuples.
        Only includes target paths with multiple operations (conflicts).
    """
    # Group by target path
    target_paths: dict[str, list[tuple[Operation, DocumentCopy]]] = {}
    for op, copy in pending_ops:
        # Build target path
        if op.suggested_directory_path:
            target = f"{op.suggested_directory_path}/{op.suggested_filename}"
        else:
            target = op.suggested_filename

        if target not in target_paths:
            target_paths[target] = []
        target_paths[target].append((op, copy))

    # Return only paths with conflicts (multiple files to same location)
    conflicts = {path: ops for path, ops in target_paths.items() if len(ops) > 1}

    return conflicts


def get_duplicate_summary(session, repo_root: Path) -> tuple[int, int]:
    """Get summary statistics about duplicate documents in the repository.

    Args:
        session: SQLAlchemy database session.
        repo_root: Path to the repository root directory.

    Returns:
        Tuple of (unique_duplicated_docs, total_duplicate_copies).
        - unique_duplicated_docs: Number of distinct documents that have duplicates
        - total_duplicate_copies: Total number of duplicate file copies
    """
    duplicate_groups = find_duplicate_groups(session, repo_root)

    unique_duplicated_docs = len(duplicate_groups)
    total_duplicate_copies = sum(len(copies) for copies in duplicate_groups.values())

    return unique_duplicated_docs, total_duplicate_copies
