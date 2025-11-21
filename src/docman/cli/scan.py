"""
Scan command for docman CLI.

This module contains the scan command which discovers document files
and extracts their content using docling, storing them in the database.
This is a prerequisite step before running 'docman plan' to generate
LLM organization suggestions.
"""

from __future__ import annotations

import signal
from pathlib import Path

import click

from docman.database import get_session
from docman.models import Document, DocumentCopy, file_needs_rehashing, get_utc_now
from docman.repository import (
    SUPPORTED_EXTENSIONS,
    RepositoryError,
    discover_document_files,
    discover_document_files_shallow,
    get_repository_root,
)

from docman.cli.utils import cleanup_orphaned_copies, require_database


@click.command()
@click.argument("path", default=None, required=False)
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    default=False,
    help="Recursively scan subdirectories",
)
@click.option(
    "--rescan",
    is_flag=True,
    default=False,
    help="Force re-scan of already-scanned files",
)
@require_database
def scan(path: str | None, recursive: bool, rescan: bool) -> None:
    """
    Scan and extract content from documents in the repository.

    Discovers document files and extracts their content using docling,
    storing them in the database. This is a prerequisite step before
    running 'docman plan' to generate LLM organization suggestions.

    Arguments:
        PATH: Optional path to a file or directory (default: current directory).
              Relative to current working directory.

    Options:
        -r, --recursive: Recursively scan subdirectories when PATH is a directory.
        --rescan: Force re-scan of already-scanned files.

    Examples:
        - 'docman scan': Scan current directory only (non-recursive)
        - 'docman scan -r': Scan entire repository recursively
        - 'docman scan docs/': Scan docs directory only (non-recursive)
        - 'docman scan docs/ -r': Scan docs directory recursively
        - 'docman scan file.pdf': Scan single file
        - 'docman scan --rescan': Re-scan all files, including those already scanned
    """
    from docman.processor import ProcessingResult, process_document_file

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
                # Neither path nor cwd is in a repository
                raise click.Abort()
    else:
        # No path provided, use current directory
        try:
            repo_root = get_repository_root(start_path=Path.cwd())
        except RepositoryError:
            raise click.Abort()

    repository_path = str(repo_root)
    click.echo(f"Scanning documents in repository: {repository_path}")

    # Determine what files to scan
    if path is None:
        if recursive:
            # Recursive discovery from repository root
            document_files = discover_document_files(repo_root)
            click.echo("Discovering documents recursively in entire repository...")
        else:
            # Default: current directory only (non-recursive)
            cwd = Path.cwd()
            document_files = discover_document_files_shallow(repo_root, cwd)
            rel_target = cwd.relative_to(repo_root) if cwd != repo_root else Path(".")
            click.echo(f"Discovering documents in: {rel_target} (non-recursive)")
    else:
        # Explicit path provided
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

        # Determine what files to scan
        if target_path.is_file():
            # Single file mode
            if target_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                click.secho(
                    f"Error: Unsupported file type '{target_path.suffix}'. "
                    f"Supported extensions: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
                    fg="red",
                    err=True,
                )
                raise click.Abort()

            # Create list with single relative path
            rel_path = target_path.relative_to(repo_root)
            document_files = [rel_path]
            click.echo(f"Scanning single file: {rel_path}")
        else:
            # Directory mode
            if recursive:
                # Recursive discovery from the target directory
                if target_path == repo_root:
                    document_files = discover_document_files(repo_root)
                    click.echo("Discovering documents recursively in entire repository...")
                else:
                    document_files = discover_document_files(repo_root, root_path=target_path)
                    rel_target = target_path.relative_to(repo_root)
                    click.echo(f"Discovering documents recursively in: {rel_target}")
            else:
                # Shallow discovery - only immediate files
                document_files = discover_document_files_shallow(repo_root, target_path)
                rel_target = target_path.relative_to(repo_root)
                click.echo(f"Discovering documents in: {rel_target} (non-recursive)")

    if not document_files:
        click.echo("No document files found.")
        return

    click.echo(f"Found {len(document_files)} document file(s)\n")

    # Get database session
    session_gen = get_session()
    session = next(session_gen)

    # Set up graceful cancellation handler
    cancellation_flag = {"cancelled": False}

    def handle_sigint(signum: int, frame: object) -> None:
        """Handle Ctrl+C gracefully by setting cancellation flag."""
        if not cancellation_flag["cancelled"]:
            cancellation_flag["cancelled"] = True
            click.echo("\n")
            click.secho(
                "Cancellation requested, finishing current file...",
                fg="yellow",
                bold=True,
            )
            click.echo()

    # Register the signal handler
    original_handler = signal.signal(signal.SIGINT, handle_sigint)

    try:
        # Clean up orphaned copies (files that no longer exist)
        deleted_count, _ = cleanup_orphaned_copies(session, repo_root)
        if deleted_count > 0:
            click.echo(f"Cleaned up {deleted_count} orphaned file(s)\n")

        # Counters for summary
        new_count = 0
        updated_count = 0
        skipped_count = 0
        failed_count = 0
        batch_size = 10
        files_since_commit = 0

        # Lazy import DocumentConverter only when needed
        from docling.document_converter import DocumentConverter

        # Create a single DocumentConverter instance to reuse for all files
        converter = DocumentConverter()

        # Process each file
        for idx, file_path in enumerate(document_files, start=1):
            # Calculate batch number for display
            batch_num = ((idx - 1) // batch_size) + 1
            percentage = int((idx / len(document_files)) * 100)
            click.echo(
                f"[{idx}/{len(document_files)}] {percentage}% (Batch {batch_num}) Scanning: {file_path}"
            )

            # Process the document file
            copy, result = process_document_file(
                session=session,
                repo_root=repo_root,
                file_path=file_path,
                repository_path=repository_path,
                converter=converter,
                rescan=rescan,
            )

            # Update counters based on result
            if result == ProcessingResult.NEW_DOCUMENT:
                click.echo(f"  New document (extracted {len(copy.document.content or '')} characters)")
                new_count += 1
            elif result == ProcessingResult.CONTENT_UPDATED:
                click.echo(f"  Content updated (extracted {len(copy.document.content or '')} characters)")
                updated_count += 1
            elif result == ProcessingResult.DUPLICATE_DOCUMENT:
                click.echo("  Found existing document (duplicate)")
                new_count += 1
            elif result == ProcessingResult.REUSED_COPY:
                click.echo("  Already scanned (skipped)")
                skipped_count += 1
            elif result == ProcessingResult.EXTRACTION_FAILED:
                click.echo("  Warning: Content extraction failed")
                failed_count += 1
            elif result == ProcessingResult.HASH_FAILED:
                click.echo("  Error: Failed to compute content hash")
                failed_count += 1

            files_since_commit += 1

            # Commit every batch_size files
            if files_since_commit >= batch_size:
                try:
                    session.commit()
                    click.secho(
                        f"✓ Batch {batch_num} committed ({idx} files processed)",
                        fg="green",
                    )
                    files_since_commit = 0
                except Exception as e:
                    click.secho(
                        f"Error: Failed to commit batch {batch_num}: {e}",
                        fg="red",
                        err=True,
                    )
                    raise

            # Check for cancellation after processing each file
            if cancellation_flag["cancelled"]:
                click.echo()
                click.secho("Saving progress...", fg="yellow", bold=True)
                # Commit any remaining files in the current incomplete batch
                if files_since_commit > 0:
                    try:
                        session.commit()
                        click.secho(
                            f"✓ Final batch committed ({idx} files processed)",
                            fg="green",
                        )
                    except Exception as e:
                        click.secho(
                            f"Error: Failed to commit final batch: {e}",
                            fg="red",
                            err=True,
                        )
                        raise
                break

        # Commit any remaining files that haven't been committed yet
        # (only if we didn't break due to cancellation, or if there were uncommitted files)
        if not cancellation_flag["cancelled"] and files_since_commit > 0:
            try:
                session.commit()
                click.secho(
                    f"✓ Final batch committed ({idx} files processed)",
                    fg="green",
                )
            except Exception as e:
                click.secho(
                    f"Error: Failed to commit final batch: {e}",
                    fg="red",
                    err=True,
                )
                raise

        # Display summary
        click.echo("\n" + "=" * 50)
        click.echo("Summary:")
        click.echo(f"  New documents: {new_count}")
        click.echo(f"  Updated documents: {updated_count}")
        click.echo(f"  Skipped (already scanned): {skipped_count}")
        click.echo(f"  Failed (extraction errors): {failed_count}")
        click.echo(f"  Total files: {len(document_files)}")
        click.echo("=" * 50)
        click.echo()

    finally:
        # Restore the original signal handler
        signal.signal(signal.SIGINT, original_handler)

        # Close the session
        try:
            next(session_gen)
        except StopIteration:
            pass
