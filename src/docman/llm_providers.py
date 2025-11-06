"""LLM provider implementations for document organization suggestions.

This module provides an abstract interface for LLM providers and concrete
implementations for various LLM services (Google Gemini, Anthropic Claude, etc.).
"""

import json
import re
from abc import ABC, abstractmethod
from typing import Any

import google.generativeai as genai
from pydantic import BaseModel, ValidationError, field_validator

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


def extract_json_from_text(text: str) -> dict[str, Any]:
    """Extract and parse JSON from free-form text output.

    This utility handles common cases where LLMs return JSON embedded in markdown
    code blocks or surrounded by explanatory text.

    Args:
        text: Raw text output from an LLM that may contain JSON.

    Returns:
        Parsed JSON as a dictionary.

    Raises:
        json.JSONDecodeError: If no valid JSON could be extracted.
        ValueError: If multiple JSON blocks are found or JSON is invalid.
    """
    # Strip whitespace
    text = text.strip()

    # Try parsing directly first (fastest path)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON in markdown code blocks (```json ... ``` or ``` ... ```)
    code_block_patterns = [
        r'```json\s*\n(.*?)\n```',  # ```json ... ```
        r'```\s*\n(.*?)\n```',       # ``` ... ```
    ]

    for pattern in code_block_patterns:
        matches = re.findall(pattern, text, re.DOTALL)
        if matches:
            if len(matches) > 1:
                raise ValueError(f"Found multiple JSON code blocks ({len(matches)}). Expected exactly one.")
            try:
                return json.loads(matches[0].strip())
            except json.JSONDecodeError:
                # Try next pattern
                continue

    # Try to find JSON objects by looking for {...} (greedy match, take largest)
    json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
    matches = re.findall(json_pattern, text, re.DOTALL)

    if matches:
        # Try parsing matches from longest to shortest (most complete first)
        matches_sorted = sorted(matches, key=len, reverse=True)

        for match in matches_sorted:
            try:
                return json.loads(match)
            except json.JSONDecodeError:
                continue

    # No valid JSON found
    raise json.JSONDecodeError(
        "Could not extract valid JSON from text. "
        "Text should contain a JSON object, optionally in a markdown code block.",
        text[:100],  # Show first 100 chars for debugging
        0
    )


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


