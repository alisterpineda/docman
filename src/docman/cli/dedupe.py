"""Dedupe command for finding and resolving duplicate files."""

from datetime import datetime
from pathlib import Path

import click

from docman.cli.utils import find_duplicate_groups, require_database
from docman.database import get_session
from docman.models import Document, DocumentCopy
from docman.repository import RepositoryError, get_repository_root


@click.command()
@click.argument("path", default=None, required=False)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    default=False,
    help="Automatically delete duplicate copies without confirmation (bulk mode)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be deleted without actually deleting files",
)
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    default=False,
    help="Include files in subdirectories (only applies when path is a directory)",
)
@require_database
def dedupe(path: str | None, yes: bool, dry_run: bool, recursive: bool) -> None:
    """
    Find and resolve duplicate files in the repository.

    Identifies documents with multiple copies (same content, different locations)
    and allows you to delete duplicates, keeping only one copy of each document.

    Interactive mode (default): Review each duplicate group and choose which copy to keep.
    Bulk mode (-y): Automatically keep the first copy found and delete the rest.

    Arguments:
        PATH: Optional path to limit deduplication scope (default: entire repository).

    Options:
        -y, --yes: Skip confirmation prompts (bulk mode)
        --dry-run: Preview changes without modifying files
        -r, --recursive: Include files in subdirectories (only applies when path is a directory)

    Examples:
        - 'docman dedupe': Interactive deduplication of entire repository
        - 'docman dedupe docs/': Deduplicate only files directly in docs directory
        - 'docman dedupe docs/ -r': Deduplicate files in docs directory and subdirectories
        - 'docman dedupe -y --dry-run': Preview bulk deduplication
        - 'docman dedupe -y': Auto-delete duplicates (keep first copy)
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

    # Get database session
    session_gen = get_session()
    session = next(session_gen)

    try:
        # Find all duplicate groups
        all_duplicate_groups = find_duplicate_groups(session, repo_root)

        # Filter by path if provided
        if path:
            target_path = Path(path).resolve()

            # Validate path exists
            if not target_path.exists():
                click.secho(f"Error: Path '{path}' does not exist", fg="red", err=True)
                raise click.Abort()

            # Validate path is within repository
            try:
                target_path.relative_to(repo_root)
            except ValueError:
                click.secho(
                    f"Error: Path '{path}' is outside the repository at {repo_root}",
                    fg="red",
                    err=True,
                )
                raise click.Abort()

            # Filter duplicate groups to only include copies in target path
            filtered_groups: dict[int, list[DocumentCopy]] = {}

            if target_path.is_file():
                # Single file - filter by exact match
                rel_path = str(target_path.relative_to(repo_root))
                for doc_id, copies in all_duplicate_groups.items():
                    matching_copies = [
                        copy for copy in copies if copy.file_path == rel_path
                    ]
                    # Only include if we still have duplicates after filtering
                    if len(matching_copies) > 1:
                        filtered_groups[doc_id] = matching_copies
            elif target_path.is_dir():
                # Directory - filter by filesystem path relationship
                for doc_id, copies in all_duplicate_groups.items():
                    if recursive:
                        # Match files in this directory and all subdirectories
                        matching_copies = [
                            copy
                            for copy in copies
                            if (repo_root / copy.file_path).resolve().is_relative_to(target_path)
                        ]
                    else:
                        # Match only files directly in this directory (not subdirectories)
                        matching_copies = [
                            copy
                            for copy in copies
                            if (repo_root / copy.file_path).resolve().parent == target_path
                        ]

                    # Only include if we still have duplicates after filtering
                    if len(matching_copies) > 1:
                        filtered_groups[doc_id] = matching_copies

            duplicate_groups = filtered_groups
        else:
            duplicate_groups = all_duplicate_groups

        if not duplicate_groups:
            click.echo("No duplicate files found.")
            if path:
                click.echo(f"  (searched in: {path})")
            return

        # Calculate statistics
        total_groups = len(duplicate_groups)
        total_copies = sum(len(copies) for copies in duplicate_groups.values())
        duplicate_copies = total_copies - total_groups  # All but one per group

        # Display header
        click.echo()
        click.secho(f"Found {total_groups} duplicate group(s)", bold=True)
        click.echo(f"Total copies: {total_copies}")
        click.echo(f"Duplicates to resolve: {duplicate_copies}")
        if path:
            click.echo(f"Scope: {path}")
            if target_path.is_dir():
                if recursive:
                    click.echo("Mode: Recursive")
                else:
                    click.echo("Mode: Non-recursive (current directory only)")
        click.echo()

        if dry_run:
            click.secho("DRY RUN MODE - No files will be deleted", fg="yellow")
            click.echo()

        # Track what to delete
        copies_to_delete: list[DocumentCopy] = []

        # Process each duplicate group
        for group_idx, (document_id, copies) in enumerate(duplicate_groups.items(), start=1):
            # Get document for display
            doc = session.query(Document).filter(Document.id == document_id).first()
            content_hash_display = doc.content_hash[:8] if doc else "unknown"

            # Display group header
            click.secho(
                f"[Group {group_idx}/{total_groups}] {len(copies)} copies, "
                f"hash: {content_hash_display}...",
                fg="cyan",
                bold=True,
            )
            click.echo()

            # Display all copies in this group with metadata
            for idx, copy in enumerate(copies, start=1):
                file_path = repo_root / copy.file_path
                if file_path.exists():
                    stat = file_path.stat()
                    size_kb = stat.st_size / 1024
                    mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                    click.echo(f"  [{idx}] {copy.file_path}")
                    click.echo(f"      Size: {size_kb:.1f} KB, Modified: {mtime}")
                else:
                    click.echo(f"  [{idx}] {copy.file_path}")
                    click.secho("      (file not found on disk)", fg="red")

            click.echo()

            if yes:
                # Bulk mode: keep first, delete rest
                copies_to_delete.extend(copies[1:])
                click.echo(f"  Keeping: [1] {copies[0].file_path}")
                click.secho(f"  Deleting: {len(copies) - 1} duplicate(s)", fg="yellow")
                click.echo()
            else:
                # Interactive mode: ask user which to keep
                click.echo("Which copy do you want to keep?")
                click.echo("  Enter number to keep that copy")
                click.echo("  Enter 'a' to keep all (skip this group)")
                click.echo("  Enter 's' to skip this group")
                click.echo()

                while True:
                    choice = click.prompt("Your choice", type=str, default="1")

                    if choice.lower() in ["a", "all"]:
                        click.echo("  Keeping all copies, skipping group.")
                        break
                    elif choice.lower() in ["s", "skip"]:
                        click.echo("  Skipping group.")
                        break
                    else:
                        try:
                            choice_idx = int(choice)
                            if 1 <= choice_idx <= len(copies):
                                # Keep the chosen copy, delete the rest
                                kept_copy = copies[choice_idx - 1]
                                for idx, copy in enumerate(copies):
                                    if idx != (choice_idx - 1):
                                        copies_to_delete.append(copy)

                                click.echo(f"  Keeping: [{choice_idx}] {kept_copy.file_path}")
                                click.secho(
                                    f"  Marking {len(copies) - 1} duplicate(s) for deletion",
                                    fg="yellow",
                                )
                                break
                            else:
                                click.secho(
                                    f"  Invalid choice. Please enter 1-{len(copies)}, 'a', or 's'",
                                    fg="red",
                                )
                        except ValueError:
                            click.secho(
                                f"  Invalid input. Please enter 1-{len(copies)}, 'a', or 's'",
                                fg="red",
                            )

                click.echo()

        # Show summary
        if not copies_to_delete:
            click.echo("No duplicates selected for deletion.")
            return

        click.echo("=" * 50)
        click.secho(f"Summary: {len(copies_to_delete)} file(s) to delete", bold=True)
        click.echo()

        # Show files to be deleted
        for copy in copies_to_delete:
            click.echo(f"  - {copy.file_path}")

        click.echo()

        if dry_run:
            click.secho("DRY RUN: No files were deleted.", fg="yellow")
            return

        # Final confirmation if not in bulk mode
        if not yes:
            if not click.confirm(f"Delete {len(copies_to_delete)} file(s)?"):
                click.echo("Aborted.")
                return

        # Delete files and database records
        deleted_count = 0
        failed_count = 0

        for copy in copies_to_delete:
            file_path = repo_root / copy.file_path

            try:
                # Delete file from disk if it exists
                if file_path.exists():
                    file_path.unlink()

                # Delete from database (will cascade to Operation)
                session.delete(copy)
                deleted_count += 1
            except Exception as e:
                click.secho(f"  Error deleting {copy.file_path}: {e}", fg="red")
                failed_count += 1

        # Commit changes
        session.commit()

        # Show results
        click.echo()
        if deleted_count > 0:
            click.secho(f"Successfully deleted {deleted_count} duplicate file(s).", fg="green")
        if failed_count > 0:
            click.secho(f"Failed to delete {failed_count} file(s).", fg="red")

    finally:
        # Close the session
        try:
            next(session_gen)
        except StopIteration:
            pass
