"""Unit tests for the llm_config module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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


class TestProviderConfig:
    """Tests for ProviderConfig dataclass."""

    def test_to_dict_basic(self) -> None:
        """Test converting ProviderConfig to dictionary."""
        provider = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )

        result = provider.to_dict()

        assert result["name"] == "test-provider"
        assert result["provider_type"] == "google"
        assert result["model"] == "gemini-1.5-flash"
        assert result["is_active"] is True
        assert "endpoint" not in result

    def test_to_dict_with_endpoint(self) -> None:
        """Test converting ProviderConfig with endpoint to dictionary."""
        provider = ProviderConfig(
            name="test-provider",
            provider_type="local",
            model="llama-3",
            endpoint="http://localhost:8080",
            is_active=False,
        )

        result = provider.to_dict()

        assert result["endpoint"] == "http://localhost:8080"

    def test_from_dict_basic(self) -> None:
        """Test creating ProviderConfig from dictionary."""
        data = {
            "name": "test-provider",
            "provider_type": "anthropic",
            "model": "claude-3-5-sonnet",
            "is_active": True,
        }

        provider = ProviderConfig.from_dict(data)

        assert provider.name == "test-provider"
        assert provider.provider_type == "anthropic"
        assert provider.model == "claude-3-5-sonnet"
        assert provider.is_active is True
        assert provider.endpoint is None

    def test_from_dict_with_endpoint(self) -> None:
        """Test creating ProviderConfig from dictionary with endpoint."""
        data = {
            "name": "test-provider",
            "provider_type": "local",
            "model": "llama-3",
            "endpoint": "http://localhost:8080",
        }

        provider = ProviderConfig.from_dict(data)

        assert provider.endpoint == "http://localhost:8080"
        assert provider.is_active is False  # Default value


class TestAddProvider:
    """Tests for add_provider function."""

    @patch("docman.llm_config.keyring")
    @patch("docman.llm_config.save_app_config")
    @patch("docman.llm_config.load_app_config")
    def test_add_first_provider_success(
        self,
        mock_load_config: MagicMock,
        mock_save_config: MagicMock,
        mock_keyring: MagicMock,
    ) -> None:
        """Test successfully adding the first provider."""
        mock_load_config.return_value = {}

        provider = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
        )

        add_provider(provider, "test-api-key")

        # Verify keyring was called BEFORE save_config
        mock_keyring.set_password.assert_called_once_with(
            "docman_llm", "test-provider", "test-api-key"
        )
        mock_save_config.assert_called_once()

        # Verify provider is marked as active (first provider)
        saved_config = mock_save_config.call_args[0][0]
        assert saved_config["llm"]["providers"][0]["is_active"] is True

    @patch("docman.llm_config.keyring")
    @patch("docman.llm_config.save_app_config")
    @patch("docman.llm_config.load_app_config")
    def test_add_provider_keyring_failure_prevents_config_save(
        self,
        mock_load_config: MagicMock,
        mock_save_config: MagicMock,
        mock_keyring: MagicMock,
    ) -> None:
        """Test that keyring failure prevents config from being modified."""
        mock_load_config.return_value = {}
        # Simulate keyring failure (common on headless Linux)
        mock_keyring.set_password.side_effect = RuntimeError("No keyring backend available")

        provider = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
        )

        # Should raise RuntimeError with helpful message
        with pytest.raises(RuntimeError) as exc_info:
            add_provider(provider, "test-api-key")

        # Verify error message is helpful
        assert "Failed to store API key securely" in str(exc_info.value)
        assert "headless systems" in str(exc_info.value)

        # CRITICAL: Verify config was NOT saved when keyring failed
        mock_save_config.assert_not_called()

    @patch("docman.llm_config.keyring")
    @patch("docman.llm_config.save_app_config")
    @patch("docman.llm_config.load_app_config")
    def test_add_provider_duplicate_name_raises_error(
        self,
        mock_load_config: MagicMock,
        mock_save_config: MagicMock,
        mock_keyring: MagicMock,
    ) -> None:
        """Test that adding a provider with duplicate name raises ValueError."""
        mock_load_config.return_value = {
            "llm": {
                "providers": [
                    {
                        "name": "existing-provider",
                        "provider_type": "google",
                        "model": "gemini-1.5-flash",
                        "is_active": True,
                    }
                ]
            }
        }

        provider = ProviderConfig(
            name="existing-provider",
            provider_type="anthropic",
            model="claude-3-5-sonnet",
        )

        with pytest.raises(ValueError) as exc_info:
            add_provider(provider, "test-api-key")

        assert "already exists" in str(exc_info.value)
        mock_keyring.set_password.assert_not_called()
        mock_save_config.assert_not_called()

    @patch("docman.llm_config.keyring")
    @patch("docman.llm_config.save_app_config")
    @patch("docman.llm_config.load_app_config")
    def test_add_second_provider_deactivates_first(
        self,
        mock_load_config: MagicMock,
        mock_save_config: MagicMock,
        mock_keyring: MagicMock,
    ) -> None:
        """Test that adding a second provider deactivates the first."""
        mock_load_config.return_value = {
            "llm": {
                "providers": [
                    {
                        "name": "first-provider",
                        "provider_type": "google",
                        "model": "gemini-1.5-flash",
                        "is_active": True,
                    }
                ]
            }
        }

        provider = ProviderConfig(
            name="second-provider",
            provider_type="anthropic",
            model="claude-3-5-sonnet",
            is_active=True,
        )

        add_provider(provider, "test-api-key")

        saved_config = mock_save_config.call_args[0][0]
        providers = saved_config["llm"]["providers"]

        # First provider should be deactivated
        assert providers[0]["is_active"] is False
        # Second provider should be active
        assert providers[1]["is_active"] is True


class TestGetProviders:
    """Tests for get_providers function."""

    @patch("docman.llm_config.load_app_config")
    def test_get_providers_empty_config(self, mock_load_config: MagicMock) -> None:
        """Test get_providers returns empty list for empty config."""
        mock_load_config.return_value = {}

        result = get_providers()

        assert result == []

    @patch("docman.llm_config.load_app_config")
    def test_get_providers_with_providers(self, mock_load_config: MagicMock) -> None:
        """Test get_providers returns list of ProviderConfig objects."""
        mock_load_config.return_value = {
            "llm": {
                "providers": [
                    {
                        "name": "provider-1",
                        "provider_type": "google",
                        "model": "gemini-1.5-flash",
                        "is_active": True,
                    },
                    {
                        "name": "provider-2",
                        "provider_type": "anthropic",
                        "model": "claude-3-5-sonnet",
                        "is_active": False,
                    },
                ]
            }
        }

        result = get_providers()

        assert len(result) == 2
        assert result[0].name == "provider-1"
        assert result[1].name == "provider-2"


class TestGetProvider:
    """Tests for get_provider function."""

    @patch("docman.llm_config.load_app_config")
    def test_get_provider_found(self, mock_load_config: MagicMock) -> None:
        """Test get_provider returns the correct provider."""
        mock_load_config.return_value = {
            "llm": {
                "providers": [
                    {
                        "name": "test-provider",
                        "provider_type": "google",
                        "model": "gemini-1.5-flash",
                        "is_active": True,
                    }
                ]
            }
        }

        result = get_provider("test-provider")

        assert result is not None
        assert result.name == "test-provider"

    @patch("docman.llm_config.load_app_config")
    def test_get_provider_not_found(self, mock_load_config: MagicMock) -> None:
        """Test get_provider returns None when provider not found."""
        mock_load_config.return_value = {"llm": {"providers": []}}

        result = get_provider("nonexistent-provider")

        assert result is None


class TestRemoveProvider:
    """Tests for remove_provider function."""

    @patch("docman.llm_config.keyring")
    @patch("docman.llm_config.save_app_config")
    @patch("docman.llm_config.load_app_config")
    def test_remove_provider_success(
        self,
        mock_load_config: MagicMock,
        mock_save_config: MagicMock,
        mock_keyring: MagicMock,
    ) -> None:
        """Test successfully removing a provider."""
        mock_load_config.return_value = {
            "llm": {
                "providers": [
                    {
                        "name": "test-provider",
                        "provider_type": "google",
                        "model": "gemini-1.5-flash",
                        "is_active": True,
                    }
                ]
            }
        }

        result = remove_provider("test-provider")

        assert result is True
        mock_keyring.delete_password.assert_called_once_with("docman_llm", "test-provider")
        mock_save_config.assert_called_once()

    @patch("docman.llm_config.keyring")
    @patch("docman.llm_config.save_app_config")
    @patch("docman.llm_config.load_app_config")
    def test_remove_provider_not_found(
        self,
        mock_load_config: MagicMock,
        mock_save_config: MagicMock,
        mock_keyring: MagicMock,
    ) -> None:
        """Test removing a nonexistent provider returns False."""
        mock_load_config.return_value = {"llm": {"providers": []}}

        result = remove_provider("nonexistent-provider")

        assert result is False
        mock_keyring.delete_password.assert_not_called()
        mock_save_config.assert_not_called()


class TestSetActiveProvider:
    """Tests for set_active_provider function."""

    @patch("docman.llm_config.save_app_config")
    @patch("docman.llm_config.load_app_config")
    def test_set_active_provider_success(
        self,
        mock_load_config: MagicMock,
        mock_save_config: MagicMock,
    ) -> None:
        """Test successfully setting a provider as active."""
        mock_load_config.return_value = {
            "llm": {
                "providers": [
                    {
                        "name": "provider-1",
                        "provider_type": "google",
                        "model": "gemini-1.5-flash",
                        "is_active": True,
                    },
                    {
                        "name": "provider-2",
                        "provider_type": "anthropic",
                        "model": "claude-3-5-sonnet",
                        "is_active": False,
                    },
                ]
            }
        }

        result = set_active_provider("provider-2")

        assert result is True
        saved_config = mock_save_config.call_args[0][0]
        providers = saved_config["llm"]["providers"]
        assert providers[0]["is_active"] is False
        assert providers[1]["is_active"] is True


class TestGetActiveProvider:
    """Tests for get_active_provider function."""

    @patch("docman.llm_config.load_app_config")
    def test_get_active_provider_found(self, mock_load_config: MagicMock) -> None:
        """Test get_active_provider returns the active provider."""
        mock_load_config.return_value = {
            "llm": {
                "providers": [
                    {
                        "name": "active-provider",
                        "provider_type": "google",
                        "model": "gemini-1.5-flash",
                        "is_active": True,
                    }
                ]
            }
        }

        result = get_active_provider()

        assert result is not None
        assert result.name == "active-provider"

    @patch("docman.llm_config.load_app_config")
    def test_get_active_provider_none_active(self, mock_load_config: MagicMock) -> None:
        """Test get_active_provider returns None when no provider is active."""
        mock_load_config.return_value = {
            "llm": {
                "providers": [
                    {
                        "name": "inactive-provider",
                        "provider_type": "google",
                        "model": "gemini-1.5-flash",
                        "is_active": False,
                    }
                ]
            }
        }

        result = get_active_provider()

        assert result is None


class TestGetApiKey:
    """Tests for get_api_key function."""

    @patch("docman.llm_config.keyring")
    def test_get_api_key_success(self, mock_keyring: MagicMock) -> None:
        """Test successfully retrieving an API key."""
        mock_keyring.get_password.return_value = "test-api-key"

        result = get_api_key("test-provider")

        assert result == "test-api-key"
        mock_keyring.get_password.assert_called_once_with("docman_llm", "test-provider")

    @patch("docman.llm_config.keyring")
    def test_get_api_key_not_found(self, mock_keyring: MagicMock) -> None:
        """Test get_api_key returns None when key not found."""
        mock_keyring.get_password.return_value = None

        result = get_api_key("nonexistent-provider")

        assert result is None

    @patch("docman.llm_config.keyring")
    def test_get_api_key_exception_returns_none(self, mock_keyring: MagicMock) -> None:
        """Test get_api_key returns None when keyring raises exception."""
        mock_keyring.get_password.side_effect = RuntimeError("Keyring error")

        result = get_api_key("test-provider")

        assert result is None
