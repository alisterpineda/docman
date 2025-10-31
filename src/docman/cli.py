"""
docman - A CLI tool for organizing documents.

This tool uses docling and LLM models (cloud or local) to help organize,
move, and rename documents intelligently.
"""

from pathlib import Path

import click

from docman.config import ensure_app_config
from docman.database import ensure_database, get_session
from docman.models import Document, DocumentCopy, PendingOperation, compute_content_hash
from docman.processor import extract_content
from docman.repository import (
    SUPPORTED_EXTENSIONS,
    RepositoryError,
    discover_document_files,
    discover_document_files_shallow,
    get_repository_root,
)


@click.group()
@click.version_option(version="0.1.0", prog_name="docman")
def main() -> None:
    """docman - Organize documents using AI-powered tools."""
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


@main.command()
@click.argument("directory", default=".")
def init(directory: str) -> None:
    """Initialize a new docman repository in the specified directory."""
    target_path = Path(directory).resolve()

    # Check if target directory exists
    if not target_path.exists():
        click.secho(f"Error: Directory '{directory}' does not exist", fg="red", err=True)
        raise click.Abort()

    if not target_path.is_dir():
        click.secho(f"Error: '{directory}' is not a directory", fg="red", err=True)
        raise click.Abort()

    docman_dir = target_path / ".docman"

    # Check if .docman already exists
    if docman_dir.exists():
        click.echo(f"docman repository already exists in {docman_dir}/")
        return

    # Create .docman directory and config.yaml
    try:
        docman_dir.mkdir(parents=True, exist_ok=True)

        # Create empty config.yaml
        config_file = docman_dir / "config.yaml"
        config_file.touch()

        click.echo(f"Initialized empty docman repository in {docman_dir}/")
    except PermissionError:
        click.secho(
            f"Error: Permission denied to create {docman_dir}", fg="red", err=True
        )
        raise click.Abort()
    except Exception as e:
        click.secho(
            f"Error: Failed to initialize repository: {e}", fg="red", err=True
        )
        raise click.Abort()


