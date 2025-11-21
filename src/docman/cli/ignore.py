"""Ignore command for marking files to be excluded from processing."""

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
    help="Recursively ignore files in subdirectories",
)
@require_database
def ignore(path: str | None, yes: bool, recursive: bool) -> None:
    """
    Mark files to be ignored by docman.

    Sets the organization status to 'ignored', preventing the files from being
    processed by 'plan' commands (unless --reprocess flag is used). Any existing
    pending operations will be deleted.

    Arguments:
        PATH: Path to file or directory to ignore (required).

    Options:
        -y, --yes: Skip confirmation prompts
        -r, --recursive: Recursively ignore files in subdirectories

    Examples:
        - 'docman ignore docs/': Ignore files in docs directory
        - 'docman ignore docs/ -r': Ignore files in docs and subdirectories
        - 'docman ignore file.pdf': Ignore specific file
    """
    # Validate path argument
    if not path:
        click.secho(
            "Error: Must specify a PATH to ignore files.",
            fg="red",
            err=True,
        )
        click.echo()
        click.echo("Examples:")
        click.echo("  docman ignore docs/")
        click.echo("  docman ignore file.pdf")
        raise click.Abort()

    # Find the repository root
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

    repository_path = str(repo_root)

    # Get database session
    session_gen = get_session()
    session = next(session_gen)

    try:
        # Query document copies for this repository
        query = (
            session.query(DocumentCopy)
            .filter(DocumentCopy.repository_path == repository_path)
        )

        # Filter by path
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
            click.echo("No files found.")
            click.echo(f"  (filtered by: {path})")
            return

        # Show what will be ignored
        click.echo()
        click.secho(f"Files to ignore: {count}", bold=True)
        click.echo(f"Repository: {repository_path}")
        click.echo(f"Filter: {path}")
        if target_path.is_dir() and recursive:
            click.echo("Mode: Recursive")
        elif target_path.is_dir():
            click.echo("Mode: Non-recursive (current directory only)")
        click.echo()

        # Show the files that will be ignored
        if count <= 10:
            # Show all if there are 10 or fewer
            for doc_copy in document_copies:
                click.echo(f"  - {doc_copy.file_path}")
        else:
            # Show first 5 and last 3 if there are more than 10
            for doc_copy in document_copies[:5]:
                click.echo(f"  - {doc_copy.file_path}")
            click.echo(f"  ... and {count - 8} more ...")
            for doc_copy in document_copies[-3:]:
                click.echo(f"  - {doc_copy.file_path}")

        click.echo()

        # Confirm if not using -y flag
        if not yes:
            if not click.confirm(f"Ignore {count} file(s)?"):
                click.echo("Aborted.")
                return

        # Mark all files as ignored and delete pending operations
        for doc_copy in document_copies:
            # Set organization status to ignored
            doc_copy.organization_status = OrganizationStatus.IGNORED

            # Delete any pending operations
            pending_ops = session.query(Operation).filter(
                Operation.document_copy_id == doc_copy.id,
                Operation.status == OperationStatus.PENDING
            ).all()
            for pending_op in pending_ops:
                session.delete(pending_op)

        session.commit()

        click.secho(f"Successfully ignored {count} file(s).", fg="green")

    finally:
        # Close the session
        try:
            next(session_gen)
        except StopIteration:
            pass
