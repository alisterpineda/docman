"""Interactive wizard for setting up LLM provider configuration.

This module provides an interactive setup wizard for first-time LLM configuration,
guiding users through provider selection and API key setup.
"""

import click

from docman.llm_config import ProviderConfig, add_provider
from docman.llm_providers import get_provider, list_available_models


def run_llm_wizard() -> bool:
    """Run the interactive LLM setup wizard.

    Guides the user through:
    1. Provider selection (Google Gemini or OpenAI-compatible)
    2. Custom endpoint input (for OpenAI-compatible servers)
    3. API key input
    4. Connection testing and model fetching
    5. Model selection (from available models)
    6. Provider naming
    7. Configuration saving

    Returns:
        True if setup completed successfully, False if cancelled or failed.
    """
    click.echo()
    click.secho("LLM Provider Setup", fg="cyan", bold=True)
    click.echo("=" * 50)
    click.echo()
    click.echo("Docman uses LLM models to intelligently organize your documents.")
    click.echo("Let's set up your first LLM provider.")
    click.echo()

    # Step 1: Provider selection
    provider_type = _select_provider()
    if provider_type is None:
        click.secho("\nSetup cancelled.", fg="yellow")
        return False

    # Step 2: Get custom endpoint (for OpenAI-compatible providers)
    endpoint = None
    if provider_type == "openai":
        endpoint = _get_endpoint()
        # endpoint can be None, which is fine (uses default OpenAI endpoint)

    # Step 3: Get API key
    api_key = _get_api_key(provider_type)
    if api_key is None:
        click.secho("\nSetup cancelled.", fg="yellow")
        return False

    # Step 4: Test connection and fetch available models
    click.echo()
    click.echo("Verifying API key and fetching available models...")

    try:
        models = list_available_models(provider_type, api_key, endpoint)
        if not models:
            click.secho("✗ No models available for this API key.", fg="red")
            return False
        click.secho(f"✓ Found {len(models)} available model(s)", fg="green")
    except ValueError as e:
        # Unsupported provider type
        click.secho(f"✗ {str(e)}", fg="red")
        return False
    except Exception as e:
        click.secho("✗ Failed to verify API key:", fg="red")
        click.secho(f"  {str(e)}", fg="red")
        return False

    # Step 5: Model selection
    model = _select_model(provider_type, models)
    if model is None:
        click.secho("\nSetup cancelled.", fg="yellow")
        return False

    # Step 6: Provider name
    provider_name = _get_provider_name(provider_type)
    if provider_name is None:
        click.secho("\nSetup cancelled.", fg="yellow")
        return False

    # Step 7: Final connection test with selected model
    click.echo()
    click.echo(f"Testing connection with model '{model}'...")

    provider_config = ProviderConfig(
        name=provider_name,
        provider_type=provider_type,
        model=model,
        endpoint=endpoint,
        is_active=True,
    )

    try:
        provider = get_provider(provider_config, api_key)
        provider.test_connection()
        click.secho("✓ Connection successful!", fg="green")
    except Exception as e:
        click.secho("✗ Connection test failed:", fg="red")
        click.secho(f"  {str(e)}", fg="red")
        return False

    # Step 7: Save configuration
    click.echo()
    click.echo("Saving configuration...")

    try:
        add_provider(provider_config, api_key)
        click.secho("✓ Configuration saved successfully!", fg="green")
        click.echo()
        click.secho(f"Provider '{provider_name}' is now active.", fg="green")
        click.echo()
        return True
    except Exception as e:
        click.secho(f"✗ Failed to save configuration: {str(e)}", fg="red")
        return False


def _select_provider() -> str | None:
    """Prompt user to select an LLM provider.

    Returns:
        Provider type string (e.g., "google", "openai"), or None if cancelled.
    """
    click.echo("Available LLM providers:")
    click.echo("  1. Google Gemini")
    click.echo("  2. OpenAI-compatible (OpenAI API, LM Studio, vLLM, etc.)")
    click.echo()

    choice = click.prompt(
        "Select a provider",
        type=click.Choice(["1", "2"], case_sensitive=False),
        default="1",
        show_choices=False,
    )

    if choice == "1":
        return "google"
    elif choice == "2":
        return "openai"

    return None