class LocalTransformerProvider(LLMProvider):
    """Local transformer model provider using HuggingFace transformers.

    Supports full precision (FP16/BF16) and quantized inference (4-bit/8-bit via bitsandbytes).
    Models are loaded lazily on first inference call.
    """

    def __init__(self, config: ProviderConfig, api_key: str | None = None):
        """Initialize local transformer provider.

        Args:
            config: Provider configuration with model, quantization, and model_path.
            api_key: Optional API key (unused for local models, but accepts for compatibility).
        """
        super().__init__(config, api_key or "")
        self.model = None
        self.tokenizer = None
        self._model_loaded = False

    @property
    def supports_structured_output(self) -> bool:
        """Local transformers do not support native structured output."""
        return False

    def _load_model(self) -> None:
        """Lazy load the model and tokenizer on first inference call.

        Raises:
            ImportError: If required dependencies are not installed.
            Exception: If model cannot be loaded (not found, OOM, etc.).
        """
        if self._model_loaded:
            return

        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        except ImportError as e:
            raise ImportError(
                "Required dependencies not installed. Install with: "
                "pip install transformers torch accelerate bitsandbytes safetensors"
            ) from e

        try:
            # Determine model path (use model_path if specified, otherwise use HF cache)
            model_name_or_path = self.config.model_path or self.config.model

            # Check for MLX models (not compatible with transformers)
            if "mlx" in model_name_or_path.lower():
                raise Exception(
                    f"MLX models (like '{model_name_or_path}') are designed for Apple Silicon "
                    f"and use the MLX framework, not transformers. "
                    f"They are not currently supported by docman's local provider. "
                    f"\n\nAlternatives:"
                    f"\n  1. Use a transformers-compatible model (e.g., google/gemma-2b-it)"
                    f"\n  2. Use a cloud provider (e.g., Google Gemini)"
                    f"\n\nFor a list of compatible models, visit: https://huggingface.co/models?library=transformers"
                )

            # Load tokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(
                model_name_or_path,
                trust_remote_code=True,
            )

            # Load model with appropriate configuration
            load_kwargs = {
                "trust_remote_code": True,
                "device_map": "auto",  # Let transformers decide device placement
            }

            # Only apply bitsandbytes quantization if explicitly requested
            # For pre-quantized models or full precision, let transformers handle it
            if self.config.quantization == "4bit":
                quantization_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_quant_type="nf4",
                )
                load_kwargs["quantization_config"] = quantization_config
            elif self.config.quantization == "8bit":
                quantization_config = BitsAndBytesConfig(
                    load_in_8bit=True,
                )
                load_kwargs["quantization_config"] = quantization_config
            # For None (pre-quantized or full precision), don't set quantization_config
            # Let transformers auto-detect and handle the model's native quantization

            self.model = AutoModelForCausalLM.from_pretrained(
                model_name_or_path,
                **load_kwargs
            )

            self._model_loaded = True

        except OSError as e:
            # Model not found
            error_msg = str(e).lower()
            if "not found" in error_msg or "does not exist" in error_msg:
                raise Exception(
                    f"Model '{self.config.model}' not found. "
                    f"Download it first with: huggingface-cli download {self.config.model}"
                ) from e
            else:
                raise Exception(f"Failed to load model: {str(e)}") from e
        except RuntimeError as e:
            # OOM or other runtime errors
            error_msg = str(e).lower()
            if "out of memory" in error_msg or "oom" in error_msg:
                suggestion = ""
                if not self.config.quantization:
                    suggestion = " Try using 4-bit or 8-bit quantization to reduce memory usage."
                elif self.config.quantization == "8bit":
                    suggestion = " Try using 4-bit quantization for even lower memory usage."
                raise Exception(
                    f"Out of memory (OOM) error loading model.{suggestion}"
                ) from e
            else:
                raise Exception(f"Runtime error loading model: {str(e)}") from e
        except Exception as e:
            raise Exception(f"Failed to load model: {str(e)}") from e

    def generate_suggestions(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Generate file organization suggestions using local transformer model.

        Args:
            system_prompt: Static system prompt defining the LLM's task.
            user_prompt: Dynamic user prompt with document-specific information.

        Returns:
            Dictionary with organization suggestions.

        Raises:
            Exception: If model loading fails or response is invalid.
        """
        # Load model if not already loaded
        self._load_model()

        # Combine prompts (models don't typically have system/user separation in local inference)
        combined_prompt = f"{system_prompt}\n\n{user_prompt}"

        try:
            import torch

            # Tokenize input
            inputs = self.tokenizer(combined_prompt, return_tensors="pt")

            # Move to same device as model
            if self.model and hasattr(self.model, 'device'):
                inputs = {k: v.to(self.model.device) for k, v in inputs.items()}

            # Generate response
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=512,
                    temperature=0.7,
                    do_sample=True,
                    pad_token_id=self.tokenizer.eos_token_id,
                )

            # Decode response
            response_text = self.tokenizer.decode(outputs[0], skip_special_tokens=True)

            # Remove the prompt from response (model often echoes it)
            if response_text.startswith(combined_prompt):
                response_text = response_text[len(combined_prompt):].strip()

            # Extract JSON from response
            data = extract_json_from_text(response_text)

            # Validate against schema
            suggestion = OrganizationSuggestion(**data)

            # Return as dictionary
            return {
                "suggested_directory_path": suggestion.suggested_directory_path,
                "suggested_filename": suggestion.suggested_filename,
                "reason": suggestion.reason,
                "confidence": suggestion.confidence,
            }

        except json.JSONDecodeError as e:
            raise Exception(f"Failed to parse JSON from model output: {str(e)}") from e
        except ValidationError as e:
            raise Exception(f"Model output does not match expected schema: {str(e)}") from e
        except Exception as e:
            raise Exception(f"Failed to generate suggestions: {str(e)}") from e

    def test_connection(self) -> bool:
        """Test that the model can be loaded and generates output.

        Returns:
            True if test successful.

        Raises:
            Exception: If model cannot be loaded or inference fails.
        """
        try:
            # Load model if not already loaded
            self._load_model()

            # Run a simple test inference
            import torch

            test_prompt = "Test: respond with 'OK'"
            inputs = self.tokenizer(test_prompt, return_tensors="pt")

            if self.model and hasattr(self.model, 'device'):
                inputs = {k: v.to(self.model.device) for k, v in inputs.items()}

            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=10,
                    pad_token_id=self.tokenizer.eos_token_id,
                )

            response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)

            if not response:
                raise Exception("Model returned empty response")

            return True

        except Exception as e:
            # Re-raise with context
            raise Exception(f"Model test failed: {str(e)}") from e


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


def get_provider(config: ProviderConfig, api_key: str | None = None) -> LLMProvider:
    """Factory function to create an LLM provider instance.

    Args:
        config: Provider configuration.
        api_key: API key for the provider. Optional for local providers.

    Returns:
        Instance of the appropriate LLM provider.

    Raises:
        ValueError: If provider_type is not supported.
    """
    if config.provider_type == "google":
        if not api_key:
            raise ValueError("API key is required for Google provider")
        return GoogleGeminiProvider(config, api_key)
    elif config.provider_type == "local":
        return LocalTransformerProvider(config, api_key)
    # Future providers can be added here:
    # elif config.provider_type == "anthropic":
    #     return AnthropicClaudeProvider(config, api_key)
    # elif config.provider_type == "openai":
    #     return OpenAIProvider(config, api_key)
    else:
        raise ValueError(f"Unsupported provider type: {config.provider_type}")
