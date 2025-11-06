"""Unit tests for LLM provider implementations."""

import json

import pytest

from docman.llm_providers import extract_json_from_text, is_mlx_model


class TestExtractJsonFromText:
    """Tests for extract_json_from_text utility function."""

    def test_extract_plain_json(self) -> None:
        """Test extracting plain JSON without any markdown."""
        json_str = '{"suggested_directory_path": "docs", "suggested_filename": "test.pdf", "reason": "Test", "confidence": 0.9}'
        result = extract_json_from_text(json_str)

        assert result == {
            "suggested_directory_path": "docs",
            "suggested_filename": "test.pdf",
            "reason": "Test",
            "confidence": 0.9
        }

    def test_extract_json_with_whitespace(self) -> None:
        """Test extracting JSON with leading/trailing whitespace."""
        json_str = '''

        {"suggested_directory_path": "docs", "suggested_filename": "test.pdf", "reason": "Test", "confidence": 0.9}

        '''
        result = extract_json_from_text(json_str)

        assert result["suggested_directory_path"] == "docs"

    def test_extract_json_from_markdown_json_block(self) -> None:
        """Test extracting JSON from ```json markdown block."""
        text = '''Here is the response:
```json
{
  "suggested_directory_path": "invoices/2024",
  "suggested_filename": "invoice_001.pdf",
  "reason": "Invoice from 2024",
  "confidence": 0.95
}
```
Hope that helps!'''

        result = extract_json_from_text(text)

        assert result == {
            "suggested_directory_path": "invoices/2024",
            "suggested_filename": "invoice_001.pdf",
            "reason": "Invoice from 2024",
            "confidence": 0.95
        }

    def test_extract_json_from_generic_markdown_block(self) -> None:
        """Test extracting JSON from ``` markdown block (without json tag)."""
        text = '''Here is the response:
```
{
  "suggested_directory_path": "reports",
  "suggested_filename": "report.pdf",
  "reason": "Monthly report",
  "confidence": 0.85
}
```'''

        result = extract_json_from_text(text)

        assert result["suggested_directory_path"] == "reports"

    def test_extract_json_with_surrounding_text(self) -> None:
        """Test extracting JSON embedded in explanatory text."""
        text = '''Based on the document content, here is my suggestion:

        {"suggested_directory_path": "contracts", "suggested_filename": "contract.pdf", "reason": "Legal contract", "confidence": 0.9}

        This organization makes sense because the document is a legal contract.'''

        result = extract_json_from_text(text)

        assert result["suggested_directory_path"] == "contracts"

    def test_extract_json_invalid_raises_error(self) -> None:
        """Test that invalid JSON raises JSONDecodeError."""
        text = "This text contains no valid JSON at all!"

        with pytest.raises(json.JSONDecodeError):
            extract_json_from_text(text)

    def test_extract_json_multiple_blocks_raises_error(self) -> None:
        """Test that multiple JSON blocks raise ValueError."""
        text = '''```json
{"a": 1}
```

And here's another:

```json
{"b": 2}
```'''

        with pytest.raises(ValueError, match="multiple JSON code blocks"):
            extract_json_from_text(text)

    def test_extract_json_with_nested_objects(self) -> None:
        """Test extracting JSON with nested structures."""
        json_str = '''{"suggested_directory_path": "nested/path", "suggested_filename": "test.pdf", "reason": "Has nested data", "confidence": 0.8}'''
        result = extract_json_from_text(json_str)

        assert result["suggested_directory_path"] == "nested/path"

    def test_extract_json_from_malformed_markdown_recovers(self) -> None:
        """Test that malformed markdown can still extract JSON from braces."""
        text = '''The document should go to {"suggested_directory_path": "docs", "suggested_filename": "file.pdf", "reason": "Document file", "confidence": 0.7} in the system.'''
        result = extract_json_from_text(text)

        assert result["suggested_filename"] == "file.pdf"


class TestIsMLXModel:
    """Tests for is_mlx_model detection function."""

    def test_detects_mlx_community_models(self) -> None:
        """Test that MLX community models are detected."""
        assert is_mlx_model("mlx-community/gemma-3n-E4B-it-4bit")
        assert is_mlx_model("mlx-community/Mistral-7B-v0.1-4bit")

    def test_detects_mlx_in_model_name(self) -> None:
        """Test that models with 'mlx' in name are detected."""
        assert is_mlx_model("some-org/model-mlx-4bit")
        assert is_mlx_model("MLX-Models/test")

    def test_case_insensitive_detection(self) -> None:
        """Test that detection is case-insensitive."""
        assert is_mlx_model("MLX-community/model")
        assert is_mlx_model("org/model-MLX")

    def test_does_not_detect_non_mlx_models(self) -> None:
        """Test that non-MLX models are not detected."""
        assert not is_mlx_model("google/gemma-3n-E4B")
        assert not is_mlx_model("mistralai/Mistral-7B-Instruct-v0.2")
        assert not is_mlx_model("TheBloke/Llama-2-7B-GPTQ")

    def test_does_not_detect_similar_names(self) -> None:
        """Test that models with similar but different names are not detected."""
        # These models don't contain 'mlx' substring
        assert not is_mlx_model("model-flux")
        assert not is_mlx_model("org/max-model")
        assert not is_mlx_model("example/model-v1")
