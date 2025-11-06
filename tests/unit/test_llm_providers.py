"""Unit tests for LLM provider implementations."""

import json

import pytest

from docman.llm_providers import extract_json_from_text


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
