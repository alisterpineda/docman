"""Status command for docman CLI.

This module contains the status command which displays pending organization
operations for a repository.
"""

from pathlib import Path

import click

from docman.cli.utils import (
    detect_target_conflicts,
    find_duplicate_groups,
    require_database,
)
from docman.database import get_session
from docman.models import (
    Document,
    DocumentCopy,
    Operation,
    OperationStatus,
    OrganizationStatus,
)
from docman.repository import RepositoryError, get_repository_root


@click.command()
@click.argument("path", default=None, required=False)
@require_database
def status(path: str | None) -> None:
    """
    Show pending organization operations for a repository.

    Displays all pending operations with suggested file reorganizations,
    including reasons for each suggestion.

    Arguments:
        PATH: Optional path to filter operations (default: show all in repository).

    Examples:
        - 'docman status': Show all pending operations
        - 'docman status docs/': Show pending operations in docs directory
        - 'docman status file.pdf': Show pending operation for specific file
    """
    # Find the repository root
    repo_root = None

    if path:
        # Try to find repository from the provided path
        search_start_path = Path(path).resolve()
        try:
            repo_root = get_repository_root(start_path=search_start_path)
        except RepositoryError:
            # Path doesn't lead to a repository, try from cwd
            try:
                repo_root = get_repository_root(start_path=Path.cwd())
            except RepositoryError:
                click.secho(
                    "Error: Not in a docman repository. Use 'docman init' to create one.",
                    fg="red",
                    err=True,
                )
                raise click.Abort()
    else:
        # No path provided, use current directory
        try:
            repo_root = get_repository_root(start_path=Path.cwd())
        except RepositoryError:
            click.secho(
                "Error: Not in a docman repository. Use 'docman init' to create one.",
                fg="red",
                err=True,
            )
            raise click.Abort()

    repository_path = str(repo_root)

    # Get database session
    session_gen = get_session()
    session = next(session_gen)

    try:
        # Query pending operations for this repository
        query = (
            session.query(Operation, DocumentCopy)
            .join(DocumentCopy, Operation.document_copy_id == DocumentCopy.id)
            .filter(DocumentCopy.repository_path == repository_path)
            .filter(Operation.status == OperationStatus.PENDING)
        )

        # Filter by path if provided
        if path:
            target_path = Path(path).resolve()

            # Check if path is a file or directory
            if target_path.is_file():
                # Single file - filter by exact match
                rel_path = str(target_path.relative_to(repo_root))
                query = query.filter(DocumentCopy.file_path == rel_path)
            elif target_path.is_dir():
                # Directory - filter by prefix
                rel_path = str(target_path.relative_to(repo_root))
                # Match files in this directory (prefix match)
                query = query.filter(DocumentCopy.file_path.startswith(rel_path))

        pending_ops = query.all()

        if not pending_ops:
            click.echo("No pending operations found.")
            if path:
                click.echo(f"  (filtered by: {path})")
            return

        # Detect duplicates and conflicts
        duplicate_groups = find_duplicate_groups(session, repo_root)
        target_conflicts = detect_target_conflicts(session, repo_root)

        # Build a lookup for document_copy_id to document_id
        {copy.id: copy.document_id for _, copy in pending_ops}

        # Separate operations into duplicates and non-duplicates
        duplicate_ops = []
        non_duplicate_ops = []

        for pending_op, doc_copy in pending_ops:
            if doc_copy.document_id in duplicate_groups:
                duplicate_ops.append((pending_op, doc_copy))
            else:
                non_duplicate_ops.append((pending_op, doc_copy))

        # Display header
        click.echo()
        click.secho(f"Pending Operations ({len(pending_ops)}):", bold=True)
        click.echo(f"Repository: {repository_path}")
        if path:
            click.echo(f"Filter: {path}")
        click.echo()

        # Initialize counter for all operations
        group_idx = 1

        # Display duplicate groups first
        if duplicate_ops:
            # Group duplicate operations by document_id
            dup_groups_display: dict[int, list[tuple[Operation, DocumentCopy]]] = {}
            for pending_op, doc_copy in duplicate_ops:
                if doc_copy.document_id not in dup_groups_display:
                    dup_groups_display[doc_copy.document_id] = []
                dup_groups_display[doc_copy.document_id].append((pending_op, doc_copy))

            # Display each duplicate group
            for document_id, group_ops in dup_groups_display.items():
                # Get content hash for display
                group_ops[0][1]
                doc = session.query(Document).filter(Document.id == document_id).first()
                content_hash_display = doc.content_hash[:8] if doc else "unknown"

                # Display group header
                click.secho(
                    f"[  DUPLICATE GROUP - {len(group_ops)} copies, hash: {content_hash_display}...]",
                    fg="yellow",
                    bold=True,
                )
                click.echo()

                # Display each operation in the group
                for sub_idx, (pending_op, doc_copy) in enumerate(group_ops, start=1):
                    # Current path
                    current_path = doc_copy.file_path

                    # Suggested path
                    suggested_dir = pending_op.suggested_directory_path
                    suggested_filename = pending_op.suggested_filename
                    if suggested_dir:
                        suggested_path = f"{suggested_dir}/{suggested_filename}"
                    else:
                        suggested_path = suggested_filename

                    # Check for conflict with this target
                    conflict_warning = ""
                    if suggested_path in target_conflicts:
                        # Find which other operations conflict
                        conflicting_ops = target_conflicts[suggested_path]
                        if len(conflicting_ops) > 1:
                            # Build list of conflicting indices
                            conflict_refs = []
                            for conf_op, conf_copy in conflicting_ops:
                                if conf_copy.id != doc_copy.id:
                                    # Find the index/sub-index of the conflicting operation
                                    # For simplicity, just mark as conflict
                                    conflict_refs.append("another file")
                            if conflict_refs:
                                conflict_warning = f"  CONFLICT: Same target as {conflict_refs[0]}"

                    # Check if it's a move or just a rename
                    operation_type = ""
                    op_color = "cyan"
                    if current_path == suggested_path:
                        operation_type = "(no change)"
                        op_color = "white"

                    # Display operation with sub-numbering
                    click.echo(f"  [{group_idx}{chr(96 + sub_idx)}] {current_path}")

                    # Show organization status
                    status_label = doc_copy.organization_status.value
                    status_color = "white"
                    if doc_copy.organization_status == OrganizationStatus.ORGANIZED:
                        status_color = "green"
                    elif doc_copy.organization_status == OrganizationStatus.IGNORED:
                        status_color = "yellow"
                    click.secho(f"    Status: {status_label}", fg=status_color)

                    click.secho(
                        f"    -> {suggested_path} {operation_type}{conflict_warning}",
                        fg=op_color,
                    )
                    click.echo(f"    Reason: {pending_op.reason}")
                    click.echo()

                group_idx += 1

        # Display non-duplicate operations
        for idx, (pending_op, doc_copy) in enumerate(non_duplicate_ops, start=group_idx):
            # Current path
            current_path = doc_copy.file_path

            # Suggested path
            suggested_dir = pending_op.suggested_directory_path
            suggested_filename = pending_op.suggested_filename
            if suggested_dir:
                suggested_path = f"{suggested_dir}/{suggested_filename}"
            else:
                suggested_path = suggested_filename

            # Check for conflict
            conflict_warning = ""
            if suggested_path in target_conflicts and len(target_conflicts[suggested_path]) > 1:
                conflict_warning = "  CONFLICT"

            # Check if it's a move or just a rename
            if current_path == suggested_path:
                operation_type = "(no change)"
                op_color = "white"
            else:
                operation_type = ""
                op_color = "cyan"

            # Display operation
            click.echo(f"[{idx}] {current_path}")

            # Show organization status
            status_label = doc_copy.organization_status.value
            status_color = "white"
            if doc_copy.organization_status == OrganizationStatus.ORGANIZED:
                status_color = "green"
            elif doc_copy.organization_status == OrganizationStatus.IGNORED:
                status_color = "yellow"
            click.secho(f"  Status: {status_label}", fg=status_color)

            click.secho(f"  -> {suggested_path} {operation_type}{conflict_warning}", fg=op_color)
            click.echo(f"  Reason: {pending_op.reason}")
            click.echo()

        # Display summary
        click.echo("=" * 50)
        click.echo(f"Total pending operations: {len(pending_ops)}")

        # Add duplicate and conflict stats
        if duplicate_groups:
            total_dup_copies = sum(len(copies) for copies in duplicate_groups.values())
            click.secho(
                f"Duplicate groups: {len(duplicate_groups)} ({total_dup_copies} total copies)",
                fg="yellow",
            )

        if target_conflicts:
            total_conflicts = sum(len(ops) for ops in target_conflicts.values())
            click.secho(
                f"Files with conflicting targets: {total_conflicts}",
                fg="yellow",
            )

        click.echo()

        if duplicate_groups:
            click.echo("Tip: Run 'docman dedupe' to resolve duplicates")
            click.echo()

        click.echo("To apply these changes, run:")
        click.echo("  docman review            # Review each operation interactively")
        click.echo("  docman review --apply-all -y    # Apply all operations without prompts")

    finally:
        # Close the session
        try:
            next(session_gen)
        except StopIteration:
            pass
