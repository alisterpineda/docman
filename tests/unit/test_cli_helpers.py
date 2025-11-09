"""Unit tests for CLI helper functions."""

import json

from docman.cli import _format_suggestion_as_json


class TestFormatSuggestionAsJson:
    """Tests for _format_suggestion_as_json function."""

    def test_basic_formatting(self) -> None:
        """Test basic JSON formatting with all required fields."""
        suggestion = {
            "suggested_directory_path": "documents/invoices",
            "suggested_filename": "invoice_001.pdf",
            "reason": "This is an invoice from 2024",
        }

        result = _format_suggestion_as_json(suggestion)

        # Verify it's valid JSON
        parsed = json.loads(result)
        assert parsed["suggested_directory_path"] == "documents/invoices"
        assert parsed["suggested_filename"] == "invoice_001.pdf"
        assert parsed["reason"] == "This is an invoice from 2024"

    def test_pretty_printing(self) -> None:
        """Test that JSON is pretty-printed with indentation."""
        suggestion = {
            "suggested_directory_path": "test",
            "suggested_filename": "test.pdf",
            "reason": "test reason",
        }

        result = _format_suggestion_as_json(suggestion)

        # Pretty-printed JSON should have newlines and indentation
        assert "\n" in result
        assert "  " in result  # Should have 2-space indentation
        # Should be multiple lines (opening brace, fields, closing brace)
        assert len(result.split("\n")) > 3

    def test_special_characters_in_fields(self) -> None:
        """Test handling of special characters in suggestion fields."""
        suggestion = {
            "suggested_directory_path": "documents/quotes & invoices",
            "suggested_filename": 'file "with" quotes.pdf',
            "reason": "Contains special chars: \\ / : * ? \" < > |",
        }

        result = _format_suggestion_as_json(suggestion)

        # Verify it's valid JSON (special chars should be escaped)
        parsed = json.loads(result)
        assert parsed["suggested_directory_path"] == "documents/quotes & invoices"
        assert parsed["suggested_filename"] == 'file "with" quotes.pdf'
        assert "special chars" in parsed["reason"]

    def test_unicode_characters(self) -> None:
        """Test handling of Unicode characters in suggestion fields."""
        suggestion = {
            "suggested_directory_path": "documents/年度報告",
            "suggested_filename": "résumé_ñoño.pdf",
            "reason": "Contains Unicode: 日本語 español français",
        }

        result = _format_suggestion_as_json(suggestion)

        # Verify it's valid JSON and Unicode is preserved
        parsed = json.loads(result)
        assert parsed["suggested_directory_path"] == "documents/年度報告"
        assert parsed["suggested_filename"] == "résumé_ñoño.pdf"
        assert "日本語" in parsed["reason"]

    def test_empty_fields(self) -> None:
        """Test handling of empty string fields."""
        suggestion = {
            "suggested_directory_path": "",
            "suggested_filename": "file.pdf",
            "reason": "",
        }

        result = _format_suggestion_as_json(suggestion)

        # Verify it's valid JSON
        parsed = json.loads(result)
        assert parsed["suggested_directory_path"] == ""
        assert parsed["suggested_filename"] == "file.pdf"
        assert parsed["reason"] == ""

    def test_long_reason_field(self) -> None:
        """Test formatting with very long reason field."""
        long_reason = "This is a very long reason. " * 100
        suggestion = {
            "suggested_directory_path": "documents",
            "suggested_filename": "test.pdf",
            "reason": long_reason,
        }

        result = _format_suggestion_as_json(suggestion)

        # Verify it's valid JSON
        parsed = json.loads(result)
        assert parsed["reason"] == long_reason
        assert len(parsed["reason"]) > 2000

    def test_newlines_in_reason(self) -> None:
        """Test handling of newlines in reason field."""
        suggestion = {
            "suggested_directory_path": "documents",
            "suggested_filename": "test.pdf",
            "reason": "Line 1\nLine 2\nLine 3",
        }

        result = _format_suggestion_as_json(suggestion)

        # Verify it's valid JSON (newlines should be escaped)
        parsed = json.loads(result)
        assert parsed["reason"] == "Line 1\nLine 2\nLine 3"
        # In the JSON string, newlines should be escaped
        assert "\\n" in result
