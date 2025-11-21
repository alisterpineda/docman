"""Config command group for managing repository configuration.

This module contains commands for managing docman repository configuration,
including setting default filename conventions and listing folder structures.
"""

import click
from pathlib import Path

from docman.repository import RepositoryError, get_repository_root
from docman.repo_config import get_folder_definitions


@click.group()
def config() -> None:
    """Manage repository configuration."""
    pass


@config.command(name="set-default-filename-convention")
@click.argument("convention", type=str)
@click.option("--path", type=str, default=".", help="Repository path (default: current directory)")
def config_set_default_filename_convention(convention: str, path: str) -> None:
    """Set the default filename convention for the repository.

    The convention is a template pattern using variables like {year}, {month},
    {description}, etc. File extensions are preserved automatically.

    Arguments:
        CONVENTION: Filename template pattern (e.g., "{year}-{month}-{description}")

    Examples:
        docman config set-default-filename-convention "{year}-{month}-{description}"
        docman config set-default-filename-convention "{date}-{company}-{type}"
    """
    from docman.repo_config import set_default_filename_convention

    # Find repository root
    try:
        repo_root = get_repository_root(start_path=Path(path).resolve())
    except RepositoryError:
        click.secho("Error: Not in a docman repository. Run 'docman init' first.", fg="red", err=True)
        raise click.Abort()

    # Set default convention
    try:
        set_default_filename_convention(repo_root, convention)
        click.secho(f"✓ Set default filename convention: {convention}", fg="green")
    except ValueError as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        raise click.Abort()
    except OSError as e:
        click.secho(f"Error: Failed to save configuration: {e}", fg="red", err=True)
        raise click.Abort()


def _render_folder_tree(folders: dict, prefix: str = "", is_root: bool = True) -> list[str]:
    """Recursively render folder tree with box-drawing characters.

    Args:
        folders: Dictionary mapping folder names to FolderDefinition objects.
        prefix: Prefix string for indentation.
        is_root: Whether this is the root level (top-level folders).

    Returns:
        List of lines representing the tree structure.
    """
    from docman.repo_config import FolderDefinition

    lines = []
    folder_items = list(folders.items())

    for i, (name, folder_def) in enumerate(folder_items):
        is_last_item = i == len(folder_items) - 1

        # Determine branch character
        if is_root:
            # Top level folders, no prefix or branch
            branch = ""
        else:
            # Child folders get branch characters
            branch = "└─ " if is_last_item else "├─ "

        # Add this folder with filename convention if set
        folder_line = f"{prefix}{branch}{name}"
        if isinstance(folder_def, FolderDefinition) and folder_def.filename_convention:
            folder_line += f" [filename: {folder_def.filename_convention}]"
        lines.append(folder_line)

        # Recursively add children if any
        if isinstance(folder_def, FolderDefinition) and folder_def.folders:
            # Determine new prefix for children
            if is_root:
                # Children of root folders start with minimal indentation
                new_prefix = ""
            else:
                # Deeper nesting, extend the prefix
                extension = "   " if is_last_item else "│  "
                new_prefix = prefix + extension

            # Render children (not root anymore)
            child_lines = _render_folder_tree(folder_def.folders, new_prefix, is_root=False)
            lines.extend(child_lines)

    return lines


@config.command(name="list-dirs")
@click.option("--path", type=str, default=".", help="Repository path (default: current directory)")
def config_list_dirs(path: str) -> None:
    """List all defined folder structures in the repository.

    Displays the folder hierarchy defined in the repository configuration
    as a tree structure, including filename conventions if set.

    Examples:
        docman config list-dirs
        docman config list-dirs --path /path/to/repo
    """
    from docman.repo_config import get_default_filename_convention

    # Find repository root
    try:
        repo_root = get_repository_root(start_path=Path(path).resolve())
    except RepositoryError:
        raise click.Abort()

    # Load default filename convention and folder definitions
    try:
        default_convention = get_default_filename_convention(repo_root)
        folders = get_folder_definitions(repo_root)
    except ValueError as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        raise click.Abort()

    if not folders:
        click.echo("No folder definitions found for this repository.")
        click.echo()
        click.echo("Run 'docman define <path> --desc \"description\"' to define folders.")
        return

    # Display default filename convention if set
    click.echo()
    if default_convention:
        click.secho("Default Filename Convention:", bold=True)
        click.echo(f"  {default_convention}")
        click.echo()

    # Render tree
    click.secho("Folder Structure:", bold=True)
    tree_lines = _render_folder_tree(folders)
    for line in tree_lines:
        click.echo(line)
    click.echo()
