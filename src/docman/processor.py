"""Document processing utilities using docling."""

import enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from docling.document_converter import DocumentConverter
    from sqlalchemy.orm import Session
else:
    # Module-level symbol for backward compatibility and test patching
    # Will be lazily imported on first function call
    DocumentConverter: Any = None
    Session: Any = None


class ProcessingResult(enum.Enum):
    """Enum for document processing results."""

    NEW_DOCUMENT = "new_document"  # New document created
    UPDATED_DOCUMENT = "updated_document"  # Existing document updated (content changed)
    DUPLICATE_DOCUMENT = "duplicate_document"  # Duplicate document (same content, different location)
    REUSED_COPY = "reused_copy"  # Existing copy reused (no changes)
    EXTRACTION_FAILED = "extraction_failed"  # Content extraction failed
    HASH_FAILED = "hash_failed"  # Content hash computation failed


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


def process_document_file(
    session: "Session",
    repo_root: Path,
    file_path: Path,
    repository_path: str,
    converter: "DocumentConverter | None" = None,
    rescan: bool = False,
) -> tuple["DocumentCopy | None", ProcessingResult]:
    """
    Process a document file: compute hash, extract content, create/update database records.

    This function encapsulates the full document processing workflow:
    1. Compute content hash (with stale detection optimization)
    2. Find or create canonical Document
    3. Extract content using docling (for new documents)
    4. Create or update DocumentCopy with stored metadata

    Args:
        session: SQLAlchemy session.
        repo_root: Path to the repository root.
        file_path: Relative path to the file (from repo_root).
        repository_path: Absolute path to the repository (string).
        converter: Optional DocumentConverter instance to reuse.
        rescan: If True, force re-extraction even if file hasn't changed.

    Returns:
        Tuple of (DocumentCopy | None, ProcessingResult):
            - DocumentCopy: The database record (or None if processing failed).
            - ProcessingResult: Enum indicating the outcome.
    """
    # Import here to avoid circular dependency
    from docman.models import (
        Document,
        DocumentCopy,
        compute_content_hash,
        file_needs_rehashing,
    )

    file_path_str = str(file_path)
    full_path = repo_root / file_path

    # Query existing copy
    existing_copy = (
        session.query(DocumentCopy)
        .filter(
            DocumentCopy.repository_path == repository_path,
            DocumentCopy.file_path == file_path_str,
        )
        .first()
    )

    # Check if we need to rehash (optimization)
    if existing_copy and not rescan and not file_needs_rehashing(existing_copy, full_path):
        # File hasn't changed, reuse existing copy
        return existing_copy, ProcessingResult.REUSED_COPY

    # Compute content hash
    try:
        content_hash = compute_content_hash(full_path)
    except Exception:
        return None, ProcessingResult.HASH_FAILED

    # If existing copy and content hasn't changed, just update metadata
    if existing_copy and content_hash == existing_copy.document.content_hash:
        # Update stored metadata
        stat = full_path.stat()
        existing_copy.stored_content_hash = content_hash
        existing_copy.stored_size = stat.st_size
        existing_copy.stored_mtime = stat.st_mtime
        session.flush()
        return existing_copy, ProcessingResult.REUSED_COPY

    # Find or create canonical document
    document = (
        session.query(Document)
        .filter(Document.content_hash == content_hash)
        .first()
    )

    is_duplicate = document is not None
    is_new_document = False

    if not document:
        # New document - extract content
        content = extract_content(full_path, converter=converter)

        if content is None:
            # Extraction failed, but we still create the document with None content
            # This allows tracking the file even if extraction fails
            pass

        # Create new canonical document
        document = Document(content_hash=content_hash, content=content)
        session.add(document)
        session.flush()  # Get the document.id
        is_new_document = True

    # Create or update document copy
    if existing_copy:
        # Track if document ID changed
        old_document_id = existing_copy.document_id

        # Update existing copy to point to new/different document
        existing_copy.document_id = document.id
        # Update stored metadata
        stat = full_path.stat()
        existing_copy.stored_content_hash = content_hash
        existing_copy.stored_size = stat.st_size
        existing_copy.stored_mtime = stat.st_mtime
        session.flush()

        # If content changed (different document), delete pending operations
        if old_document_id != document.id:
            from docman.models import Operation
            session.query(Operation).filter(
                Operation.document_copy_id == existing_copy.id
            ).delete()

        result = ProcessingResult.UPDATED_DOCUMENT
    else:
        # Create new copy
        stat = full_path.stat()
        copy = DocumentCopy(
            document_id=document.id,
            repository_path=repository_path,
            file_path=file_path_str,
            stored_content_hash=content_hash,
            stored_size=stat.st_size,
            stored_mtime=stat.st_mtime,
        )
        session.add(copy)
        session.flush()
        existing_copy = copy

        if is_new_document:
            result = ProcessingResult.NEW_DOCUMENT
        else:
            result = ProcessingResult.DUPLICATE_DOCUMENT

    # Check if extraction failed (document has no content)
    if document.content is None:
        result = ProcessingResult.EXTRACTION_FAILED

    return existing_copy, result
