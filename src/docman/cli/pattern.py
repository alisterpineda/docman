"""Pattern command group for managing variable pattern definitions.

This module contains the `pattern` command group and all its subcommands
for managing variable patterns and their predefined values.
"""

import click
from pathlib import Path

from docman.repository import RepositoryError, get_repository_root


@click.group()
def pattern() -> None:
    """Manage variable pattern definitions."""
    pass


@pattern.group(name="value")
def pattern_value_group() -> None:
    """Manage predefined values for variable patterns."""
    pass


@pattern_value_group.command(name="add")
@click.argument("pattern_name")
@click.argument("value")
@click.option("--desc", default=None, help="Description of this value")
@click.option("--alias-of", default=None, help="Add as alias of this canonical value")
@click.option("--path", type=str, default=".", help="Repository path (default: current directory)")
def pattern_value_add(
    pattern_name: str, value: str, desc: str | None, alias_of: str | None, path: str
) -> None:
    """Add a value to a variable pattern.

    Values help the LLM recognize and categorize documents with known names.
    Use --alias-of to add alternative names that map to a canonical value.

    Examples:
        docman pattern value add company "Acme Corp." --desc "Current name after 2020"
        docman pattern value add company "XYZ Corp" --alias-of "Acme Corp."
    """
    try:
        repo_root = get_repository_root(start_path=Path(path).resolve())
    except RepositoryError:
        raise click.Abort()

    try:
        from docman.repo_config import add_pattern_value

        add_pattern_value(repo_root, pattern_name, value, desc, alias_of)

        if alias_of:
            click.secho(f"Added alias '{value}' for '{alias_of}'", fg="green")
        else:
            click.secho(f"Added value '{value}' to pattern '{pattern_name}'", fg="green")
            if desc:
                click.echo(f"  Description: {desc}")

    except ValueError as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        raise click.Abort()
    except Exception as e:
        click.secho(f"Error: Failed to add value: {e}", fg="red", err=True)
        raise click.Abort()


@pattern_value_group.command(name="list")
@click.argument("pattern_name")
@click.option("--path", type=str, default=".", help="Repository path (default: current directory)")
def pattern_value_list(pattern_name: str, path: str) -> None:
    """List all values for a variable pattern."""
    try:
        repo_root = get_repository_root(start_path=Path(path).resolve())
    except RepositoryError:
        raise click.Abort()

    try:
        from docman.repo_config import get_pattern_values, get_variable_patterns

        # Check if pattern exists
        patterns = get_variable_patterns(repo_root)
        if pattern_name not in patterns:
            click.secho(f"Error: Variable pattern '{pattern_name}' not found", fg="red", err=True)
            click.echo()
            click.echo("Run 'docman pattern list' to see all defined patterns.")
            raise click.Abort()

        values = get_pattern_values(repo_root, pattern_name)

        if not values:
            click.echo(f"No values defined for pattern '{pattern_name}'.")
            click.echo()
            click.echo(f"Run 'docman pattern value add {pattern_name} <value>' to add values.")
            return

        click.echo()
        click.secho(f"Values for '{pattern_name}':", bold=True)
        click.echo()

        for pv in values:
            # Display value with optional description
            if pv.description:
                click.echo(f"  - {pv.value} - {pv.description}")
            else:
                click.echo(f"  - {pv.value}")

            # Display aliases if any
            if pv.aliases:
                aliases_str = ", ".join(pv.aliases)
                click.echo(f"    Aliases: {aliases_str}")

        click.echo()

    except ValueError as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        raise click.Abort()
    except Exception as e:
        click.secho(f"Error: Failed to list values: {e}", fg="red", err=True)
        raise click.Abort()


@pattern_value_group.command(name="remove")
@click.argument("pattern_name")
@click.argument("value")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation prompt")
@click.option("--path", type=str, default=".", help="Repository path (default: current directory)")
def pattern_value_remove(pattern_name: str, value: str, yes: bool, path: str) -> None:
    """Remove a value or alias from a variable pattern.

    If the value is canonical, removes it and all its aliases.
    If it's an alias, removes only the alias.
    """
    try:
        repo_root = get_repository_root(start_path=Path(path).resolve())
    except RepositoryError:
        raise click.Abort()

    try:
        from docman.repo_config import get_pattern_values, remove_pattern_value

        # Check what we're removing
        values = get_pattern_values(repo_root, pattern_name)
        is_alias = False
        canonical_value = None

        for pv in values:
            if pv.value == value:
                break
            if value in pv.aliases:
                is_alias = True
                canonical_value = pv.value
                break

        # Confirm deletion
        if not yes:
            if is_alias:
                click.echo(f"Removing alias '{value}' from canonical value '{canonical_value}'")
            else:
                click.echo(f"Removing value '{value}' (and all its aliases)")
            click.echo()
            if not click.confirm("Proceed?", default=False):
                click.echo("Cancelled.")
                return

        remove_pattern_value(repo_root, pattern_name, value)

        if is_alias:
            click.secho(f"Removed alias '{value}'", fg="green")
        else:
            click.secho(f"Removed value '{value}'", fg="green")

    except ValueError as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        raise click.Abort()
    except Exception as e:
        click.secho(f"Error: Failed to remove value: {e}", fg="red", err=True)
        raise click.Abort()


