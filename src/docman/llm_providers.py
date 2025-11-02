"""LLM provider implementations for document organization suggestions.

This module provides an abstract interface for LLM providers and concrete
implementations for various LLM services (Google Gemini, Anthropic Claude, etc.).
"""

import json
from abc import ABC, abstractmethod
from typing import Any

import google.generativeai as genai

from docman.llm_config import ProviderConfig


class GeminiSafetyBlockError(Exception):
    """Raised when Gemini blocks a response due to safety filters."""
    pass


class GeminiEmptyResponseError(Exception):
    """Raised when Gemini returns an empty response."""
    pass


class LLMProvider(ABC):
    """Abstract base class for LLM providers.

    All LLM provider implementations should inherit from this class and implement
    the required methods.
    """

    def __init__(self, config: ProviderConfig, api_key: str):
        """Initialize the LLM provider.

        Args:
            config: Provider configuration including model and endpoint details.
            api_key: API key for authenticating with the provider.
        """
        self.config = config
        self.api_key = api_key

    @abstractmethod
    def generate_suggestions(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Generate file organization suggestions for a document.

        Args:
            system_prompt: Static system prompt defining the LLM's task.
            user_prompt: Dynamic user prompt with document-specific information.

        Returns:
            Dictionary with keys:
                - suggested_directory_path: str - Suggested directory path
                - suggested_filename: str - Suggested filename
                - reason: str - Explanation for the suggestion
                - confidence: float - Confidence score between 0.0 and 1.0
        """
        pass

    @abstractmethod
    def test_connection(self) -> bool:
        """Test the connection to the LLM API.

        Returns:
            True if connection successful.

        Raises:
            Exception: If connection fails, with detailed error message.
        """
        pass


class GoogleGeminiProvider(LLMProvider):
    """Google Gemini LLM provider implementation."""

    def __init__(self, config: ProviderConfig, api_key: str):
        """Initialize Google Gemini provider.

        Args:
            config: Provider configuration.
            api_key: Google AI API key.
        """
        super().__init__(config, api_key)
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(config.model)

    @staticmethod
    def list_models(api_key: str) -> list[dict[str, str]]:
        """List available Google Gemini models.

        Args:
            api_key: Google AI API key.

        Returns:
            List of model dictionaries with 'name' and 'display_name' keys.

        Raises:
            Exception: If API call fails.
        """
        try:
            genai.configure(api_key=api_key)
            models = []

            # Get all models and filter for generative models
            for model in genai.list_models():
                # Only include models that support generateContent
                if "generateContent" in model.supported_generation_methods:
                    # Extract model name (remove "models/" prefix if present)
                    model_name = model.name
                    if model_name.startswith("models/"):
                        model_name = model_name[7:]

                    models.append(
                        {
                            "name": model_name,
                            "display_name": model.display_name or model_name,
                            "description": model.description or "",
                        }
                    )

            return models
        except Exception as e:
            error_msg = str(e).lower()
            if "api key" in error_msg or "invalid" in error_msg or "unauthorized" in error_msg:
                raise Exception(
                    "Invalid API key. Please check your API key and try again."
                ) from e
            else:
                raise Exception(f"Failed to list models: {str(e)}") from e

    def generate_suggestions(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Generate file organization suggestions using Google Gemini.

        Args:
            system_prompt: Static system prompt defining the LLM's task.
            user_prompt: Dynamic user prompt with document-specific information.

        Returns:
            Dictionary with organization suggestions.

        Raises:
            GeminiSafetyBlockError: If response is blocked by safety filters.
            GeminiEmptyResponseError: If response is empty.
            Exception: If API call fails or response cannot be parsed.
        """
        # Combine system and user prompts
        combined_prompt = f"{system_prompt}\n\n{user_prompt}"

        try:
            # Generate response
            response = self.model.generate_content(combined_prompt)

            # Normalize response - check if response.text exists and is non-empty
            if not hasattr(response, 'text') or not response.text:
                # Check candidates for blocked or empty responses
                if hasattr(response, 'candidates') and response.candidates:
                    candidate = response.candidates[0]

                    # Check finish_reason for blocking
                    if hasattr(candidate, 'finish_reason'):
                        finish_reason = str(candidate.finish_reason)

                        # Safety filter blocked the response
                        if 'SAFETY' in finish_reason:
                            raise GeminiSafetyBlockError(
                                f"Gemini blocked response (safety filter): {finish_reason}"
                            )

                        # Other blocking reasons
                        if finish_reason not in ['STOP', 'FinishReason.STOP']:
                            raise GeminiEmptyResponseError(
                                f"Gemini returned empty response (finish_reason: {finish_reason})"
                            )

                # No candidates or finish_reason - generic empty response
                raise GeminiEmptyResponseError(
                    "Gemini returned empty response with no candidates"
                )

            # Parse the response
            return self._parse_response(response.text)

        except (GeminiSafetyBlockError, GeminiEmptyResponseError):
            # Re-raise our custom exceptions without wrapping
            raise
        except Exception as e:
            raise Exception(f"Failed to generate suggestions: {str(e)}") from e

    def test_connection(self) -> bool:
        """Test connection to Google Gemini API.

        Returns:
            True if connection successful.

        Raises:
            Exception: If connection fails, with detailed error message.
        """
        try:
            # Try a simple generation to verify API key and connectivity
            response = self.model.generate_content("Test connection. Respond with 'OK'.")
            if not response.text:
                raise Exception("API returned empty response")
            return True
        except Exception as e:
            # Provide more specific error messages based on common error types
            error_msg = str(e).lower()

            if "api key" in error_msg or "invalid" in error_msg or "unauthorized" in error_msg:
                raise Exception(
                    "Invalid API key. Please check your API key and try again. "
                    "Get a valid key at: https://aistudio.google.com/app/apikey"
                ) from e
            elif "quota" in error_msg or "rate limit" in error_msg:
                raise Exception(
                    "API quota exceeded or rate limit reached. "
                    "Please try again later or check your quota at Google AI Studio."
                ) from e
            elif "network" in error_msg or "connection" in error_msg or "timeout" in error_msg:
                raise Exception(
                    "Network connection error. Please check your internet connection and try again."
                ) from e
            elif "not found" in error_msg or "404" in error_msg:
                raise Exception(
                    f"Model '{self.config.model}' not found. "
                    "Please check the model name and try again."
                ) from e
            else:
                # Generic error with original message
                raise Exception(f"Connection test failed: {str(e)}") from e


    def _parse_response(self, response_text: str) -> dict[str, Any]:
        """Parse the LLM response into structured data.

        Args:
            response_text: Raw text response from the LLM.

        Returns:
            Parsed dictionary with suggestion fields.

        Raises:
            ValueError: If response cannot be parsed or is missing required fields.
        """
        # Clean up the response (remove markdown code blocks if present)
        cleaned_text = response_text.strip()
        if cleaned_text.startswith("```json"):
            cleaned_text = cleaned_text[7:]  # Remove ```json
        if cleaned_text.startswith("```"):
            cleaned_text = cleaned_text[3:]  # Remove ```
        if cleaned_text.endswith("```"):
            cleaned_text = cleaned_text[:-3]  # Remove trailing ```
        cleaned_text = cleaned_text.strip()

        try:
            data = json.loads(cleaned_text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON response: {str(e)}") from e

        # Validate required fields
        required_fields = ["suggested_directory_path", "suggested_filename", "reason", "confidence"]
        for field in required_fields:
            if field not in data:
                raise ValueError(f"Missing required field: {field}")

        # Validate confidence is between 0 and 1
        confidence = float(data["confidence"])
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {confidence}")

        return {
            "suggested_directory_path": str(data["suggested_directory_path"]),
            "suggested_filename": str(data["suggested_filename"]),
            "reason": str(data["reason"]),
            "confidence": confidence,
        }


def list_available_models(provider_type: str, api_key: str) -> list[dict[str, str]]:
    """List available models for a given provider.

    Args:
        provider_type: Type of provider (e.g., "google", "anthropic", "openai")
        api_key: API key for the provider.

    Returns:
        List of model dictionaries with 'name', 'display_name', and 'description' keys.

    Raises:
        ValueError: If provider_type is not supported.
        Exception: If API call fails.
    """
    if provider_type == "google":
        return GoogleGeminiProvider.list_models(api_key)
    # Future providers can be added here:
    # elif provider_type == "anthropic":
    #     return AnthropicClaudeProvider.list_models(api_key)
    # elif provider_type == "openai":
    #     return OpenAIProvider.list_models(api_key)
    else:
        raise ValueError(f"Unsupported provider type: {provider_type}")


def get_provider(config: ProviderConfig, api_key: str) -> LLMProvider:
    """Factory function to create an LLM provider instance.

    Args:
        config: Provider configuration.
        api_key: API key for the provider.

    Returns:
        Instance of the appropriate LLM provider.

    Raises:
        ValueError: If provider_type is not supported.
    """
    if config.provider_type == "google":
        return GoogleGeminiProvider(config, api_key)
    # Future providers can be added here:
    # elif config.provider_type == "anthropic":
    #     return AnthropicClaudeProvider(config, api_key)
    # elif config.provider_type == "openai":
    #     return OpenAIProvider(config, api_key)
    else:
        raise ValueError(f"Unsupported provider type: {config.provider_type}")
