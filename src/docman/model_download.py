"""Utilities for downloading HuggingFace models for local LLM inference.

This module provides functions to download models from HuggingFace Hub
with progress reporting and error handling.
"""

from pathlib import Path
from typing import Callable


def check_model_exists(model_id: str) -> bool:
    """Check if a model is already downloaded in the HuggingFace cache.

    Args:
        model_id: HuggingFace model identifier (e.g., "google/gemma-3n-E4B")

    Returns:
        True if model files exist in cache, False otherwise.
    """
    try:
        from huggingface_hub import scan_cache_dir

        cache_info = scan_cache_dir()

        # Check if model_id exists in any of the cached repos
        for repo in cache_info.repos:
            if repo.repo_id == model_id:
                # Check if repo has any revisions (means files downloaded)
                if repo.revisions:
                    return True

        return False
    except Exception:
        # If there's any error checking cache, assume model doesn't exist
        return False


def download_model(
    model_id: str,
    progress_callback: Callable[[str], None] | None = None,
) -> bool:
    """Download a model from HuggingFace Hub.

    Args:
        model_id: HuggingFace model identifier (e.g., "google/gemma-3n-E4B")
        progress_callback: Optional callback function to report progress messages

    Returns:
        True if download successful, False otherwise.

    Raises:
        ImportError: If huggingface-hub is not installed.
        Exception: If download fails with detailed error message.
    """
    try:
        from huggingface_hub import snapshot_download
        from huggingface_hub.utils import HfHubHTTPError, RepositoryNotFoundError
    except ImportError as e:
        raise ImportError(
            "huggingface-hub is not installed. Install with: pip install huggingface-hub"
        ) from e

    def report(message: str) -> None:
        """Report progress message via callback if provided."""
        if progress_callback:
            progress_callback(message)

    try:
        report(f"Downloading model '{model_id}' from HuggingFace Hub...")
        report("This may take several minutes depending on model size and network speed.")

        # Download the model to HuggingFace cache
        # This downloads all files needed for the model
        cache_dir = snapshot_download(
            repo_id=model_id,
            resume_download=True,  # Resume if interrupted
            local_files_only=False,  # Download from hub
        )

        report(f"Model successfully downloaded to: {cache_dir}")
        return True

    except RepositoryNotFoundError as e:
        raise Exception(
            f"Model '{model_id}' not found on HuggingFace Hub. "
            f"Please check the model name and try again. "
            f"Visit https://huggingface.co/models to browse available models."
        ) from e
    except HfHubHTTPError as e:
        error_msg = str(e).lower()
        if "401" in error_msg or "403" in error_msg:
            raise Exception(
                f"Access denied to model '{model_id}'. "
                f"This model may require authentication or acceptance of terms. "
                f"Visit https://huggingface.co/{model_id} to check access requirements."
            ) from e
        elif "404" in error_msg:
            raise Exception(
                f"Model '{model_id}' not found. Please check the model name."
            ) from e
        else:
            raise Exception(
                f"HTTP error downloading model: {str(e)}"
            ) from e
    except OSError as e:
        error_msg = str(e).lower()
        if "disk" in error_msg or "space" in error_msg:
            raise Exception(
                f"Insufficient disk space to download model '{model_id}'. "
                f"Models can be several GB in size. Please free up space and try again."
            ) from e
        else:
            raise Exception(f"OS error downloading model: {str(e)}") from e
    except Exception as e:
        raise Exception(f"Failed to download model '{model_id}': {str(e)}") from e


def get_model_info(model_id: str) -> dict[str, str] | None:
    """Get basic information about a model from HuggingFace Hub.

    Args:
        model_id: HuggingFace model identifier

    Returns:
        Dictionary with model info (id, downloads, likes, etc.) or None if unavailable.
    """
    try:
        from huggingface_hub import model_info

        info = model_info(model_id)
        return {
            "id": info.id,
            "downloads": str(info.downloads) if info.downloads else "N/A",
            "likes": str(info.likes) if info.likes else "0",
            "pipeline_tag": info.pipeline_tag or "N/A",
        }
    except Exception:
        return None


def is_pre_quantized_model(model_id: str) -> bool:
    """Check if a model is pre-quantized (already quantized at upload time).

    Pre-quantized models should not have additional runtime quantization applied.

    Args:
        model_id: HuggingFace model identifier

    Returns:
        True if model appears to be pre-quantized, False otherwise.
    """
    model_lower = model_id.lower()

    # Common patterns for pre-quantized models
    pre_quant_patterns = [
        "4bit",
        "8bit",
        "awq",
        "gptq",
        "gguf",
        "ggml",
        "int4",
        "int8",
        "mlx",  # MLX models are typically pre-quantized
        "exl2",
        "bnb-4bit",
        "bnb-8bit",
    ]

    return any(pattern in model_lower for pattern in pre_quant_patterns)

