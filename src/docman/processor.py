"""Document processing utilities using docling."""

from pathlib import Path

from docling.document_converter import DocumentConverter


def extract_content(file_path: Path) -> str | None:
    """
    Extract text content from a document using docling.

    Args:
        file_path: Path to the document file.

    Returns:
        Extracted text content as a string, or None if extraction fails.
    """
    try:
        # Initialize the document converter
        converter = DocumentConverter()

        # Convert the document
        result = converter.convert(str(file_path))

        # Extract text content
        # The result object has a document property with export_to_markdown method
        if result and result.document:
            content = result.document.export_to_markdown()
            return content

        return None

    except Exception:
        # Log the error but don't crash - we'll store None as content
        # This could be improved with proper logging in the future
        return None