def _get_endpoint() -> str | None:
    """Prompt user for custom endpoint URL.

    Returns:
        Endpoint URL string, or None if skipped/cancelled.
    """
    click.echo()
    click.echo("Enter a custom API endpoint URL (optional).")
    click.echo("Examples:")
    click.echo("  - LM Studio: http://localhost:1234/v1")
    click.echo("  - vLLM server: http://192.168.1.100:8000/v1")
    click.echo("  - Leave blank to use OpenAI's official API")
    click.echo()

    endpoint: str = click.prompt(
        "API endpoint URL",
        type=str,
        default="",
    )

    if not endpoint or not endpoint.strip():
        return None

    return endpoint.strip()


def _get_api_key(provider_type: str) -> str | None:
    """Prompt user for API key.

    Args:
        provider_type: Type of provider (e.g., "google", "openai")

    Returns:
        API key string, or None if cancelled.
    """
    click.echo()

    if provider_type == "google":
        click.echo("You'll need a Google AI API key.")
        click.echo("Get one at: https://aistudio.google.com/app/apikey")
        click.echo()
    elif provider_type == "openai":
        click.echo("You'll need an OpenAI API key.")
        click.echo("Get one at: https://platform.openai.com/api-keys")
        click.echo()
        click.echo("Note: For local servers (LM Studio, etc.), you can use any non-empty value.")
        click.echo()

    api_key: str = click.prompt(
        "Enter your API key",
        hide_input=True,
        type=str,
        default="",
    )

    if not api_key or not api_key.strip():
        return None

    return api_key.strip()


def _select_model(provider_type: str, models: list[dict[str, str]]) -> str | None:
    """Prompt user to select a model from available models.

    Args:
        provider_type: Type of provider (e.g., "google", "openai")
        models: List of model dictionaries with 'name', 'display_name', and 'description'

    Returns:
        Model identifier string, or None if cancelled.
    """
    click.echo()

    if provider_type == "google":
        click.echo("Available Google Gemini models:")
        click.echo()

        # Sort models by name and display them
        sorted_models = sorted(models, key=lambda m: m["name"])

        # Highlight recommended models
        recommended_models = {"gemini-1.5-flash", "gemini-2.0-flash-exp"}

        for idx, model in enumerate(sorted_models, start=1):
            model_name = model["name"]
            display_name = model.get("display_name", model_name)

            # Add recommended tag
            tag = ""
            if model_name in recommended_models:
                tag = " (recommended)" if "flash" in model_name.lower() else ""

            click.echo(f"  {idx}. {display_name}{tag}")

            # Show description if available (truncated)
            description = model.get("description", "")
            if description:
                # Truncate long descriptions
                if len(description) > 80:
                    description = description[:77] + "..."
                click.echo(f"     {description}")

        click.echo()

        # Create choice list
        choices = [str(i) for i in range(1, len(sorted_models) + 1)]

        choice = click.prompt(
            "Select a model",
            type=click.Choice(choices, case_sensitive=False),
            default="1",
            show_choices=False,
        )

        # Return the selected model name
        idx = int(choice) - 1
        return sorted_models[idx]["name"]

    elif provider_type == "openai":
        click.echo("Available OpenAI-compatible models:")
        click.echo()

        # Sort models by name and display them
        sorted_models = sorted(models, key=lambda m: m["name"])

        # Highlight recommended OpenAI models
        recommended_models = {"gpt-4o", "gpt-4o-mini", "gpt-4-turbo"}

        for idx, model in enumerate(sorted_models, start=1):
            model_name = model["name"]
            display_name = model.get("display_name", model_name)

            # Add recommended tag for known OpenAI models
            tag = ""
            if model_name in recommended_models:
                tag = " (recommended)"

            click.echo(f"  {idx}. {display_name}{tag}")

            # Show description if available (truncated)
            description = model.get("description", "")
            if description:
                # Truncate long descriptions
                if len(description) > 80:
                    description = description[:77] + "..."
                click.echo(f"     {description}")

        click.echo()

        # Create choice list
        choices = [str(i) for i in range(1, len(sorted_models) + 1)]

        choice = click.prompt(
            "Select a model",
            type=click.Choice(choices, case_sensitive=False),
            default="1",
            show_choices=False,
        )

        # Return the selected model name
        idx = int(choice) - 1
        return sorted_models[idx]["name"]

    return None


def _get_provider_name(provider_type: str) -> str | None:
    """Prompt user for a name for this provider configuration.

    Args:
        provider_type: Type of provider (e.g., "google")

    Returns:
        Provider name string, or None if cancelled.
    """
    click.echo()

    default_name = f"{provider_type}-default"

    provider_name: str = click.prompt(
        "Enter a name for this configuration",
        type=str,
        default=default_name,
    )

    if not provider_name or not provider_name.strip():
        return None

    return provider_name.strip()
