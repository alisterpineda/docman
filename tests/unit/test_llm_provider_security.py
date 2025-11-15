"""
Unit tests for LLM provider security validation.

These tests verify that the Pydantic field validators are actually executed
when LLM providers parse responses, ensuring malicious paths are rejected.
"""

import json
import pytest
from unittest.mock import Mock, patch

from docman.llm_config import ProviderConfig
from docman.llm_providers import GoogleGeminiProvider, OpenAICompatibleProvider


@pytest.mark.unit
class TestGoogleGeminiProviderSecurity:
    """Test that GoogleGeminiProvider validates LLM responses."""

    @patch("google.generativeai.configure")
    @patch("google.generativeai.GenerativeModel")
    def test_rejects_parent_directory_traversal(self, mock_model_class, mock_configure):
        """Verify that parent directory traversal in responses is rejected."""
        # Setup mock config
        config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )

        # Mock the model instance
        mock_model_instance = Mock()
        mock_model_class.return_value = mock_model_instance

        # Create provider
        provider = GoogleGeminiProvider(config, "fake-api-key")

        # Mock the model to return malicious JSON
        mock_response = Mock()
        mock_response.text = json.dumps({
            "suggested_directory_path": "../../etc",
            "suggested_filename": "passwd",
            "reason": "Malicious suggestion"
        })
        mock_model_instance.generate_content = Mock(return_value=mock_response)

        # Call generate_suggestions and expect validation error
        with pytest.raises(Exception, match="validation failed"):
            provider.generate_suggestions(
                "You are a document organizer",
                "Organize this file"
            )

    @patch("google.generativeai.configure")
    @patch("google.generativeai.GenerativeModel")
    def test_rejects_absolute_paths(self, mock_model_class, mock_configure):
        """Verify that absolute paths in responses are rejected."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )

        mock_model_instance = Mock()
        mock_model_class.return_value = mock_model_instance
        provider = GoogleGeminiProvider(config, "fake-api-key")

        # Mock the model to return absolute path
        mock_response = Mock()
        mock_response.text = json.dumps({
            "suggested_directory_path": "/etc",
            "suggested_filename": "hosts",
            "reason": "Malicious suggestion"
        })
        mock_model_instance.generate_content = Mock(return_value=mock_response)

        # Call generate_suggestions and expect validation error
        with pytest.raises(Exception, match="validation failed"):
            provider.generate_suggestions(
                "You are a document organizer",
                "Organize this file"
            )

    @patch("google.generativeai.configure")
    @patch("google.generativeai.GenerativeModel")
    def test_accepts_safe_paths(self, mock_model_class, mock_configure):
        """Verify that safe paths in responses are accepted."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )

        mock_model_instance = Mock()
        mock_model_class.return_value = mock_model_instance
        provider = GoogleGeminiProvider(config, "fake-api-key")

        # Mock the model to return safe JSON
        mock_response = Mock()
        mock_response.text = json.dumps({
            "suggested_directory_path": "documents/reports",
            "suggested_filename": "annual_report.pdf",
            "reason": "Valid suggestion"
        })
        mock_model_instance.generate_content = Mock(return_value=mock_response)

        # Call generate_suggestions and expect success
        result = provider.generate_suggestions(
            "You are a document organizer",
            "Organize this file"
        )

        assert result["suggested_directory_path"] == "documents/reports"
        assert result["suggested_filename"] == "annual_report.pdf"


@pytest.mark.unit
class TestOpenAICompatibleProviderSecurity:
    """Test that OpenAICompatibleProvider validates LLM responses."""

    @patch("openai.OpenAI")
    def test_rejects_parent_directory_traversal(self, mock_openai_class):
        """Verify that parent directory traversal in responses is rejected."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="openai",
            model="gpt-4",
            is_active=True,
        )

        # Mock the OpenAI client
        mock_client = Mock()
        mock_openai_class.return_value = mock_client

        # Create provider
        provider = OpenAICompatibleProvider(config, "fake-api-key")

        # Mock the OpenAI response with malicious data
        mock_message = Mock()
        mock_message.content = json.dumps({
            "suggested_directory_path": "../../etc",
            "suggested_filename": "passwd",
            "reason": "Malicious suggestion"
        })
        mock_choice = Mock()
        mock_choice.message = mock_message
        mock_response = Mock()
        mock_response.choices = [mock_choice]

        mock_client.chat.completions.create = Mock(return_value=mock_response)

        # Call generate_suggestions and expect validation error
        with pytest.raises(Exception, match="validation failed"):
            provider.generate_suggestions(
                "You are a document organizer",
                "Organize this file"
            )

    @patch("openai.OpenAI")
    def test_rejects_absolute_paths(self, mock_openai_class):
        """Verify that absolute paths in responses are rejected."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="openai",
            model="gpt-4",
            is_active=True,
        )

        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        provider = OpenAICompatibleProvider(config, "fake-api-key")

        # Mock the OpenAI response with absolute path
        mock_message = Mock()
        mock_message.content = json.dumps({
            "suggested_directory_path": "/etc",
            "suggested_filename": "hosts",
            "reason": "Malicious suggestion"
        })
        mock_choice = Mock()
        mock_choice.message = mock_message
        mock_response = Mock()
        mock_response.choices = [mock_choice]

        mock_client.chat.completions.create = Mock(return_value=mock_response)

        # Call generate_suggestions and expect validation error
        with pytest.raises(Exception, match="validation failed"):
            provider.generate_suggestions(
                "You are a document organizer",
                "Organize this file"
            )

    @patch("openai.OpenAI")
    def test_accepts_safe_paths(self, mock_openai_class):
        """Verify that safe paths in responses are accepted."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="openai",
            model="gpt-4",
            is_active=True,
        )

        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        provider = OpenAICompatibleProvider(config, "fake-api-key")

        # Mock the OpenAI response with safe data
        mock_message = Mock()
        mock_message.content = json.dumps({
            "suggested_directory_path": "documents/reports",
            "suggested_filename": "annual_report.pdf",
            "reason": "Valid suggestion"
        })
        mock_choice = Mock()
        mock_choice.message = mock_message
        mock_response = Mock()
        mock_response.choices = [mock_choice]

        mock_client.chat.completions.create = Mock(return_value=mock_response)

        # Call generate_suggestions and expect success
        result = provider.generate_suggestions(
            "You are a document organizer",
            "Organize this file"
        )

        assert result["suggested_directory_path"] == "documents/reports"
        assert result["suggested_filename"] == "annual_report.pdf"

    @patch("openai.OpenAI")
    def test_handles_markdown_code_blocks_with_validation(self, mock_openai_class):
        """Verify validation works even when response is in markdown code blocks."""
        config = ProviderConfig(
            name="test-provider",
            provider_type="openai",
            model="gpt-4",
            is_active=True,
        )

        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        provider = OpenAICompatibleProvider(config, "fake-api-key")

        # Mock response with markdown code block containing malicious path
        mock_message = Mock()
        mock_message.content = """```json
{
    "suggested_directory_path": "../../.ssh",
    "suggested_filename": "id_rsa",
    "reason": "Malicious suggestion"
}
```"""
        mock_choice = Mock()
        mock_choice.message = mock_message
        mock_response = Mock()
        mock_response.choices = [mock_choice]

        mock_client.chat.completions.create = Mock(return_value=mock_response)

        # Call generate_suggestions and expect validation error
        with pytest.raises(Exception, match="validation failed"):
            provider.generate_suggestions(
                "You are a document organizer",
                "Organize this file"
            )
