"""Document processing utilities using docling."""

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from docling.document_converter import DocumentConverter
else:
    # Module-level symbol for backward compatibility and test patching
    # Will be lazily imported on first function call
    DocumentConverter: Any = None


def extract_content(file_path: Path, converter: "DocumentConverter | None" = None) -> str | None:
    """
    Extract text content from a document using docling.

    Args:
        file_path: Path to the document file.
        converter: Optional DocumentConverter instance to reuse. If None, creates a new one.

    Returns:
        Extracted text content as a string, or None if extraction fails.
    """
    global DocumentConverter

    try:
        # Lazy import on first use (heavy ML/CV dependencies)
        if DocumentConverter is None:
            from docling.document_converter import DocumentConverter as _DC
            DocumentConverter = _DC

        # Initialize the document converter if not provided
        if converter is None:
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
