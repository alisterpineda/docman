"""Document processing utilities using docling."""

import enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from docling.document_converter import DocumentConverter
    from sqlalchemy.orm import Session

    from docman.models import DocumentCopy as DocumentCopyType
else:
    # Module-level symbol for backward compatibility and test patching
    # Will be lazily imported on first function call
    DocumentConverter: Any = None


class ProcessingResult(enum.Enum):
    """Enum for document processing outcomes."""

    NEW_DOCUMENT = "new_document"  # New document, content extracted
    DUPLICATE_DOCUMENT = "duplicate_document"  # Existing document with same content
    CONTENT_UPDATED = "content_updated"  # Existing copy, content changed
    REUSED_COPY = "reused_copy"  # Existing copy, no changes
    EXTRACTION_FAILED = "extraction_failed"  # Content extraction failed
    HASH_FAILED = "hash_failed"  # Failed to compute content hash


def extract_content(file_path: Path, converter: "DocumentConverter | None" = None) -> str | None:
    """
    Extract text content from a document using docling.

    Args:
        file_path: Path to the document file.
        converter: Optional DocumentConverter instance to reuse. If None, creates a new one.

    Returns:
        Extracted text content as a string, or None if extraction fails.
    """
    try:
        # Initialize the document converter if not provided
        if converter is None:
            # Lazy import on first use (heavy ML/CV dependencies)
            from docling.document_converter import (
                DocumentConverter as DocConverter,
            )

            converter = DocConverter()

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
) -> tuple["DocumentCopyType | None", ProcessingResult]:
    """
    Process a single document file, handling discovery, extraction, and database operations.

    This function encapsulates all the logic for processing a document file:
    - Content hash computation
    - Stale detection via file_needs_rehashing()
    - Document deduplication (finding by hash)
    - Docling content extraction
    - Document/DocumentCopy creation/updates

    Args:
        session: SQLAlchemy database session.
        repo_root: Path to repository root.
        file_path: Relative path to the file from repo_root.
        repository_path: String representation of repository path.
        converter: Optional DocumentConverter instance to reuse.
        rescan: If True, force re-scan even if copy exists with valid metadata.

    Returns:
        Tuple of (DocumentCopy | None, ProcessingResult) where:
        - DocumentCopy is the database record (or None if processing failed)
        - ProcessingResult indicates what happened during processing
    """
    from docman.models import Document, DocumentCopy, compute_content_hash, file_needs_rehashing

    file_path_str = str(file_path)
    full_path = repo_root / file_path

    # Check if copy already exists in this repository at this path
    copy = (
        session.query(DocumentCopy)
        .filter(
            DocumentCopy.repository_path == repository_path,
            DocumentCopy.file_path == file_path_str,
        )
        .first()
    )

    if copy and not rescan:
        # Check if file content has changed
        if file_needs_rehashing(copy, full_path):
            # File metadata changed, rehash to check content
            try:
                content_hash = compute_content_hash(full_path)
            except Exception:
                return None, ProcessingResult.HASH_FAILED

            # Check if content actually changed
            if not copy.document:
                # Document relationship not loaded, this shouldn't happen
                return None, ProcessingResult.HASH_FAILED

            if content_hash != copy.document.content_hash:
                # Content changed - update or create new document
                new_document = (
                    session.query(Document)
                    .filter(Document.content_hash == content_hash)
                    .first()
                )

                if new_document:
                    # Document with this content already exists
                    copy.document_id = new_document.id
                    result = ProcessingResult.DUPLICATE_DOCUMENT
                else:
                    # Extract new content
                    content = extract_content(full_path, converter=converter)

                    if content is None:
                        # Extraction failed, but we'll still create the document
                        result = ProcessingResult.EXTRACTION_FAILED
                    else:
                        result = ProcessingResult.CONTENT_UPDATED

                    # Create new document
                    new_document = Document(content_hash=content_hash, content=content)
                    session.add(new_document)
                    session.flush()

                    # Update copy to point to new document
                    copy.document_id = new_document.id

                # Update stored metadata
                stat = full_path.stat()
                copy.stored_content_hash = content_hash
                copy.stored_size = stat.st_size
                copy.stored_mtime = stat.st_mtime
                session.flush()

                return copy, result
            else:
                # Content hash matches, just update metadata
                stat = full_path.stat()
                copy.stored_content_hash = content_hash
                copy.stored_size = stat.st_size
                copy.stored_mtime = stat.st_mtime
                session.flush()
                return copy, ProcessingResult.REUSED_COPY
        else:
            # Metadata matches, no need to rehash
            return copy, ProcessingResult.REUSED_COPY

    # New file or rescan requested - compute content hash
    try:
        content_hash = compute_content_hash(full_path)
    except Exception:
        return None, ProcessingResult.HASH_FAILED

    # Find or create canonical document
    document = (
        session.query(Document)
        .filter(Document.content_hash == content_hash)
        .first()
    )

    if document:
        # Document already exists (found in another repo or location)
        result = ProcessingResult.DUPLICATE_DOCUMENT
    else:
        # New document - extract content
        content = extract_content(full_path, converter=converter)

        if content is None:
            result = ProcessingResult.EXTRACTION_FAILED
        else:
            result = ProcessingResult.NEW_DOCUMENT

        # Create new canonical document
        document = Document(content_hash=content_hash, content=content)
        session.add(document)
        session.flush()  # Get the document.id for the copy

    # Create or update document copy for this repository
    if copy:
        # Update existing copy (rescan case)
        copy.document_id = document.id
        stat = full_path.stat()
        copy.stored_content_hash = content_hash
        copy.stored_size = stat.st_size
        copy.stored_mtime = stat.st_mtime
    else:
        # Create new document copy
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

    session.flush()  # Get the copy.id

    return copy, result
