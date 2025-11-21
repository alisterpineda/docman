"""LLM command group for managing LLM provider configurations."""

import click

from docman.llm_config import (
    ProviderConfig,
    add_provider,
    get_active_provider,
    get_api_key,
    get_provider,
    get_providers,
    remove_provider,
    set_active_provider,
)
from docman.llm_providers import get_provider as get_llm_provider
from docman.llm_wizard import run_llm_wizard


@click.group()
def llm() -> None:
    """Manage LLM provider configurations."""
    pass


@llm.command(name="add")
@click.option("--name", type=str, help="Name for this provider configuration")
@click.option(
    "--provider",
    type=click.Choice(["google", "openai"], case_sensitive=False),
    help="Provider type (google, openai)",
)
@click.option("--model", type=str, help="Model identifier (e.g., gemini-1.5-flash, gpt-4)")
@click.option("--api-key", type=str, help="API key (will be prompted if not provided)")
@click.option("--endpoint", type=str, help="Custom API endpoint URL (for OpenAI-compatible servers)")
def llm_add(name: str | None, provider: str | None, model: str | None, api_key: str | None, endpoint: str | None) -> None:
    """Add a new LLM provider configuration.

    If options are not provided, an interactive wizard will guide you through setup.
    """
    # If any option is missing, use the wizard
    if not all([name, provider, model, api_key]):
        if not run_llm_wizard():
            click.secho("Setup failed or cancelled.", fg="yellow")
            raise click.Abort()
        return

    # All options provided - add provider directly
    # At this point we know all values are not None due to the check above
    assert name is not None
    assert provider is not None
    assert model is not None
    assert api_key is not None

    try:
        provider_config = ProviderConfig(
            name=name,
            provider_type=provider,
            model=model,
            endpoint=endpoint,
            is_active=False,  # Will be set to True if it's the first provider
        )

        # Test connection
        click.echo("Testing connection...")
        llm_provider = get_llm_provider(provider_config, api_key)
        try:
            llm_provider.test_connection()
            click.secho("Connection successful!", fg="green")
        except Exception as e:
            click.secho("Connection test failed:", fg="red")
            click.secho(f"  {str(e)}", fg="red")
            raise click.Abort()

        # Add provider
        add_provider(provider_config, api_key)
        click.secho(f"Provider '{name}' added successfully!", fg="green")

        # Check if it was set as active
        if provider_config.is_active:
            click.secho(f"Provider '{name}' is now active.", fg="green")

    except ValueError as e:
        click.secho(f"Error: {e}", fg="red")
        raise click.Abort()
    except Exception as e:
        click.secho(f"Error: Failed to add provider: {e}", fg="red")
        raise click.Abort()


@llm.command(name="list")
def llm_list() -> None:
    """List all configured LLM providers."""
    providers = get_providers()

    if not providers:
        click.echo("No LLM providers configured.")
        click.echo()
        click.echo("Run 'docman llm add' to add a provider.")
        return

    click.echo()
    click.secho("Configured LLM Providers:", bold=True)
    click.echo()

    for provider in providers:
        active_marker = "● " if provider.is_active else "○ "
        color = "green" if provider.is_active else "white"

        click.secho(f"{active_marker}{provider.name}", fg=color, bold=provider.is_active)
        click.echo(f"  Type: {provider.provider_type}")
        click.echo(f"  Model: {provider.model}")
        if provider.endpoint:
            click.echo(f"  Endpoint: {provider.endpoint}")
        click.echo()


@llm.command(name="remove")
@click.argument("name")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation prompt")
def llm_remove(name: str, yes: bool) -> None:
    """Remove an LLM provider configuration.

    Arguments:
        NAME: The name of the provider to remove.
    """
    # Check if provider exists
    provider = get_provider(name)
    if not provider:
        click.secho(f"Error: Provider '{name}' not found.", fg="red")
        raise click.Abort()

    # Confirm deletion
    if not yes:
        click.echo("Provider to remove:")
        click.echo(f"  Name: {provider.name}")
        click.echo(f"  Type: {provider.provider_type}")
        click.echo(f"  Model: {provider.model}")
        click.echo()

        if not click.confirm(f"Are you sure you want to remove '{name}'?"):
            click.echo("Aborted.")
            return

    # Remove provider
    if remove_provider(name):
        click.secho(f"Provider '{name}' removed successfully.", fg="green")

        # Check if there's a new active provider
        active = get_active_provider()
        if active:
            click.echo(f"Active provider is now: {active.name}")
    else:
        click.secho(f"Error: Failed to remove provider '{name}'.", fg="red")
        raise click.Abort()


@llm.command(name="set-active")
@click.argument("name")
def llm_set_active(name: str) -> None:
    """Set a provider as the active one.

    Arguments:
        NAME: The name of the provider to activate.
    """
    if set_active_provider(name):
        click.secho(f"Provider '{name}' is now active.", fg="green")
    else:
        click.secho(f"Error: Provider '{name}' not found.", fg="red")
        raise click.Abort()


@llm.command(name="show")
@click.argument("name", required=False)
def llm_show(name: str | None) -> None:
    """Show details of an LLM provider.

    Arguments:
        NAME: The name of the provider to show (defaults to active provider).
    """
    if name:
        provider = get_provider(name)
        if not provider:
            click.secho(f"Error: Provider '{name}' not found.", fg="red")
            raise click.Abort()
    else:
        provider = get_active_provider()
        if not provider:
            click.echo("No active provider configured.")
            click.echo()
            click.echo("Run 'docman llm add' to add a provider.")
            return

    click.echo()
    click.secho(f"Provider: {provider.name}", bold=True)
    if provider.is_active:
        click.secho("  (Active)", fg="green")
    click.echo()
    click.echo(f"Type: {provider.provider_type}")
    click.echo(f"Model: {provider.model}")
    if provider.endpoint:
        click.echo(f"Endpoint: {provider.endpoint}")
    click.echo()

    # Show API key status (but not the actual key)
    api_key = get_api_key(provider.name)
    if api_key:
        click.secho("API Key: Configured ✓", fg="green")
    else:
        click.secho("API Key: Not found ✗", fg="red")
    click.echo()


@llm.command(name="test")
@click.argument("name", required=False)
def llm_test(name: str | None) -> None:
    """Test connection to an LLM provider.

    Arguments:
        NAME: The name of the provider to test (defaults to active provider).
    """
    if name:
        provider = get_provider(name)
        if not provider:
            click.secho(f"Error: Provider '{name}' not found.", fg="red")
            raise click.Abort()
    else:
        provider = get_active_provider()
        if not provider:
            click.echo("No active provider configured.")
            click.echo()
            click.echo("Run 'docman llm add' to add a provider.")
            return

    click.echo(f"Testing connection to '{provider.name}'...")

    # Get API key
    api_key = get_api_key(provider.name)
    if not api_key:
        click.secho("Error: API key not found for this provider.", fg="red")
        raise click.Abort()

    # Test connection
    try:
        llm_provider = get_llm_provider(provider, api_key)
        llm_provider.test_connection()
        click.secho("Connection successful!", fg="green")
    except Exception as e:
        click.secho("Connection failed:", fg="red")
        click.secho(f"  {str(e)}", fg="red")
        raise click.Abort()