@main.command()
@click.argument("path", default=None, required=False)
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    default=False,
    help="Recursively process subdirectories",
)
def plan(path: str | None, recursive: bool) -> None:
    """
    Process documents in the repository.

    Discovers document files and extracts their content using docling,
    storing them in the database.

    Arguments:
        PATH: Optional path to a file or directory (default: current directory).
              Relative to current working directory.

    Options:
        -r, --recursive: Recursively process subdirectories when PATH is a directory.

    Examples:
        - 'docman plan': Process entire repository recursively (backward compatible)
        - 'docman plan .': Process current directory only (non-recursive)
        - 'docman plan docs/': Process docs directory only (non-recursive)
        - 'docman plan docs/ -r': Process docs directory recursively
        - 'docman plan file.pdf': Process single file
        - 'docman plan -r': Process entire repository recursively (same as no args)
    """
    # Find the repository root
    # Strategy: Try from the provided path first (if any), then fall back to cwd
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
    click.echo(f"Processing documents in repository: {repository_path}")

    # For backward compatibility: if no path provided, process entire repository recursively
    # This maintains the original behavior of 'docman plan' with no arguments
    if path is None and not recursive:
        # Default behavior - process entire repository recursively
        document_files = discover_document_files(repo_root)
        click.echo("Discovering documents recursively in entire repository...")
    else:
        # If path is None but recursive flag is set, treat as current directory
        if path is None:
            path = "."
        # Explicit path provided - handle accordingly
        # Convert path to absolute Path object
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

        # Determine what files to process
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
            click.echo(f"Processing single file: {rel_path}")
        else:
            # Directory mode
            if recursive:
                # Recursive discovery from the target directory
                if target_path == repo_root:
                    document_files = discover_document_files(repo_root)
                    click.echo("Discovering documents recursively in entire repository...")
                else:
                    # Recursive discovery in subdirectory
                    all_files = discover_document_files(repo_root)
                    rel_target = target_path.relative_to(repo_root)
                    document_files = [
                        f for f in all_files if f.parts[:len(rel_target.parts)] == rel_target.parts
                    ]
                    click.echo(f"Discovering documents recursively in: {rel_target}")
            else:
                # Shallow discovery - only immediate files
                document_files = discover_document_files_shallow(repo_root, target_path)
                rel_target = target_path.relative_to(repo_root)
                click.echo(f"Discovering documents in: {rel_target} (non-recursive)")

    if not document_files:
        click.echo("No document files found in repository.")
        return

    click.echo(f"Found {len(document_files)} document file(s)\n")

    # Get database session
    session_gen = get_session()
    session = next(session_gen)

    try:
        # Query existing copies in this repository
        existing_copies = (
            session.query(DocumentCopy)
            .filter(DocumentCopy.repository_path == repository_path)
            .all()
        )
        existing_copy_paths = {copy.file_path for copy in existing_copies}

        # Counters for summary
        processed_count = 0
        skipped_count = 0
        failed_count = 0
        duplicate_count = 0  # Same document, different location

        # Process each file
        for idx, file_path in enumerate(document_files, start=1):
            file_path_str = str(file_path)
            percentage = int((idx / len(document_files)) * 100)

            # Skip if copy already exists in this repository at this path
            if file_path_str in existing_copy_paths:
                click.echo(f"[{idx}/{len(document_files)}] {percentage}% Skipping: {file_path}")
                skipped_count += 1
                continue

            # Show progress
            click.echo(f"[{idx}/{len(document_files)}] {percentage}% Processing: {file_path}")

            # Compute content hash
            full_path = repo_root / file_path
            try:
                content_hash = compute_content_hash(full_path)
            except Exception as e:
                click.echo(f"  Error computing hash: {e}")
                failed_count += 1
                continue

            # Find or create canonical document
            document = session.query(Document).filter(Document.content_hash == content_hash).first()

            if document:
                # Document already exists (found in another repo or location)
                click.echo(f"  Found existing document (hash: {content_hash[:8]}...)")
                duplicate_count += 1
            else:
                # New document - extract content
                content = extract_content(full_path)

                if content is None:
                    click.echo("  Warning: Content extraction failed")
                    failed_count += 1
                    # Still create the document with None content
                else:
                    click.echo(f"  Extracted {len(content)} characters")
                    processed_count += 1

                # Create new canonical document
                document = Document(content_hash=content_hash, content=content)
                session.add(document)
                session.flush()  # Get the document.id for the copy

            # Create document copy for this repository
            copy = DocumentCopy(
                document_id=document.id,
                repository_path=repository_path,
                file_path=file_path_str,
            )
            session.add(copy)
            session.flush()  # Get the copy.id for the pending operation

            # Create pending operation if it doesn't exist (stub implementation)
            existing_pending_op = (
                session.query(PendingOperation)
                .filter(PendingOperation.document_copy_id == copy.id)
                .first()
            )

            if not existing_pending_op:
                # Extract current directory and filename from file_path
                file_path_obj = Path(file_path_str)
                current_directory = str(file_path_obj.parent) if file_path_obj.parent != Path('.') else ""
                current_filename = file_path_obj.name

                # Create pending operation with stub suggestion (keep file as-is)
                pending_op = PendingOperation(
                    document_copy_id=copy.id,
                    suggested_directory_path=current_directory,
                    suggested_filename=current_filename,
                    reason="Awaiting LLM analysis",
                    confidence=0.5,  # Neutral confidence for stub
                )
                session.add(pending_op)

        # Commit all changes
        session.commit()

        # Display summary
        click.echo("\n" + "=" * 50)
        click.echo("Summary:")
        click.echo(f"  New documents processed: {processed_count}")
        click.echo(f"  Duplicate documents (already known): {duplicate_count}")
        click.echo(f"  Skipped (copy exists in this repo): {skipped_count}")
        click.echo(f"  Failed (hash or extraction errors): {failed_count}")
        click.echo(f"  Total files: {len(document_files)}")
        click.echo("=" * 50)

    finally:
        # Close the session
        try:
            next(session_gen)
        except StopIteration:
            pass


if __name__ == "__main__":
    main()
