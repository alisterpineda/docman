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
    1. Provider selection (currently Google Gemini only)
    2. API key input
    3. Connection testing and model fetching
    4. Model selection (from available models)
    5. Provider naming
    6. Configuration saving

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

    # Step 1: Provider selection (for now, only Google Gemini)
    provider_type = _select_provider()
    if provider_type is None:
        click.secho("\nSetup cancelled.", fg="yellow")
        return False

    # Step 2: Get API key (skip for local providers)
    api_key = _get_api_key(provider_type)
    if api_key is None:
        click.secho("\nSetup cancelled.", fg="yellow")
        return False

    # Step 3: Model selection (different flow for local vs cloud providers)
    if provider_type == "local":
        # For local providers, prompt for model name and quantization
        model = _get_local_model_name()
        if model is None:
            click.secho("\nSetup cancelled.", fg="yellow")
            return False

        # Check if model is already downloaded, offer to download if not
        if not _ensure_model_downloaded(model):
            click.secho("\nSetup cancelled.", fg="yellow")
            return False

        # Check if model is pre-quantized (skip quantization selection if so)
        from docman.model_download import is_pre_quantized_model

        if is_pre_quantized_model(model):
            click.echo()
            click.secho(
                f"ℹ️  Model '{model}' appears to be pre-quantized.",
                fg="cyan"
            )
            click.echo("Skipping runtime quantization (will use model as-is).")
            quantization = None
        else:
            quantization = _select_quantization()
            if quantization is None:
                click.secho("\nSetup cancelled.", fg="yellow")
                return False
    else:
        # For cloud providers, fetch and list available models
        click.echo()
        click.echo("Verifying API key and fetching available models...")

        try:
            models = list_available_models(provider_type, api_key)
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

        # Step 4: Model selection
        model = _select_model(provider_type, models)
        if model is None:
            click.secho("\nSetup cancelled.", fg="yellow")
            return False

        quantization = None  # Cloud providers don't use quantization

    # Step 5: Provider name
    provider_name = _get_provider_name(provider_type)
    if provider_name is None:
        click.secho("\nSetup cancelled.", fg="yellow")
        return False

    # Step 6: Final connection test with selected model
    click.echo()
    if provider_type == "local":
        click.echo(f"Testing local model '{model}'...")
        if quantization:
            click.echo(f"  (using {quantization} quantization)")
    else:
        click.echo(f"Testing connection with model '{model}'...")

    provider_config = ProviderConfig(
        name=provider_name,
        provider_type=provider_type,
        model=model,
        quantization=quantization,
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
        Provider type string (e.g., "google", "local"), or None if cancelled.
    """
    click.echo("Available LLM providers:")
    click.echo("  1. Google Gemini (cloud API)")
    click.echo("  2. Local Model (transformers or MLX, runs on your machine)")
    click.echo("  (More providers coming soon)")
    click.echo()

    choice = click.prompt(
        "Select a provider",
        type=click.Choice(["1", "2"], case_sensitive=False),
        default="2",
        show_choices=False,
    )

    if choice == "1":
        return "google"
    elif choice == "2":
        return "local"

    return None


def _get_api_key(provider_type: str) -> str | None:
    """Prompt user for API key.

    Args:
        provider_type: Type of provider (e.g., "google", "local")

    Returns:
        API key string, or None if cancelled. Returns empty string for local providers.
    """
    click.echo()

    if provider_type == "local":
        # Local providers don't need API keys
        click.echo("Local models don't require an API key.")
        return ""

    if provider_type == "google":
        click.echo("You'll need a Google AI API key.")
        click.echo("Get one at: https://aistudio.google.com/app/apikey")
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
        provider_type: Type of provider (e.g., "google")
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


def _get_local_model_name() -> str | None:
    """Prompt user for a local model name.

    Returns:
        Model name/path string, or None if cancelled.
    """
    click.echo()
    click.echo("Enter the HuggingFace model identifier.")
    click.echo()
    click.echo("Examples:")
    click.echo("  - Transformers: google/gemma-3n-E4B, mistralai/Mistral-7B-Instruct-v0.2")
    click.echo("  - MLX (Apple Silicon): mlx-community/gemma-3n-E4B-it-4bit")
    click.echo()

    model_name: str = click.prompt(
        "Model identifier",
        type=str,
        default="google/gemma-3n-E4B",
    )

    if not model_name or not model_name.strip():
        return None

    return model_name.strip()


def _select_quantization() -> str | None:
    """Prompt user to select quantization level for local model.

    Returns:
        Quantization level ("4bit", "8bit", or None for full precision),
        or None if cancelled.
    """
    click.echo()
    click.echo("Select quantization level:")
    click.echo("  1. 4-bit quantization (lowest memory, ~3-4GB VRAM)")
    click.echo("  2. 8-bit quantization (medium memory, ~6-8GB VRAM)")
    click.echo("  3. Full precision (highest memory, ~12-16GB VRAM)")
    click.echo()
    click.echo("Note: Quantization reduces memory usage but may slightly affect quality.")
    click.echo()

    choice = click.prompt(
        "Select quantization",
        type=click.Choice(["1", "2", "3"], case_sensitive=False),
        default="1",
        show_choices=False,
    )

    if choice == "1":
        return "4bit"
    elif choice == "2":
        return "8bit"
    elif choice == "3":
        return None  # Full precision

    return None


def _ensure_model_downloaded(model_id: str) -> bool:
    """Check if model is downloaded and offer to download if not.

    Args:
        model_id: HuggingFace model identifier

    Returns:
        True if model is available (already downloaded or user chose to download),
        False if model not available and user declined to download.
    """
    from docman.model_download import check_model_exists, download_model, get_model_info

    # Check if model already exists
    if check_model_exists(model_id):
        click.echo()
        click.secho(f"✓ Model '{model_id}' is already downloaded.", fg="green")
        return True

    # Model not found, offer to download
    click.echo()
    click.secho(f"✗ Model '{model_id}' is not downloaded yet.", fg="yellow")
    click.echo()

    # Get model info if available
    model_info = get_model_info(model_id)
    if model_info:
        click.echo(f"Model info:")
        click.echo(f"  Downloads: {model_info['downloads']}")
        click.echo(f"  Likes: {model_info['likes']}")
        click.echo(f"  Type: {model_info['pipeline_tag']}")
        click.echo()

    click.echo("Note: Model downloads can be several GB in size.")
    click.echo("      Download time depends on your network speed.")
    click.echo()

    if not click.confirm(f"Would you like to download '{model_id}' now?", default=True):
        click.echo()
        click.echo("You can download the model later with:")
        click.echo(f"  docman llm download-model {model_id}")
        return False

    # Download the model
    click.echo()
    click.echo("Downloading model...")

    def progress_callback(message: str) -> None:
        """Print progress messages."""
        click.echo(message)

    try:
        download_model(model_id, progress_callback=progress_callback)
        click.echo()
        click.secho("✓ Model downloaded successfully!", fg="green")
        return True
    except Exception as e:
        click.echo()
        click.secho("✗ Download failed:", fg="red")
        click.secho(f"  {str(e)}", fg="red")
        click.echo()
        click.echo("You can try downloading the model later with:")
        click.echo(f"  docman llm download-model {model_id}")
        return False
