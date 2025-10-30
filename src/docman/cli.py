"""
docman - A CLI tool for organizing documents.

This tool uses docling and LLM models (cloud or local) to help organize,
move, and rename documents intelligently.
"""

from pathlib import Path

import click

from docman.config import ensure_app_config
from docman.database import ensure_database, get_session
from docman.models import Document
from docman.processor import extract_content
from docman.repository import RepositoryError, discover_document_files, get_repository_root


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
def plan() -> None:
    """
    Process all documents in the repository.

    Discovers all document files in the repository and extracts their content
    using docling, storing them in the database.
    """
    try:
        # Find the repository root
        repo_root = get_repository_root()
    except RepositoryError:
        raise click.Abort()

    click.echo(f"Processing documents in repository: {repo_root}")

    # Discover all document files
    document_files = discover_document_files(repo_root)

    if not document_files:
        click.echo("No document files found in repository.")
        return

    click.echo(f"Found {len(document_files)} document file(s)\n")

    # Get database session
    session_gen = get_session()
    session = next(session_gen)

    try:
        # Query existing documents to check what's already in the database
        existing_docs = session.query(Document).all()
        existing_paths = {doc.file_path for doc in existing_docs}

        # Counters for summary
        processed_count = 0
        skipped_count = 0
        failed_count = 0

        # Process each file
        for idx, file_path in enumerate(document_files, start=1):
            file_path_str = str(file_path)
            percentage = int((idx / len(document_files)) * 100)

            # Skip if already exists
            if file_path_str in existing_paths:
                click.echo(f"[{idx}/{len(document_files)}] {percentage}% Skipping: {file_path}")
                skipped_count += 1
                continue

            # Show progress
            click.echo(f"[{idx}/{len(document_files)}] {percentage}% Processing: {file_path}")

            # Extract content
            full_path = repo_root / file_path
            content = extract_content(full_path)

            # Create document record
            doc = Document(file_path=file_path_str, content=content)
            session.add(doc)

            if content is None:
                failed_count += 1
            else:
                processed_count += 1

        # Commit all changes
        session.commit()

        # Display summary
        click.echo("\n" + "=" * 50)
        click.echo("Summary:")
        click.echo(f"  Processed: {processed_count}")
        click.echo(f"  Skipped (already exists): {skipped_count}")
        click.echo(f"  Failed (content extraction): {failed_count}")
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
