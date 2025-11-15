"""Unit tests for LLM wizard interactive setup."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from click.testing import CliRunner

from docman.llm_wizard import (
    run_llm_wizard,
    _select_provider,
    _get_endpoint,
    _get_api_key,
    _select_model,
    _get_provider_name,
)


class TestSelectProvider:
    """Tests for _select_provider function."""

    def test_select_google_provider(self):
        """Test selecting Google Gemini provider."""
        with patch("click.prompt") as mock_prompt:
            mock_prompt.return_value = "1"
            result = _select_provider()
            assert result == "google"

    def test_select_openai_provider(self):
        """Test selecting OpenAI-compatible provider."""
        with patch("click.prompt") as mock_prompt:
            mock_prompt.return_value = "2"
            result = _select_provider()
            assert result == "openai"


class TestGetEndpoint:
    """Tests for _get_endpoint function."""

    def test_returns_endpoint_when_provided(self):
        """Test that endpoint is returned when user provides one."""
        with patch("click.prompt") as mock_prompt:
            mock_prompt.return_value = "http://localhost:1234/v1"
            result = _get_endpoint()
            assert result == "http://localhost:1234/v1"

    def test_returns_none_when_empty(self):
        """Test that None is returned when user provides empty string."""
        with patch("click.prompt") as mock_prompt:
            mock_prompt.return_value = ""
            result = _get_endpoint()
            assert result is None

    def test_returns_none_when_whitespace_only(self):
        """Test that None is returned when user provides only whitespace."""
        with patch("click.prompt") as mock_prompt:
            mock_prompt.return_value = "   "
            result = _get_endpoint()
            assert result is None

    def test_strips_whitespace_from_endpoint(self):
        """Test that whitespace is stripped from endpoint URL."""
        with patch("click.prompt") as mock_prompt:
            mock_prompt.return_value = "  http://localhost:1234/v1  "
            result = _get_endpoint()
            assert result == "http://localhost:1234/v1"


class TestGetApiKey:
    """Tests for _get_api_key function."""

    def test_returns_api_key_for_google_provider(self):
        """Test that API key is returned for Google provider."""
        with patch("click.prompt") as mock_prompt:
            mock_prompt.return_value = "test-api-key-123"
            result = _get_api_key("google")
            assert result == "test-api-key-123"

    def test_returns_api_key_for_openai_provider(self):
        """Test that API key is returned for OpenAI provider."""
        with patch("click.prompt") as mock_prompt:
            mock_prompt.return_value = "sk-test123"
            result = _get_api_key("openai")
            assert result == "sk-test123"

    def test_returns_none_when_empty(self):
        """Test that None is returned when user provides empty API key."""
        with patch("click.prompt") as mock_prompt:
            mock_prompt.return_value = ""
            result = _get_api_key("google")
            assert result is None

    def test_returns_none_when_whitespace_only(self):
        """Test that None is returned when user provides only whitespace."""
        with patch("click.prompt") as mock_prompt:
            mock_prompt.return_value = "   "
            result = _get_api_key("google")
            assert result is None

    def test_strips_whitespace_from_api_key(self):
        """Test that whitespace is stripped from API key."""
        with patch("click.prompt") as mock_prompt:
            mock_prompt.return_value = "  test-key-123  "
            result = _get_api_key("google")
            assert result == "test-key-123"


class TestSelectModel:
    """Tests for _select_model function."""

    def test_select_google_model_first_choice(self):
        """Test selecting first Google Gemini model."""
        models = [
            {"name": "gemini-1.5-flash", "display_name": "Gemini 1.5 Flash"},
            {"name": "gemini-1.5-pro", "display_name": "Gemini 1.5 Pro"},
        ]
        with patch("click.prompt") as mock_prompt:
            mock_prompt.return_value = "1"
            result = _select_model("google", models)
            assert result == "gemini-1.5-flash"

    def test_select_google_model_second_choice(self):
        """Test selecting second Google Gemini model."""
        models = [
            {"name": "gemini-1.5-flash", "display_name": "Gemini 1.5 Flash"},
            {"name": "gemini-1.5-pro", "display_name": "Gemini 1.5 Pro"},
        ]
        with patch("click.prompt") as mock_prompt:
            mock_prompt.return_value = "2"
            result = _select_model("google", models)
            assert result == "gemini-1.5-pro"

    def test_select_openai_model(self):
        """Test selecting OpenAI model."""
        models = [
            {"name": "gpt-4o", "display_name": "GPT-4o"},
            {"name": "gpt-4o-mini", "display_name": "GPT-4o Mini"},
        ]
        with patch("click.prompt") as mock_prompt:
            mock_prompt.return_value = "1"
            result = _select_model("openai", models)
            assert result == "gpt-4o"

    def test_models_sorted_alphabetically(self):
        """Test that models are sorted alphabetically before selection."""
        models = [
            {"name": "gemini-1.5-pro", "display_name": "Gemini 1.5 Pro"},
            {"name": "gemini-1.5-flash", "display_name": "Gemini 1.5 Flash"},
            {"name": "gemini-2.0-flash", "display_name": "Gemini 2.0 Flash"},
        ]
        with patch("click.prompt") as mock_prompt:
            mock_prompt.return_value = "1"
            result = _select_model("google", models)
            # First alphabetically is gemini-1.5-flash
            assert result == "gemini-1.5-flash"

    def test_returns_none_for_unsupported_provider(self):
        """Test that None is returned for unsupported provider type."""
        models = [{"name": "test-model", "display_name": "Test Model"}]
        result = _select_model("unsupported", models)
        assert result is None


class TestGetProviderName:
    """Tests for _get_provider_name function."""

    def test_returns_custom_name_when_provided(self):
        """Test that custom name is returned when user provides one."""
        with patch("click.prompt") as mock_prompt:
            mock_prompt.return_value = "my-custom-provider"
            result = _get_provider_name("google")
            assert result == "my-custom-provider"

    def test_returns_default_name_when_accepted(self):
        """Test that default name is used when user accepts default."""
        with patch("click.prompt") as mock_prompt:
            mock_prompt.return_value = "google-default"
            result = _get_provider_name("google")
            assert result == "google-default"

    def test_returns_none_when_empty(self):
        """Test that None is returned when user provides empty string."""
        with patch("click.prompt") as mock_prompt:
            mock_prompt.return_value = ""
            result = _get_provider_name("google")
            assert result is None

    def test_strips_whitespace_from_name(self):
        """Test that whitespace is stripped from provider name."""
        with patch("click.prompt") as mock_prompt:
            mock_prompt.return_value = "  my-provider  "
            result = _get_provider_name("google")
            assert result == "my-provider"


class TestRunLLMWizard:
    """Tests for run_llm_wizard main orchestration function."""

    @patch("docman.llm_wizard._select_provider")
    def test_cancelled_at_provider_selection(self, mock_select_provider):
        """Test wizard returns False when cancelled at provider selection."""
        mock_select_provider.return_value = None
        result = run_llm_wizard()
        assert result is False

    @patch("docman.llm_wizard._select_provider")
    @patch("docman.llm_wizard._get_endpoint")
    @patch("docman.llm_wizard._get_api_key")
    def test_cancelled_at_api_key_entry(
        self, mock_get_api_key, mock_get_endpoint, mock_select_provider
    ):
        """Test wizard returns False when cancelled at API key entry."""
        mock_select_provider.return_value = "openai"
        mock_get_endpoint.return_value = None
        mock_get_api_key.return_value = None

        result = run_llm_wizard()
        assert result is False

    @patch("docman.llm_wizard._select_provider")
    @patch("docman.llm_wizard._get_api_key")
    @patch("docman.llm_wizard.list_available_models")
    def test_returns_false_when_no_models_available(
        self, mock_list_models, mock_get_api_key, mock_select_provider
    ):
        """Test wizard returns False when no models are available."""
        mock_select_provider.return_value = "google"
        mock_get_api_key.return_value = "test-key"
        mock_list_models.return_value = []

        result = run_llm_wizard()
        assert result is False

    @patch("docman.llm_wizard._select_provider")
    @patch("docman.llm_wizard._get_api_key")
    @patch("docman.llm_wizard.list_available_models")
    def test_returns_false_on_unsupported_provider_error(
        self, mock_list_models, mock_get_api_key, mock_select_provider
    ):
        """Test wizard returns False when provider type is unsupported."""
        mock_select_provider.return_value = "google"
        mock_get_api_key.return_value = "test-key"
        mock_list_models.side_effect = ValueError("Unsupported provider type")

        result = run_llm_wizard()
        assert result is False

    @patch("docman.llm_wizard._select_provider")
    @patch("docman.llm_wizard._get_api_key")
    @patch("docman.llm_wizard.list_available_models")
    def test_returns_false_on_api_connection_error(
        self, mock_list_models, mock_get_api_key, mock_select_provider
    ):
        """Test wizard returns False when API connection fails."""
        mock_select_provider.return_value = "google"
        mock_get_api_key.return_value = "test-key"
        mock_list_models.side_effect = Exception("API connection failed")

        result = run_llm_wizard()
        assert result is False

    @patch("docman.llm_wizard._select_provider")
    @patch("docman.llm_wizard._get_api_key")
    @patch("docman.llm_wizard.list_available_models")
    @patch("docman.llm_wizard._select_model")
    def test_cancelled_at_model_selection(
        self, mock_select_model, mock_list_models, mock_get_api_key, mock_select_provider
    ):
        """Test wizard returns False when cancelled at model selection."""
        mock_select_provider.return_value = "google"
        mock_get_api_key.return_value = "test-key"
        mock_list_models.return_value = [
            {"name": "gemini-1.5-flash", "display_name": "Gemini 1.5 Flash"}
        ]
        mock_select_model.return_value = None

        result = run_llm_wizard()
        assert result is False

    @patch("docman.llm_wizard._select_provider")
    @patch("docman.llm_wizard._get_api_key")
    @patch("docman.llm_wizard.list_available_models")
    @patch("docman.llm_wizard._select_model")
    @patch("docman.llm_wizard._get_provider_name")
    def test_cancelled_at_provider_naming(
        self,
        mock_get_provider_name,
        mock_select_model,
        mock_list_models,
        mock_get_api_key,
        mock_select_provider,
    ):
        """Test wizard returns False when cancelled at provider naming."""
        mock_select_provider.return_value = "google"
        mock_get_api_key.return_value = "test-key"
        mock_list_models.return_value = [
            {"name": "gemini-1.5-flash", "display_name": "Gemini 1.5 Flash"}
        ]
        mock_select_model.return_value = "gemini-1.5-flash"
        mock_get_provider_name.return_value = None

        result = run_llm_wizard()
        assert result is False

    @patch("docman.llm_wizard._select_provider")
    @patch("docman.llm_wizard._get_api_key")
    @patch("docman.llm_wizard.list_available_models")
    @patch("docman.llm_wizard._select_model")
    @patch("docman.llm_wizard._get_provider_name")
    @patch("docman.llm_wizard.get_provider")
    def test_returns_false_on_connection_test_failure(
        self,
        mock_get_provider,
        mock_get_provider_name,
        mock_select_model,
        mock_list_models,
        mock_get_api_key,
        mock_select_provider,
    ):
        """Test wizard returns False when connection test fails."""
        mock_select_provider.return_value = "google"
        mock_get_api_key.return_value = "test-key"
        mock_list_models.return_value = [
            {"name": "gemini-1.5-flash", "display_name": "Gemini 1.5 Flash"}
        ]
        mock_select_model.return_value = "gemini-1.5-flash"
        mock_get_provider_name.return_value = "my-provider"

        mock_provider_instance = Mock()
        mock_provider_instance.test_connection.side_effect = Exception("Connection failed")
        mock_get_provider.return_value = mock_provider_instance

        result = run_llm_wizard()
        assert result is False

    @patch("docman.llm_wizard._select_provider")
    @patch("docman.llm_wizard._get_api_key")
    @patch("docman.llm_wizard.list_available_models")
    @patch("docman.llm_wizard._select_model")
    @patch("docman.llm_wizard._get_provider_name")
    @patch("docman.llm_wizard.get_provider")
    @patch("docman.llm_wizard.add_provider")
    def test_returns_false_on_save_failure(
        self,
        mock_add_provider,
        mock_get_provider,
        mock_get_provider_name,
        mock_select_model,
        mock_list_models,
        mock_get_api_key,
        mock_select_provider,
    ):
        """Test wizard returns False when saving configuration fails."""
        mock_select_provider.return_value = "google"
        mock_get_api_key.return_value = "test-key"
        mock_list_models.return_value = [
            {"name": "gemini-1.5-flash", "display_name": "Gemini 1.5 Flash"}
        ]
        mock_select_model.return_value = "gemini-1.5-flash"
        mock_get_provider_name.return_value = "my-provider"

        mock_provider_instance = Mock()
        mock_provider_instance.test_connection.return_value = None
        mock_get_provider.return_value = mock_provider_instance

        mock_add_provider.side_effect = Exception("Failed to save")

        result = run_llm_wizard()
        assert result is False

    @patch("docman.llm_wizard._select_provider")
    @patch("docman.llm_wizard._get_api_key")
    @patch("docman.llm_wizard.list_available_models")
    @patch("docman.llm_wizard._select_model")
    @patch("docman.llm_wizard._get_provider_name")
    @patch("docman.llm_wizard.get_provider")
    @patch("docman.llm_wizard.add_provider")
    def test_successful_google_provider_setup(
        self,
        mock_add_provider,
        mock_get_provider,
        mock_get_provider_name,
        mock_select_model,
        mock_list_models,
        mock_get_api_key,
        mock_select_provider,
    ):
        """Test successful completion of wizard for Google provider."""
        mock_select_provider.return_value = "google"
        mock_get_api_key.return_value = "test-key"
        mock_list_models.return_value = [
            {"name": "gemini-1.5-flash", "display_name": "Gemini 1.5 Flash"},
            {"name": "gemini-1.5-pro", "display_name": "Gemini 1.5 Pro"},
        ]
        mock_select_model.return_value = "gemini-1.5-flash"
        mock_get_provider_name.return_value = "my-google-provider"

        mock_provider_instance = Mock()
        mock_provider_instance.test_connection.return_value = None
        mock_get_provider.return_value = mock_provider_instance

        mock_add_provider.return_value = None

        result = run_llm_wizard()

        assert result is True
        mock_add_provider.assert_called_once()

        # Verify the config passed to add_provider
        call_args = mock_add_provider.call_args
        config = call_args[0][0]
        api_key = call_args[0][1]

        assert config.name == "my-google-provider"
        assert config.provider_type == "google"
        assert config.model == "gemini-1.5-flash"
        assert config.is_active is True
        assert api_key == "test-key"

    @patch("docman.llm_wizard._select_provider")
    @patch("docman.llm_wizard._get_endpoint")
    @patch("docman.llm_wizard._get_api_key")
    @patch("docman.llm_wizard.list_available_models")
    @patch("docman.llm_wizard._select_model")
    @patch("docman.llm_wizard._get_provider_name")
    @patch("docman.llm_wizard.get_provider")
    @patch("docman.llm_wizard.add_provider")
    def test_successful_openai_provider_setup_with_endpoint(
        self,
        mock_add_provider,
        mock_get_provider,
        mock_get_provider_name,
        mock_select_model,
        mock_list_models,
        mock_get_api_key,
        mock_get_endpoint,
        mock_select_provider,
    ):
        """Test successful completion of wizard for OpenAI with custom endpoint."""
        mock_select_provider.return_value = "openai"
        mock_get_endpoint.return_value = "http://localhost:1234/v1"
        mock_get_api_key.return_value = "sk-test"
        mock_list_models.return_value = [
            {"name": "gpt-4o", "display_name": "GPT-4o"},
        ]
        mock_select_model.return_value = "gpt-4o"
        mock_get_provider_name.return_value = "my-local-llm"

        mock_provider_instance = Mock()
        mock_provider_instance.test_connection.return_value = None
        mock_get_provider.return_value = mock_provider_instance

        mock_add_provider.return_value = None

        result = run_llm_wizard()

        assert result is True

        # Verify the config includes the custom endpoint
        call_args = mock_add_provider.call_args
        config = call_args[0][0]

        assert config.endpoint == "http://localhost:1234/v1"
        assert config.provider_type == "openai"

    @patch("docman.llm_wizard._select_provider")
    @patch("docman.llm_wizard._get_endpoint")
    @patch("docman.llm_wizard._get_api_key")
    @patch("docman.llm_wizard.list_available_models")
    @patch("docman.llm_wizard._select_model")
    @patch("docman.llm_wizard._get_provider_name")
    @patch("docman.llm_wizard.get_provider")
    @patch("docman.llm_wizard.add_provider")
    def test_successful_openai_provider_setup_without_endpoint(
        self,
        mock_add_provider,
        mock_get_provider,
        mock_get_provider_name,
        mock_select_model,
        mock_list_models,
        mock_get_api_key,
        mock_get_endpoint,
        mock_select_provider,
    ):
        """Test successful completion of wizard for OpenAI without custom endpoint."""
        mock_select_provider.return_value = "openai"
        mock_get_endpoint.return_value = None  # No custom endpoint
        mock_get_api_key.return_value = "sk-test"
        mock_list_models.return_value = [
            {"name": "gpt-4o", "display_name": "GPT-4o"},
        ]
        mock_select_model.return_value = "gpt-4o"
        mock_get_provider_name.return_value = "openai-default"

        mock_provider_instance = Mock()
        mock_provider_instance.test_connection.return_value = None
        mock_get_provider.return_value = mock_provider_instance

        mock_add_provider.return_value = None

        result = run_llm_wizard()

        assert result is True

        # Verify the config has None for endpoint
        call_args = mock_add_provider.call_args
        config = call_args[0][0]

        assert config.endpoint is None
