"""Comprehensive error handling tests for LLM providers."""

import pytest
from unittest.mock import Mock, patch

from docman.llm_config import ProviderConfig
from docman.llm_providers import (
    GoogleGeminiProvider,
    OpenAICompatibleProvider,
    GeminiSafetyBlockError,
    GeminiEmptyResponseError,
    OpenAIAPIError,
    OpenAIEmptyResponseError,
    get_provider,
    list_available_models,
)


class TestGoogleGeminiProviderErrors:
    """Test error handling for GoogleGeminiProvider."""

    @patch("google.generativeai.configure")
    @patch("google.generativeai.GenerativeModel")
    def test_handles_empty_response(self, mock_model_class, mock_configure):
        """Test handling of empty response from Gemini."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )

        mock_model_instance = Mock()
        mock_model_class.return_value = mock_model_instance
        provider = GoogleGeminiProvider(config, "fake-api-key")

        # Mock empty response
        mock_response = Mock()
        mock_response.text = ""
        mock_response.candidates = []
        mock_model_instance.generate_content = Mock(return_value=mock_response)

        with pytest.raises(GeminiEmptyResponseError, match="empty response with no candidates"):
            provider.generate_suggestions(
                "You are a document organizer",
                "Organize this file"
            )

    @patch("google.generativeai.configure")
    @patch("google.generativeai.GenerativeModel")
    def test_handles_safety_block_error(self, mock_model_class, mock_configure):
        """Test handling of safety filter block from Gemini."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )

        mock_model_instance = Mock()
        mock_model_class.return_value = mock_model_instance
        provider = GoogleGeminiProvider(config, "fake-api-key")

        # Mock safety blocked response
        mock_candidate = Mock()
        mock_candidate.finish_reason = "SAFETY"
        mock_response = Mock()
        mock_response.text = None
        mock_response.candidates = [mock_candidate]
        mock_model_instance.generate_content = Mock(return_value=mock_response)

        with pytest.raises(GeminiSafetyBlockError, match="safety filter"):
            provider.generate_suggestions(
                "You are a document organizer",
                "Organize this file"
            )

    @patch("google.generativeai.configure")
    @patch("google.generativeai.GenerativeModel")
    def test_handles_json_parse_error(self, mock_model_class, mock_configure):
        """Test handling of malformed JSON response."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )

        mock_model_instance = Mock()
        mock_model_class.return_value = mock_model_instance
        provider = GoogleGeminiProvider(config, "fake-api-key")

        # Mock response with invalid JSON
        mock_response = Mock()
        mock_response.text = "This is not valid JSON"
        mock_model_instance.generate_content = Mock(return_value=mock_response)

        with pytest.raises(Exception, match="Failed to parse JSON response"):
            provider.generate_suggestions(
                "You are a document organizer",
                "Organize this file"
            )

    @patch("google.generativeai.configure")
    @patch("google.generativeai.GenerativeModel")
    def test_test_connection_invalid_api_key(self, mock_model_class, mock_configure):
        """Test connection test with invalid API key."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )

        mock_model_instance = Mock()
        mock_model_class.return_value = mock_model_instance
        provider = GoogleGeminiProvider(config, "fake-api-key")

        # Mock API key error
        mock_model_instance.generate_content.side_effect = Exception("Invalid API key")

        with pytest.raises(Exception, match="Invalid API key"):
            provider.test_connection()

    @patch("google.generativeai.configure")
    @patch("google.generativeai.GenerativeModel")
    def test_test_connection_quota_exceeded(self, mock_model_class, mock_configure):
        """Test connection test with quota exceeded error."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )

        mock_model_instance = Mock()
        mock_model_class.return_value = mock_model_instance
        provider = GoogleGeminiProvider(config, "fake-api-key")

        # Mock quota error
        mock_model_instance.generate_content.side_effect = Exception("Quota exceeded")

        with pytest.raises(Exception, match="quota exceeded"):
            provider.test_connection()

    @patch("google.generativeai.configure")
    @patch("google.generativeai.GenerativeModel")
    def test_test_connection_network_error(self, mock_model_class, mock_configure):
        """Test connection test with network error."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )

        mock_model_instance = Mock()
        mock_model_class.return_value = mock_model_instance
        provider = GoogleGeminiProvider(config, "fake-api-key")

        # Mock network error
        mock_model_instance.generate_content.side_effect = Exception("Network connection failed")

        with pytest.raises(Exception, match="Network connection error"):
            provider.test_connection()

    @patch("google.generativeai.configure")
    @patch("google.generativeai.GenerativeModel")
    def test_test_connection_model_not_found(self, mock_model_class, mock_configure):
        """Test connection test with model not found error."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-nonexistent",
            is_active=True,
        )

        mock_model_instance = Mock()
        mock_model_class.return_value = mock_model_instance
        provider = GoogleGeminiProvider(config, "fake-api-key")

        # Mock model not found error
        mock_model_instance.generate_content.side_effect = Exception("Model not found: 404")

        with pytest.raises(Exception, match="not found"):
            provider.test_connection()

    @patch("google.generativeai.configure")
    def test_list_models_invalid_api_key(self, mock_configure):
        """Test listing models with invalid API key."""
        with patch("google.generativeai.list_models") as mock_list_models:
            mock_list_models.side_effect = Exception("Invalid API key")

            with pytest.raises(Exception, match="Invalid API key"):
                GoogleGeminiProvider.list_models("invalid-key")

    @patch("google.generativeai.configure")
    def test_list_models_network_error(self, mock_configure):
        """Test listing models with network error."""
        with patch("google.generativeai.list_models") as mock_list_models:
            mock_list_models.side_effect = Exception("Connection timeout")

            with pytest.raises(Exception, match="Failed to list models"):
                GoogleGeminiProvider.list_models("test-key")


class TestOpenAICompatibleProviderErrors:
    """Test error handling for OpenAICompatibleProvider."""

    @patch("openai.OpenAI")
    def test_handles_empty_response_no_choices(self, mock_openai_class):
        """Test handling of empty response with no choices."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="openai",
            model="gpt-4",
            is_active=True,
        )

        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        provider = OpenAICompatibleProvider(config, "fake-api-key")

        # Mock empty response
        mock_response = Mock()
        mock_response.choices = []
        mock_client.chat.completions.create = Mock(return_value=mock_response)

        with pytest.raises(OpenAIEmptyResponseError, match="no choices"):
            provider.generate_suggestions(
                "You are a document organizer",
                "Organize this file"
            )

    @patch("openai.OpenAI")
    def test_handles_empty_message_content(self, mock_openai_class):
        """Test handling of empty message content."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="openai",
            model="gpt-4",
            is_active=True,
        )

        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        provider = OpenAICompatibleProvider(config, "fake-api-key")

        # Mock response with empty content
        mock_message = Mock()
        mock_message.content = None
        mock_choice = Mock()
        mock_choice.message = mock_message
        mock_response = Mock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create = Mock(return_value=mock_response)

        with pytest.raises(OpenAIEmptyResponseError, match="empty message content"):
            provider.generate_suggestions(
                "You are a document organizer",
                "Organize this file"
            )

    @patch("openai.OpenAI")
    def test_handles_json_parse_error(self, mock_openai_class):
        """Test handling of malformed JSON response."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="openai",
            model="gpt-4",
            is_active=True,
        )

        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        provider = OpenAICompatibleProvider(config, "fake-api-key")

        # Mock response with invalid JSON
        mock_message = Mock()
        mock_message.content = "This is not valid JSON"
        mock_choice = Mock()
        mock_choice.message = mock_message
        mock_response = Mock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create = Mock(return_value=mock_response)

        with pytest.raises(Exception, match="Failed to parse JSON response"):
            provider.generate_suggestions(
                "You are a document organizer",
                "Organize this file"
            )

    @patch("openai.OpenAI")
    def test_handles_rate_limit_error(self, mock_openai_class):
        """Test handling of rate limit error."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="openai",
            model="gpt-4",
            is_active=True,
        )

        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        provider = OpenAICompatibleProvider(config, "fake-api-key")

        # Mock rate limit error
        mock_client.chat.completions.create.side_effect = Exception("Rate limit exceeded: 429")

        with pytest.raises(OpenAIAPIError, match="Rate limit exceeded"):
            provider.generate_suggestions(
                "You are a document organizer",
                "Organize this file"
            )

    @patch("openai.OpenAI")
    def test_handles_invalid_api_key_error(self, mock_openai_class):
        """Test handling of invalid API key error."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="openai",
            model="gpt-4",
            is_active=True,
        )

        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        provider = OpenAICompatibleProvider(config, "fake-api-key")

        # Mock invalid API key error
        mock_client.chat.completions.create.side_effect = Exception("Unauthorized: 401")

        with pytest.raises(OpenAIAPIError, match="Invalid API key"):
            provider.generate_suggestions(
                "You are a document organizer",
                "Organize this file"
            )

    @patch("openai.OpenAI")
    def test_handles_model_not_found_error(self, mock_openai_class):
        """Test handling of model not found error."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="openai",
            model="nonexistent-model",
            is_active=True,
        )

        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        provider = OpenAICompatibleProvider(config, "fake-api-key")

        # Mock model not found error
        mock_client.chat.completions.create.side_effect = Exception("Model not found: 404")

        with pytest.raises(OpenAIAPIError, match="not found"):
            provider.generate_suggestions(
                "You are a document organizer",
                "Organize this file"
            )

    @patch("openai.OpenAI")
    def test_handles_connection_error(self, mock_openai_class):
        """Test handling of connection error."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="openai",
            model="gpt-4",
            is_active=True,
        )

        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        provider = OpenAICompatibleProvider(config, "fake-api-key")

        # Mock connection error
        mock_client.chat.completions.create.side_effect = Exception("Connection timeout")

        with pytest.raises(OpenAIAPIError, match="Network connection error"):
            provider.generate_suggestions(
                "You are a document organizer",
                "Organize this file"
            )

    @patch("openai.OpenAI")
    def test_test_connection_invalid_api_key(self, mock_openai_class):
        """Test connection test with invalid API key."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="openai",
            model="gpt-4",
            is_active=True,
        )

        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        provider = OpenAICompatibleProvider(config, "fake-api-key")

        # Mock API key error
        mock_client.chat.completions.create.side_effect = Exception("Invalid API key: 401")

        with pytest.raises(Exception, match="Invalid API key"):
            provider.test_connection()

    @patch("openai.OpenAI")
    def test_test_connection_quota_exceeded(self, mock_openai_class):
        """Test connection test with quota exceeded error."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="openai",
            model="gpt-4",
            is_active=True,
        )

        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        provider = OpenAICompatibleProvider(config, "fake-api-key")

        # Mock quota error
        mock_client.chat.completions.create.side_effect = Exception("Rate limit: 429")

        with pytest.raises(Exception, match="quota exceeded"):
            provider.test_connection()

    @patch("openai.OpenAI")
    def test_test_connection_with_custom_endpoint(self, mock_openai_class):
        """Test connection test with custom endpoint error message."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="openai",
            model="gpt-4",
            endpoint="http://localhost:1234/v1",
            is_active=True,
        )

        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        provider = OpenAICompatibleProvider(config, "fake-api-key")

        # Mock connection error
        mock_client.chat.completions.create.side_effect = Exception("Connection refused")

        with pytest.raises(Exception, match="localhost:1234"):
            provider.test_connection()

    @patch("openai.OpenAI")
    def test_list_models_invalid_api_key(self, mock_openai_class):
        """Test listing models with invalid API key."""
        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        mock_client.models.list.side_effect = Exception("Unauthorized: 401")

        with pytest.raises(Exception, match="Invalid API key"):
            OpenAICompatibleProvider.list_models("invalid-key")

    @patch("openai.OpenAI")
    def test_list_models_connection_error(self, mock_openai_class):
        """Test listing models with connection error."""
        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        mock_client.models.list.side_effect = Exception("Connection refused")

        with pytest.raises(Exception, match="Could not connect"):
            OpenAICompatibleProvider.list_models("test-key", "http://localhost:1234/v1")


class TestFactoryFunctions:
    """Test factory functions for provider creation."""

    def test_get_provider_google(self):
        """Test get_provider returns GoogleGeminiProvider for google type."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )

        with patch("google.generativeai.configure"):
            with patch("google.generativeai.GenerativeModel"):
                provider = get_provider(config, "test-key")
                assert isinstance(provider, GoogleGeminiProvider)

    def test_get_provider_openai(self):
        """Test get_provider returns OpenAICompatibleProvider for openai type."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="openai",
            model="gpt-4",
            is_active=True,
        )

        with patch("openai.OpenAI"):
            provider = get_provider(config, "test-key")
            assert isinstance(provider, OpenAICompatibleProvider)

    def test_get_provider_unsupported_type(self):
        """Test get_provider raises ValueError for unsupported provider type."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="unsupported",
            model="some-model",
            is_active=True,
        )

        with pytest.raises(ValueError, match="Unsupported provider type"):
            get_provider(config, "test-key")

    def test_list_available_models_google(self):
        """Test list_available_models for google provider."""
        with patch("docman.llm_providers.GoogleGeminiProvider.list_models") as mock_list:
            mock_list.return_value = [{"name": "gemini-1.5-flash", "display_name": "Gemini 1.5 Flash"}]
            result = list_available_models("google", "test-key")
            assert len(result) == 1
            assert result[0]["name"] == "gemini-1.5-flash"

    def test_list_available_models_openai(self):
        """Test list_available_models for openai provider."""
        with patch("docman.llm_providers.OpenAICompatibleProvider.list_models") as mock_list:
            mock_list.return_value = [{"name": "gpt-4", "display_name": "GPT-4"}]
            result = list_available_models("openai", "test-key")
            assert len(result) == 1
            assert result[0]["name"] == "gpt-4"

    def test_list_available_models_unsupported_type(self):
        """Test list_available_models raises ValueError for unsupported provider type."""
        with pytest.raises(ValueError, match="Unsupported provider type"):
            list_available_models("unsupported", "test-key")
