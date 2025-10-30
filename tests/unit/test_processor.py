"""Unit tests for the processor module."""

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from docman.processor import extract_content


class TestExtractContent:
    """Tests for extract_content function."""

    @patch("docman.processor.DocumentConverter")
    def test_successful_extraction(self, mock_converter_class: Mock, tmp_path: Path) -> None:
        """Test successful content extraction from a document."""
        # Create a test file
        test_file = tmp_path / "test.pdf"
        test_file.touch()

        # Mock the converter and its result
        mock_converter = MagicMock()
        mock_converter_class.return_value = mock_converter

        # Mock the result object with document that has export_to_markdown method
        mock_result = MagicMock()
        mock_result.document.export_to_markdown.return_value = "Extracted content"
        mock_converter.convert.return_value = mock_result

        # Call the function
        result = extract_content(test_file)

        # Assertions
        assert result == "Extracted content"
        mock_converter_class.assert_called_once()
        mock_converter.convert.assert_called_once_with(str(test_file))
        mock_result.document.export_to_markdown.assert_called_once()

    @patch("docman.processor.DocumentConverter")
    def test_returns_none_when_no_document(
        self, mock_converter_class: Mock, tmp_path: Path
    ) -> None:
        """Test that None is returned when conversion produces no document."""
        test_file = tmp_path / "test.pdf"
        test_file.touch()

        # Mock converter with no document in result
        mock_converter = MagicMock()
        mock_converter_class.return_value = mock_converter

        mock_result = MagicMock()
        mock_result.document = None
        mock_converter.convert.return_value = mock_result

        result = extract_content(test_file)

        assert result is None

    @patch("docman.processor.DocumentConverter")
    def test_returns_none_when_no_result(
        self, mock_converter_class: Mock, tmp_path: Path
    ) -> None:
        """Test that None is returned when conversion produces no result."""
        test_file = tmp_path / "test.pdf"
        test_file.touch()

        # Mock converter with None result
        mock_converter = MagicMock()
        mock_converter_class.return_value = mock_converter
        mock_converter.convert.return_value = None

        result = extract_content(test_file)

        assert result is None

    @patch("docman.processor.DocumentConverter")
    def test_handles_conversion_exception(
        self, mock_converter_class: Mock, tmp_path: Path
    ) -> None:
        """Test that exceptions during conversion are handled gracefully."""
        test_file = tmp_path / "test.pdf"
        test_file.touch()

        # Mock converter that raises an exception
        mock_converter = MagicMock()
        mock_converter_class.return_value = mock_converter
        mock_converter.convert.side_effect = Exception("Conversion failed")

        # Should not raise, should return None
        result = extract_content(test_file)

        assert result is None

    @patch("docman.processor.DocumentConverter")
    def test_handles_export_exception(
        self, mock_converter_class: Mock, tmp_path: Path
    ) -> None:
        """Test that exceptions during markdown export are handled gracefully."""
        test_file = tmp_path / "test.pdf"
        test_file.touch()

        # Mock converter with export that raises exception
        mock_converter = MagicMock()
        mock_converter_class.return_value = mock_converter

        mock_result = MagicMock()
        mock_result.document.export_to_markdown.side_effect = Exception("Export failed")
        mock_converter.convert.return_value = mock_result

        result = extract_content(test_file)

        assert result is None

    @patch("docman.processor.DocumentConverter")
    def test_converts_path_to_string(self, mock_converter_class: Mock, tmp_path: Path) -> None:
        """Test that Path object is converted to string for docling."""
        test_file = tmp_path / "test.pdf"
        test_file.touch()

        mock_converter = MagicMock()
        mock_converter_class.return_value = mock_converter

        mock_result = MagicMock()
        mock_result.document.export_to_markdown.return_value = "Content"
        mock_converter.convert.return_value = mock_result

        extract_content(test_file)

        # Verify that convert was called with a string, not Path
        call_args = mock_converter.convert.call_args[0][0]
        assert isinstance(call_args, str)
        assert call_args == str(test_file)

    @patch("docman.processor.DocumentConverter")
    def test_handles_empty_content(self, mock_converter_class: Mock, tmp_path: Path) -> None:
        """Test handling of documents with empty content."""
        test_file = tmp_path / "empty.pdf"
        test_file.touch()

        mock_converter = MagicMock()
        mock_converter_class.return_value = mock_converter

        mock_result = MagicMock()
        mock_result.document.export_to_markdown.return_value = ""
        mock_converter.convert.return_value = mock_result

        result = extract_content(test_file)

        # Empty string is still valid content
        assert result == ""

    @patch("docman.processor.DocumentConverter")
    def test_handles_nonexistent_file(
        self, mock_converter_class: Mock, tmp_path: Path
    ) -> None:
        """Test handling of nonexistent files."""
        test_file = tmp_path / "nonexistent.pdf"

        mock_converter = MagicMock()
        mock_converter_class.return_value = mock_converter
        mock_converter.convert.side_effect = FileNotFoundError("File not found")

        result = extract_content(test_file)

        assert result is None
