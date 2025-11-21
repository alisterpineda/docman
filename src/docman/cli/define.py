"""Define command for docman CLI.

This module contains the define command for creating folder definitions
in the organization structure.
"""

from pathlib import Path

import click

from docman.repo_config import add_folder_definition
from docman.repository import RepositoryError, get_repository_root


@click.command()
@click.argument("path", type=str)
@click.option(
    "--desc",
    type=str,
    default=None,
    help="Description of the folder (optional - omit for self-documenting structure)",
)
@click.option(
    "--filename-convention",
    type=str,
    default=None,
    help="Optional filename template pattern (e.g., '{year}-{month}-invoice')",
)
def define(path: str, desc: str | None, filename_convention: str | None) -> None:
    """Define a folder with optional description in the organization structure.

    Creates or updates a folder definition in the repository configuration.
    Paths use '/' as separator and can include variable patterns like {year}.

    Arguments:
        PATH: Folder path (e.g., "Financial/invoices/{year}")

    Options:
        --desc: Human-readable description of what belongs in this folder (optional).
                Omit for self-documenting structures using variable patterns.
        --filename-convention: Optional filename template with variables like {year}, {month}, etc.
                              File extensions are preserved automatically.

    Examples:
        - 'docman define Financial --desc "Financial documents"'
        - 'docman define Financial/invoices/{year} --desc "Invoices by year (YYYY format)"'
        - 'docman define Financial/invoices/{year}' (no description - structure is self-documenting)
        - 'docman define Financial/invoices/{year} --desc "Invoices" --filename-convention "{company}-invoice-{year}-{month}"'
        - 'docman define Personal/medical/{family_member} --desc "Medical records by family member"'
    """
    # Find repository root
    try:
        repo_root = get_repository_root(start_path=Path.cwd())
    except RepositoryError:
        click.secho("Error: Not in a docman repository. Run 'docman init' first.", fg="red", err=True)
        raise click.Abort()

    # Add folder definition
    try:
        add_folder_definition(repo_root, path, desc, filename_convention)
        success_msg = f"✓ Defined folder: {path}"
        if filename_convention:
            success_msg += f"\n  Filename convention: {filename_convention}"
        click.secho(success_msg, fg="green")
    except ValueError as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        raise click.Abort()
    except OSError as e:
        click.secho(f"Error: Failed to save configuration: {e}", fg="red", err=True)
        raise click.Abort()
