"""LLM provider implementations for document organization suggestions.

This module provides an abstract interface for LLM providers and concrete
implementations for various LLM services (Google Gemini, Anthropic Claude, etc.).
"""

import json
import re
from abc import ABC, abstractmethod
from typing import Any

import google.generativeai as genai
import torch
from pydantic import BaseModel, field_validator
from transformers import AutoModelForCausalLM, AutoTokenizer

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


class TransformersProvider(LLMProvider):
    """Local LLM provider using HuggingFace Transformers library."""

    def __init__(self, config: ProviderConfig, api_key: str = ""):
        """Initialize Transformers provider.

        Args:
            config: Provider configuration.
            api_key: Not used for local models, but kept for interface compatibility.
        """
        super().__init__(config, api_key)
        self.model = None
        self.tokenizer = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

    def _load_model(self) -> None:
        """Load the model and tokenizer if not already loaded."""
        if self.model is None or self.tokenizer is None:
            # Load tokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.config.model,
                trust_remote_code=True,
            )

            # Load model
            self.model = AutoModelForCausalLM.from_pretrained(
                self.config.model,
                torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
                device_map="auto" if self.device == "cuda" else None,
                trust_remote_code=True,
            )

            if self.device == "cpu":
                self.model = self.model.to(self.device)

    @property
    def supports_structured_output(self) -> bool:
        """Local models typically don't support native structured output."""
        return False

    @staticmethod
    def list_models(api_key: str = "") -> list[dict[str, str]]:
        """List recommended local models.

        Args:
            api_key: Not used for local models.

        Returns:
            List of recommended model configurations.
        """
        # Return a curated list of recommended local models
        return [
            {
                "name": "google/gemma-2-2b-it",
                "display_name": "Gemma 2 2B (Instruct)",
                "description": "Small, efficient instruction-tuned model from Google",
            },
            {
                "name": "google/gemma-2-9b-it",
                "display_name": "Gemma 2 9B (Instruct)",
                "description": "Larger instruction-tuned model with better performance",
            },
            {
                "name": "microsoft/Phi-3-mini-4k-instruct",
                "display_name": "Phi-3 Mini (4K context)",
                "description": "Microsoft's efficient 3.8B parameter model",
            },
            {
                "name": "meta-llama/Llama-3.2-3B-Instruct",
                "display_name": "Llama 3.2 3B (Instruct)",
                "description": "Meta's compact instruction-tuned model",
            },
        ]

    def generate_suggestions(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Generate file organization suggestions using a local LLM.

        Args:
            system_prompt: Static system prompt defining the LLM's task.
            user_prompt: Dynamic user prompt with document-specific information.

        Returns:
            Dictionary with organization suggestions.

        Raises:
            Exception: If model loading, generation, or parsing fails.
        """
        try:
            # Load model if not already loaded
            self._load_model()

            # Combine prompts
            combined_prompt = f"{system_prompt}\n\n{user_prompt}"

            # Tokenize input
            inputs = self.tokenizer(
                combined_prompt,
                return_tensors="pt",
                truncation=True,
                max_length=2048,
            ).to(self.device)

            # Generate response
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=512,
                    temperature=0.7,
                    top_p=0.9,
                    do_sample=True,
                    pad_token_id=self.tokenizer.eos_token_id,
                )

            # Decode response
            response_text = self.tokenizer.decode(outputs[0], skip_special_tokens=True)

            # Extract the generated part (remove the prompt)
            if combined_prompt in response_text:
                response_text = response_text[len(combined_prompt):].strip()

            # Try to extract JSON from the response
            json_data = self._extract_json(response_text)

            if not json_data:
                raise Exception("Failed to extract valid JSON from model response")

            # Validate and return as dictionary
            return {
                "suggested_directory_path": str(json_data["suggested_directory_path"]),
                "suggested_filename": str(json_data["suggested_filename"]),
                "reason": str(json_data["reason"]),
                "confidence": float(json_data["confidence"]),
            }

        except KeyError as e:
            raise Exception(f"Missing required field in response: {str(e)}") from e
        except (ValueError, TypeError) as e:
            raise Exception(f"Invalid field type in response: {str(e)}") from e
        except Exception as e:
            raise Exception(f"Failed to generate suggestions: {str(e)}") from e

    def _extract_json(self, text: str) -> dict[str, Any] | None:
        """Extract JSON object from text that may contain markdown or other content.

        Args:
            text: Text that may contain JSON, possibly in markdown code blocks.

        Returns:
            Parsed JSON dictionary, or None if no valid JSON found.
        """
        # Try to find JSON in markdown code blocks first
        json_block_pattern = r"```(?:json)?\s*(\{.*?\})\s*```"
        matches = re.findall(json_block_pattern, text, re.DOTALL)

        for match in matches:
            try:
                return json.loads(match)
            except json.JSONDecodeError:
                continue

        # Try to find raw JSON object
        json_pattern = r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
        matches = re.findall(json_pattern, text, re.DOTALL)

        for match in matches:
            try:
                data = json.loads(match)
                # Verify it has the expected keys
                if all(
                    key in data
                    for key in [
                        "suggested_directory_path",
                        "suggested_filename",
                        "reason",
                        "confidence",
                    ]
                ):
                    return data
            except json.JSONDecodeError:
                continue

        return None

    def test_connection(self) -> bool:
        """Test that the local model can be loaded and used.

        Returns:
            True if model loads successfully.

        Raises:
            Exception: If model loading fails, with detailed error message.
        """
        try:
            # Try to load the model
            self._load_model()

            # Try a simple generation to verify it works
            test_input = "Hello, this is a test."
            inputs = self.tokenizer(test_input, return_tensors="pt").to(self.device)

            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=10,
                    pad_token_id=self.tokenizer.eos_token_id,
                )

            # If we got here, the model works
            return True

        except Exception as e:
            error_msg = str(e).lower()

            if "out of memory" in error_msg or "oom" in error_msg:
                raise Exception(
                    f"Model '{self.config.model}' is too large for available memory. "
                    "Try a smaller model or ensure you have enough RAM/VRAM."
                ) from e
            elif "not found" in error_msg or "does not exist" in error_msg:
                raise Exception(
                    f"Model '{self.config.model}' not found. "
                    "The model may need to be downloaded from HuggingFace first."
                ) from e
            elif "connection" in error_msg or "timeout" in error_msg:
                raise Exception(
                    "Network connection error. Please check your internet connection "
                    "(required for first-time model download)."
                ) from e
            else:
                raise Exception(f"Model loading test failed: {str(e)}") from e


def list_available_models(provider_type: str, api_key: str = "") -> list[dict[str, str]]:
    """List available models for a given provider.

    Args:
        provider_type: Type of provider (e.g., "google", "local", "anthropic", "openai")
        api_key: API key for the provider (not needed for local models).

    Returns:
        List of model dictionaries with 'name', 'display_name', and 'description' keys.

    Raises:
        ValueError: If provider_type is not supported.
        Exception: If API call fails.
    """
    if provider_type == "google":
        return GoogleGeminiProvider.list_models(api_key)
    elif provider_type == "local":
        return TransformersProvider.list_models(api_key)
    # Future providers can be added here:
    # elif provider_type == "anthropic":
    #     return AnthropicClaudeProvider.list_models(api_key)
    # elif provider_type == "openai":
    #     return OpenAIProvider.list_models(api_key)
    else:
        raise ValueError(f"Unsupported provider type: {provider_type}")


def get_provider(config: ProviderConfig, api_key: str = "") -> LLMProvider:
    """Factory function to create an LLM provider instance.

    Args:
        config: Provider configuration.
        api_key: API key for the provider (not needed for local models).

    Returns:
        Instance of the appropriate LLM provider.

    Raises:
        ValueError: If provider_type is not supported.
    """
    if config.provider_type == "google":
        return GoogleGeminiProvider(config, api_key)
    elif config.provider_type == "local":
        return TransformersProvider(config, api_key)
    # Future providers can be added here:
    # elif config.provider_type == "anthropic":
    #     return AnthropicClaudeProvider(config, api_key)
    # elif config.provider_type == "openai":
    #     return OpenAIProvider(config, api_key)
    else:
        raise ValueError(f"Unsupported provider type: {config.provider_type}")
