"""Unmark command for resetting organization status of files."""

import os
from pathlib import Path

import click

from docman.cli.utils import require_database
from docman.database import get_session
from docman.models import DocumentCopy, Operation, OperationStatus, OrganizationStatus
from docman.repository import RepositoryError, get_repository_root


@click.command()
@click.argument("path", default=None, required=False)
@click.option(
    "--all",
    "-a",
    "unmark_all",
    is_flag=True,
    default=False,
    help="Unmark all files in the repository",
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    default=False,
    help="Skip confirmation prompts",
)
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    default=False,
    help="Recursively unmark files in subdirectories",
)
@require_database
def unmark(path: str | None, unmark_all: bool, yes: bool, recursive: bool) -> None:
    """
    Unmark files that were previously organized or ignored.

    Sets the organization status back to 'unorganized' and deletes any pending
    operations, allowing the files to be reprocessed by the next 'plan' command.

    Arguments:
        PATH: Optional path to unmark files for (default: requires --all flag).

    Options:
        --all, -a: Unmark all files in the repository
        -y, --yes: Skip confirmation prompts
        -r, --recursive: Recursively unmark files in subdirectories

    Examples:
        - 'docman unmark --all': Unmark all files (with confirmation)
        - 'docman unmark --all -y': Unmark all without prompts
        - 'docman unmark docs/': Unmark files in docs directory
        - 'docman unmark docs/ -r': Unmark files in docs and subdirectories
        - 'docman unmark file.pdf': Unmark specific file
    """
    # Validate flags
    if not unmark_all and not path:
        click.secho(
            "Error: Must specify either --all or a PATH to unmark files.",
            fg="red",
            err=True,
        )
        click.echo()
        click.echo("Examples:")
        click.echo("  docman unmark --all")
        click.echo("  docman unmark docs/")
        click.echo("  docman unmark file.pdf")
        raise click.Abort()

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
        # Query document copies for this repository
        query = (
            session.query(DocumentCopy)
            .filter(DocumentCopy.repository_path == repository_path)
            .filter(DocumentCopy.organization_status.in_([OrganizationStatus.ORGANIZED, OrganizationStatus.IGNORED]))
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
                if recursive:
                    # Match files in this directory and all subdirectories (prefix match)
                    query = query.filter(DocumentCopy.file_path.startswith(rel_path))
                else:
                    # Match only files directly in this directory (not subdirectories)
                    sep = os.sep
                    query = query.filter(
                        DocumentCopy.file_path.startswith(rel_path),
                        ~DocumentCopy.file_path.op('LIKE')(f"{rel_path}{sep}%{sep}%")
                    )
            else:
                click.secho(f"Error: Path '{path}' does not exist", fg="red", err=True)
                raise click.Abort()

        document_copies = query.all()
        count = len(document_copies)

        if count == 0:
            click.echo("No organized or ignored files found.")
            if path:
                click.echo(f"  (filtered by: {path})")
            return

        # Show what will be unmarked
        click.echo()
        click.secho(f"Files to unmark: {count}", bold=True)
        click.echo(f"Repository: {repository_path}")
        if path:
            click.echo(f"Filter: {path}")
            if target_path.is_dir() and recursive:
                click.echo("Mode: Recursive")
            elif target_path.is_dir():
                click.echo("Mode: Non-recursive (current directory only)")
        click.echo()

        # Show the files that will be unmarked
        if count <= 10:
            # Show all if there are 10 or fewer
            for doc_copy in document_copies:
                status_label = "organized" if doc_copy.organization_status == OrganizationStatus.ORGANIZED else "ignored"
                click.echo(f"  - {doc_copy.file_path} ({status_label})")
        else:
            # Show first 5 and last 3 if there are more than 10
            for doc_copy in document_copies[:5]:
                status_label = "organized" if doc_copy.organization_status == OrganizationStatus.ORGANIZED else "ignored"
                click.echo(f"  - {doc_copy.file_path} ({status_label})")
            click.echo(f"  ... and {count - 8} more ...")
            for doc_copy in document_copies[-3:]:
                status_label = "organized" if doc_copy.organization_status == OrganizationStatus.ORGANIZED else "ignored"
                click.echo(f"  - {doc_copy.file_path} ({status_label})")

        click.echo()

        # Confirm if not using -y flag
        if not yes:
            if not click.confirm(f"Unmark {count} file(s)?"):
                click.echo("Aborted.")
                return

        # Unmark all files and delete pending operations
        for doc_copy in document_copies:
            # Reset organization status
            doc_copy.organization_status = OrganizationStatus.UNORGANIZED

            # Delete any pending operations
            pending_ops = session.query(Operation).filter(
                Operation.document_copy_id == doc_copy.id,
                Operation.status == OperationStatus.PENDING
            ).all()
            for pending_op in pending_ops:
                session.delete(pending_op)

        session.commit()

        click.secho(f"Successfully unmarked {count} file(s).", fg="green")

    finally:
        # Close the session
        try:
            next(session_gen)
        except StopIteration:
            pass
