"""LLM provider implementations for document organization suggestions.

This module provides an abstract interface for LLM providers and concrete
implementations for various LLM services (Google Gemini, Anthropic Claude, etc.).
"""

import json
from abc import ABC, abstractmethod
from typing import Any

import google.generativeai as genai
from openai import OpenAI
from pydantic import BaseModel, field_validator

from docman.llm_config import ProviderConfig


class OrganizationSuggestion(BaseModel):
    """Pydantic model for document organization suggestions.

    This model is used for structured output from LLM providers that support it.
    It ensures the response matches the expected schema.
    """

    suggested_directory_path: str
    suggested_filename: str
    reason: str
    confidence: float

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        """Validate that confidence is between 0.0 and 1.0."""
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {v}")
        return v


class GeminiSafetyBlockError(Exception):
    """Raised when Gemini blocks a response due to safety filters."""
    pass


class GeminiEmptyResponseError(Exception):
    """Raised when Gemini returns an empty response."""
    pass


class OpenAIAPIError(Exception):
    """Raised when OpenAI API returns an error."""
    pass


class OpenAIEmptyResponseError(Exception):
    """Raised when OpenAI returns an empty response."""
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

    @property
    def supports_structured_output(self) -> bool:
        """Indicates if this provider supports native structured output.

        Returns:
            True if the provider supports structured output (e.g., response schemas),
            False otherwise. Default is False for maximum compatibility.
        """
        return False

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

        # Configure structured output using Pydantic model
        generation_config = genai.GenerationConfig(
            response_mime_type="application/json",
            response_schema=OrganizationSuggestion,
        )

        self.model = genai.GenerativeModel(
            config.model,
            generation_config=generation_config,
        )

    @property
    def supports_structured_output(self) -> bool:
        """Google Gemini supports structured output via response schemas."""
        return True

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

        With structured output enabled, the API guarantees the response matches
        the OrganizationSuggestion schema.

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
            # Generate response with structured output
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

            # Parse JSON response (API enforces schema via structured output)
            data = json.loads(response.text)

            # Validate and return as dictionary
            return {
                "suggested_directory_path": str(data["suggested_directory_path"]),
                "suggested_filename": str(data["suggested_filename"]),
                "reason": str(data["reason"]),
                "confidence": float(data["confidence"]),
            }

        except (GeminiSafetyBlockError, GeminiEmptyResponseError):
            # Re-raise our custom exceptions without wrapping
            raise
        except json.JSONDecodeError as e:
            raise Exception(f"Failed to parse JSON response: {str(e)}") from e
        except KeyError as e:
            raise Exception(f"Missing required field in response: {str(e)}") from e
        except (ValueError, TypeError) as e:
            raise Exception(f"Invalid field type in response: {str(e)}") from e
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


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI-compatible LLM provider implementation.

    This provider works with:
    - OpenAI's official API
    - OpenAI-compatible APIs (e.g., LM Studio, text-generation-webui, vLLM)
    - Any server implementing the OpenAI chat completions API
    """

    def __init__(self, config: ProviderConfig, api_key: str):
        """Initialize OpenAI-compatible provider.

        Args:
            config: Provider configuration with optional custom endpoint.
            api_key: OpenAI API key (can be a dummy value for local servers).
        """
        super().__init__(config, api_key)

        # Configure OpenAI client with custom endpoint if provided
        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if config.endpoint:
            client_kwargs["base_url"] = config.endpoint

        self.client = OpenAI(**client_kwargs)

        # Only use JSON schema mode for official OpenAI API
        # Custom endpoints (LM Studio, vLLM, etc.) don't support it
        self._use_json_schema = config.endpoint is None

    @property
    def supports_structured_output(self) -> bool:
        """Only OpenAI's official API supports JSON schema structured output.

        Custom endpoints (LM Studio, vLLM, etc.) fall back to regular JSON mode
        where the system prompt guides the LLM to output valid JSON.
        """
        return self._use_json_schema

    @staticmethod
    def list_models(api_key: str, endpoint: str | None = None) -> list[dict[str, str]]:
        """List available OpenAI-compatible models.

        Args:
            api_key: OpenAI API key.
            endpoint: Optional custom endpoint URL for OpenAI-compatible servers.

        Returns:
            List of model dictionaries with 'name' and 'display_name' keys.

        Raises:
            Exception: If API call fails.
        """
        try:
            client_kwargs: dict[str, Any] = {"api_key": api_key}
            if endpoint:
                client_kwargs["base_url"] = endpoint

            client = OpenAI(**client_kwargs)

            # List models using OpenAI API
            models_response = client.models.list()
            models = []

            for model in models_response.data:
                models.append(
                    {
                        "name": model.id,
                        "display_name": model.id,
                        "description": f"Created: {model.created}" if hasattr(model, 'created') else "",
                    }
                )

            return models
        except Exception as e:
            error_msg = str(e).lower()
            if "api key" in error_msg or "invalid" in error_msg or "unauthorized" in error_msg or "401" in error_msg:
                raise Exception(
                    "Invalid API key. Please check your API key and try again."
                ) from e
            elif "connection" in error_msg or "refused" in error_msg or "unreachable" in error_msg:
                endpoint_info = f" at {endpoint}" if endpoint else ""
                raise Exception(
                    f"Could not connect to server{endpoint_info}. "
                    "Please check the endpoint URL and ensure the server is running."
                ) from e
            else:
                raise Exception(f"Failed to list models: {str(e)}") from e

    def generate_suggestions(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Generate file organization suggestions using OpenAI-compatible API.

        For OpenAI's official API, uses JSON schema mode for guaranteed structure.
        For custom endpoints (LM Studio, vLLM, etc.), uses regular JSON mode
        and relies on the system prompt to guide JSON output.

        Args:
            system_prompt: Static system prompt defining the LLM's task.
            user_prompt: Dynamic user prompt with document-specific information.

        Returns:
            Dictionary with organization suggestions.

        Raises:
            OpenAIAPIError: If API returns an error.
            OpenAIEmptyResponseError: If response is empty.
            Exception: If API call fails or response cannot be parsed.
        """
        try:
            # Prepare request parameters
            request_params: dict[str, Any] = {
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.7,
            }

            # Use JSON schema mode only for official OpenAI API
            if self._use_json_schema:
                # Convert Pydantic model to JSON schema for OpenAI
                schema = OrganizationSuggestion.model_json_schema()
                request_params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "organization_suggestion",
                        "schema": schema,
                        "strict": True,
                    },
                }
            else:
                # For custom endpoints, use regular JSON mode
                # The system prompt will guide the LLM to output valid JSON
                request_params["response_format"] = {"type": "json_object"}

            # Make API request
            response = self.client.chat.completions.create(**request_params)

            # Extract response content
            if not response.choices:
                raise OpenAIEmptyResponseError("OpenAI returned empty response with no choices")

            message = response.choices[0].message
            if not message.content:
                raise OpenAIEmptyResponseError("OpenAI returned empty message content")

            # Parse JSON response
            data = json.loads(message.content)

            # Validate and return as dictionary
            return {
                "suggested_directory_path": str(data["suggested_directory_path"]),
                "suggested_filename": str(data["suggested_filename"]),
                "reason": str(data["reason"]),
                "confidence": float(data["confidence"]),
            }

        except (OpenAIAPIError, OpenAIEmptyResponseError):
            # Re-raise our custom exceptions without wrapping
            raise
        except json.JSONDecodeError as e:
            raise Exception(f"Failed to parse JSON response: {str(e)}") from e
        except KeyError as e:
            raise Exception(f"Missing required field in response: {str(e)}") from e
        except (ValueError, TypeError) as e:
            raise Exception(f"Invalid field type in response: {str(e)}") from e
        except Exception as e:
            # Handle OpenAI-specific errors
            error_msg = str(e).lower()
            if "api key" in error_msg or "unauthorized" in error_msg or "401" in error_msg:
                raise OpenAIAPIError(
                    "Invalid API key. Please check your API key and try again."
                ) from e
            elif "rate limit" in error_msg or "429" in error_msg:
                raise OpenAIAPIError(
                    "Rate limit exceeded. Please try again later."
                ) from e
            elif "not found" in error_msg or "404" in error_msg:
                raise OpenAIAPIError(
                    f"Model '{self.config.model}' not found. "
                    "Please check the model name and try again."
                ) from e
            elif "connection" in error_msg or "timeout" in error_msg:
                raise OpenAIAPIError(
                    "Network connection error. Please check your connection and server availability."
                ) from e
            else:
                raise Exception(f"Failed to generate suggestions: {str(e)}") from e

    def test_connection(self) -> bool:
        """Test connection to OpenAI-compatible API.

        Returns:
            True if connection successful.

        Raises:
            Exception: If connection fails, with detailed error message.
        """
        try:
            # Try a simple chat completion to verify API key and connectivity
            response = self.client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "Test connection. Respond with 'OK'."},
                ],
                max_tokens=10,
            )

            if not response.choices or not response.choices[0].message.content:
                raise Exception("API returned empty response")

            return True
        except Exception as e:
            # Provide more specific error messages based on common error types
            error_msg = str(e).lower()

            if "api key" in error_msg or "invalid" in error_msg or "unauthorized" in error_msg or "401" in error_msg:
                raise Exception(
                    "Invalid API key. Please check your API key and try again."
                ) from e
            elif "quota" in error_msg or "rate limit" in error_msg or "429" in error_msg:
                raise Exception(
                    "API quota exceeded or rate limit reached. "
                    "Please try again later."
                ) from e
            elif "connection" in error_msg or "timeout" in error_msg or "refused" in error_msg or "unreachable" in error_msg:
                endpoint_info = f" at {self.config.endpoint}" if self.config.endpoint else ""
                raise Exception(
                    f"Network connection error{endpoint_info}. "
                    "Please check your connection and ensure the server is running."
                ) from e
            elif "not found" in error_msg or "404" in error_msg:
                raise Exception(
                    f"Model '{self.config.model}' not found. "
                    "Please check the model name and try again."
                ) from e
            else:
                # Generic error with original message
                raise Exception(f"Connection test failed: {str(e)}") from e


def list_available_models(provider_type: str, api_key: str, endpoint: str | None = None) -> list[dict[str, str]]:
    """List available models for a given provider.

    Args:
        provider_type: Type of provider (e.g., "google", "anthropic", "openai")
        api_key: API key for the provider.
        endpoint: Optional custom endpoint URL (for OpenAI-compatible servers).

    Returns:
        List of model dictionaries with 'name', 'display_name', and 'description' keys.

    Raises:
        ValueError: If provider_type is not supported.
        Exception: If API call fails.
    """
    if provider_type == "google":
        return GoogleGeminiProvider.list_models(api_key)
    elif provider_type == "openai":
        return OpenAICompatibleProvider.list_models(api_key, endpoint)
    # Future providers can be added here:
    # elif provider_type == "anthropic":
    #     return AnthropicClaudeProvider.list_models(api_key)
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
    elif config.provider_type == "openai":
        return OpenAICompatibleProvider(config, api_key)
    # Future providers can be added here:
    # elif config.provider_type == "anthropic":
    #     return AnthropicClaudeProvider(config, api_key)
    else:
        raise ValueError(f"Unsupported provider type: {config.provider_type}")