@pattern.command(name="add")
@click.argument("name")
@click.option("--desc", required=True, help="Description of the variable pattern")
@click.option("--path", type=str, default=".", help="Repository path (default: current directory)")
def pattern_add(name: str, desc: str, path: str) -> None:
    """Add or update a variable pattern definition.

    Variable patterns define how to extract values like {year}, {category},
    or {company} from documents. These patterns are used in folder paths and
    filename conventions.

    Example:
        docman pattern add year --desc "4-digit year in YYYY format"
    """
    try:
        repo_root = get_repository_root(start_path=Path(path).resolve())
    except RepositoryError:
        raise click.Abort()

    try:
        from docman.repo_config import set_variable_pattern

        set_variable_pattern(repo_root, name, desc)

        click.secho(f"Variable pattern '{name}' saved", fg="green")
        click.echo()
        click.echo(f"  Description: {desc}")
        click.echo()
        click.echo("You can now use this pattern in folder paths and filename conventions:")
        click.echo("  docman define path/{name}/... --desc '...'")

    except ValueError as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        raise click.Abort()
    except Exception as e:
        click.secho(f"Error: Failed to save variable pattern: {e}", fg="red", err=True)
        raise click.Abort()


@pattern.command(name="list")
@click.option("--path", type=str, default=".", help="Repository path (default: current directory)")
def pattern_list(path: str) -> None:
    """List all defined variable patterns."""
    try:
        repo_root = get_repository_root(start_path=Path(path).resolve())
    except RepositoryError:
        raise click.Abort()

    try:
        from docman.repo_config import get_variable_patterns

        patterns = get_variable_patterns(repo_root)

        if not patterns:
            click.echo("No variable patterns defined for this repository.")
            click.echo()
            click.echo("Run 'docman pattern add <name> --desc \"description\"' to define patterns.")
            return

        click.echo()
        click.secho("Variable Patterns:", bold=True)
        click.echo()

        for name, pattern in sorted(patterns.items()):
            click.secho(f"  {name}:", fg="cyan", bold=True)
            click.echo(f"    {pattern.description}")
            # Show value count if any values defined
            if pattern.values:
                click.echo(f"    ({len(pattern.values)} predefined values)")
            click.echo()

    except ValueError as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        raise click.Abort()
    except Exception as e:
        click.secho(f"Error: Failed to load variable patterns: {e}", fg="red", err=True)
        raise click.Abort()


@pattern.command(name="show")
@click.argument("name")
@click.option("--path", type=str, default=".", help="Repository path (default: current directory)")
def pattern_show(name: str, path: str) -> None:
    """Show details of a specific variable pattern."""
    try:
        repo_root = get_repository_root(start_path=Path(path).resolve())
    except RepositoryError:
        raise click.Abort()

    try:
        from docman.repo_config import get_variable_patterns

        patterns = get_variable_patterns(repo_root)

        if name not in patterns:
            click.secho(f"Error: Variable pattern '{name}' not found", fg="red", err=True)
            click.echo()
            click.echo("Run 'docman pattern list' to see all defined patterns.")
            raise click.Abort()

        pattern = patterns[name]

        click.echo()
        click.secho(f"Pattern: {name}", bold=True)
        click.echo()
        click.echo(f"  Description: {pattern.description}")

        # Display values if any
        if pattern.values:
            click.echo()
            click.secho("  Values:", bold=True)
            for pv in pattern.values:
                if pv.description:
                    click.echo(f"    - {pv.value} - {pv.description}")
                else:
                    click.echo(f"    - {pv.value}")
                if pv.aliases:
                    aliases_str = ", ".join(pv.aliases)
                    click.echo(f"      Aliases: {aliases_str}")

        click.echo()

    except ValueError as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        raise click.Abort()
    except Exception as e:
        click.secho(f"Error: Failed to load variable pattern: {e}", fg="red", err=True)
        raise click.Abort()


@pattern.command(name="remove")
@click.argument("name")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation prompt")
@click.option("--path", type=str, default=".", help="Repository path (default: current directory)")
def pattern_remove(name: str, yes: bool, path: str) -> None:
    """Remove a variable pattern definition."""
    try:
        repo_root = get_repository_root(start_path=Path(path).resolve())
    except RepositoryError:
        raise click.Abort()

    try:
        from docman.repo_config import get_variable_patterns, remove_variable_pattern

        # Check if pattern exists
        patterns = get_variable_patterns(repo_root)
        if name not in patterns:
            click.secho(f"Error: Variable pattern '{name}' not found", fg="red", err=True)
            click.echo()
            click.echo("Run 'docman pattern list' to see all defined patterns.")
            raise click.Abort()

        # Confirm deletion
        if not yes:
            click.echo()
            click.secho(f"Pattern: {name}", bold=True)
            click.echo(f"  Description: {patterns[name].description}")
            if patterns[name].values:
                click.echo(f"  ({len(patterns[name].values)} predefined values will be removed)")
            click.echo()
            if not click.confirm(f"Remove variable pattern '{name}'?", default=False):
                click.echo("Cancelled.")
                return

        # Remove pattern
        remove_variable_pattern(repo_root, name)

        click.secho(f"Variable pattern '{name}' removed", fg="green")

    except ValueError as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        raise click.Abort()
    except Exception as e:
        click.secho(f"Error: Failed to remove variable pattern: {e}", fg="red", err=True)
        raise click.Abort()
