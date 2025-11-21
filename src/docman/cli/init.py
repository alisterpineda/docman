"""Init command for docman CLI.

This module contains the init command for initializing a new docman repository.
"""

from pathlib import Path

import click

from docman.cli.utils import require_database


@click.command()
@click.argument("directory", default=".")
@require_database
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
        click.echo()
        click.echo("Next steps:")
        click.echo("  1. Define variable patterns: docman pattern add <name> --desc \"description\"")
        click.echo("  2. Define folder structure: docman define <path> --desc \"description\"")
        click.echo("  3. Scan documents: docman scan -r")
        click.echo("  4. Generate suggestions: docman plan")
        click.echo()

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
