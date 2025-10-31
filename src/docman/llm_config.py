"""LLM provider configuration management for docman.

This module handles the configuration and management of LLM providers, including
secure storage of API keys using the OS keychain/credential manager.
"""

from dataclasses import dataclass
from typing import Any

import keyring

from docman.config import load_app_config, save_app_config

# Keyring service name for storing LLM API keys
KEYRING_SERVICE_NAME = "docman_llm"


@dataclass
class ProviderConfig:
    """Configuration for an LLM provider.

    Attributes:
        name: Unique identifier for this provider configuration (e.g., "my-gemini-api")
        provider_type: Type of provider (e.g., "google", "anthropic", "openai", "local")
        model: Model identifier (e.g., "gemini-1.5-flash", "claude-3-5-sonnet")
        endpoint: Optional custom API endpoint URL
        is_active: Whether this is the currently active provider
    """

    name: str
    provider_type: str
    model: str
    endpoint: str | None = None
    is_active: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert ProviderConfig to dictionary for YAML serialization."""
        result: dict[str, Any] = {
            "name": self.name,
            "provider_type": self.provider_type,
            "model": self.model,
            "is_active": self.is_active,
        }
        if self.endpoint:
            result["endpoint"] = self.endpoint
        return result

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ProviderConfig":
        """Create ProviderConfig from dictionary loaded from YAML."""
        return ProviderConfig(
            name=data["name"],
            provider_type=data["provider_type"],
            model=data["model"],
            endpoint=data.get("endpoint"),
            is_active=data.get("is_active", False),
        )


def get_providers() -> list[ProviderConfig]:
    """Load all configured LLM providers from app configuration.

    Returns:
        List of ProviderConfig objects. Returns empty list if no providers configured.
    """
    config = load_app_config()
    llm_config = config.get("llm", {})
    providers_data = llm_config.get("providers", [])

    return [ProviderConfig.from_dict(p) for p in providers_data]


def get_provider(name: str) -> ProviderConfig | None:
    """Get a specific provider configuration by name.

    Args:
        name: The unique name of the provider to retrieve.

    Returns:
        ProviderConfig if found, None otherwise.
    """
    providers = get_providers()
    for provider in providers:
        if provider.name == name:
            return provider
    return None


def add_provider(provider: ProviderConfig, api_key: str) -> None:
    """Add a new LLM provider configuration.

    Stores the provider configuration in config.yaml and the API key
    securely in the OS keychain.

    Args:
        provider: ProviderConfig object with provider details.
        api_key: The API key to store securely in the keychain.

    Raises:
        ValueError: If a provider with the same name already exists.
    """
    providers = get_providers()

    # Check if provider with this name already exists
    if any(p.name == provider.name for p in providers):
        raise ValueError(f"Provider with name '{provider.name}' already exists")

    # If this is the first provider or is_active is True, make it active
    if not providers or provider.is_active:
        # Deactivate all other providers
        for p in providers:
            p.is_active = False
        provider.is_active = True

    # Add the new provider
    providers.append(provider)

    # Save to config
    _save_providers(providers)

    # Store API key in keychain
    keyring.set_password(KEYRING_SERVICE_NAME, provider.name, api_key)


def remove_provider(name: str) -> bool:
    """Remove an LLM provider configuration.

    Removes the provider from config.yaml and deletes the API key from the keychain.

    Args:
        name: The unique name of the provider to remove.

    Returns:
        True if provider was removed, False if provider not found.
    """
    providers = get_providers()

    # Find and remove the provider
    provider_to_remove = None
    new_providers = []
    for p in providers:
        if p.name == name:
            provider_to_remove = p
        else:
            new_providers.append(p)

    if provider_to_remove is None:
        return False

    # If we removed the active provider and there are others, make the first one active
    if provider_to_remove.is_active and new_providers:
        new_providers[0].is_active = True

    # Save updated providers list
    _save_providers(new_providers)

    # Remove API key from keychain
    try:
        keyring.delete_password(KEYRING_SERVICE_NAME, name)
    except keyring.errors.PasswordDeleteError:
        # Key might not exist in keychain, that's okay
        pass

    return True


def set_active_provider(name: str) -> bool:
    """Set a provider as the active one.

    Args:
        name: The unique name of the provider to activate.

    Returns:
        True if provider was activated, False if provider not found.
    """
    providers = get_providers()

    found = False
    for p in providers:
        if p.name == name:
            p.is_active = True
            found = True
        else:
            p.is_active = False

    if not found:
        return False

    _save_providers(providers)
    return True


def get_active_provider() -> ProviderConfig | None:
    """Get the currently active LLM provider.

    Returns:
        ProviderConfig of the active provider, or None if no providers configured
        or no provider is marked as active.
    """
    providers = get_providers()
    for provider in providers:
        if provider.is_active:
            return provider
    return None


def get_api_key(provider_name: str) -> str | None:
    """Retrieve the API key for a provider from the OS keychain.

    Args:
        provider_name: The unique name of the provider.

    Returns:
        The API key string if found, None otherwise.
    """
    try:
        return keyring.get_password(KEYRING_SERVICE_NAME, provider_name)
    except Exception:
        return None


def _save_providers(providers: list[ProviderConfig]) -> None:
    """Save the list of providers to app configuration.

    Private helper function to persist provider configurations.

    Args:
        providers: List of ProviderConfig objects to save.
    """
    config = load_app_config()

    # Ensure llm key exists
    if "llm" not in config:
        config["llm"] = {}

    # Convert providers to dictionaries
    config["llm"]["providers"] = [p.to_dict() for p in providers]

    save_app_config(config)
