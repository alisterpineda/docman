"""Database models for docman."""

import enum
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import (  # type: ignore[attr-defined]
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class OrganizationStatus(enum.Enum):
    """Enum for tracking document organization state."""

    UNORGANIZED = "unorganized"
    ORGANIZED = "organized"
    IGNORED = "ignored"


class OperationStatus(enum.Enum):
    """Enum for tracking operation lifecycle state."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


def get_utc_now() -> datetime:
    """Get current UTC time as a timezone-aware datetime."""
    return datetime.now(UTC)


def compute_content_hash(file_path: str | Path) -> str:
    """
    Compute SHA256 hash of file content.

    Args:
        file_path: Path to the file to hash.

    Returns:
        Hexadecimal string representation of the SHA256 hash.
    """
    path = Path(file_path)
    sha256_hash = hashlib.sha256()

    with path.open("rb") as f:
        # Read file in chunks to handle large files efficiently
        for chunk in iter(lambda: f.read(8192), b""):
            sha256_hash.update(chunk)

    return sha256_hash.hexdigest()


class Base(DeclarativeBase):  # type: ignore[misc]
    """Base class for all database models."""

    pass


class Document(Base):
    """
    Canonical document model representing a unique document (nonfungible).

    A document is uniquely identified by its content hash. Multiple copies of
    the same document across different repositories or locations are represented
    as DocumentCopy instances that reference this canonical document.

    Attributes:
        id: Primary key identifier for the document.
        content_hash: SHA256 hash of the file content (unique identifier).
        content: Extracted text content from the document.
        created_at: Timestamp when the document was first discovered.
        updated_at: Timestamp when the document metadata was last updated.
        copies: Relationship to all copies of this document.
    """

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt", DateTime, nullable=False, default=get_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt", DateTime, nullable=False, default=get_utc_now, onupdate=get_utc_now
    )

    # Relationship to document copies
    copies: Mapped[list["DocumentCopy"]] = relationship(
        "DocumentCopy", back_populates="document", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        """Return string representation of Document."""
        return f"<Document(id={self.id}, content_hash='{self.content_hash[:8]}...')>"


class DocumentCopy(Base):
    """
    Document copy model representing a specific instance of a document (fungible).

    Multiple copies can exist for the same canonical document across different
    repositories or even within the same repository at different paths.

    Attributes:
        id: Primary key identifier for the copy.
        document_id: Foreign key to the canonical document.
        accepted_operation_id: Foreign key to the currently accepted operation (nullable).
        repository_path: Absolute path to the repository root.
        file_path: Path to the file (absolute or relative to repository).
        stored_content_hash: Content hash when last processed (for stale detection).
        stored_size: File size in bytes when last processed (for stale detection).
        stored_mtime: File modification time when last processed (for stale detection).
        last_seen_at: Timestamp when this file was last seen on disk (for cleanup).
        organization_status: Status tracking whether file has been organized (indexed).
        created_at: Timestamp when this copy was first discovered.
        updated_at: Timestamp when this copy was last verified.
        document: Relationship to the canonical document.
        operations: Relationship to all operations for this document copy.
        accepted_operation: Relationship to the currently accepted operation.
    """

    __tablename__ = "document_copies"
    __table_args__ = (
        UniqueConstraint("repository_path", "file_path", name="uix_repo_file"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("documents.id"), nullable=False, index=True
    )
    accepted_operation_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("operations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    repository_path: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    stored_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stored_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stored_mtime: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(
        "lastSeenAt", DateTime, nullable=True, index=True
    )
    organization_status: Mapped[OrganizationStatus] = mapped_column(
        "organization_status",
        Enum(OrganizationStatus),
        nullable=False,
        default=OrganizationStatus.UNORGANIZED,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt", DateTime, nullable=False, default=get_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt", DateTime, nullable=False, default=get_utc_now, onupdate=get_utc_now
    )

    # Relationship to canonical document
    document: Mapped["Document"] = relationship("Document", back_populates="copies")

    # Relationship to operations (no cascade - operations preserved for historical record)
    operations: Mapped[list["Operation"]] = relationship(
        "Operation",
        foreign_keys="[Operation.document_copy_id]",
        back_populates="document_copy"
    )

    # Relationship to accepted operation (no cascade)
    accepted_operation: Mapped["Operation | None"] = relationship(
        "Operation",
        foreign_keys="[DocumentCopy.accepted_operation_id]",
        post_update=True
    )

    def __repr__(self) -> str:
        """Return string representation of DocumentCopy."""
        return (
            f"<DocumentCopy(id={self.id}, document_id={self.document_id}, "
            f"file_path='{self.file_path}')>"
        )


class Operation(Base):
    """
    Operation model storing LLM suggestions for file organization with lifecycle tracking.

    This table stores suggestions from the LLM on where a file should be moved
    and/or renamed to, and tracks the full lifecycle (PENDING → ACCEPTED/REJECTED).
    Each document copy can have at most one PENDING operation, but multiple historical
    operations (ACCEPTED/REJECTED) are preserved.

    Attributes:
        id: Primary key identifier for the operation.
        document_copy_id: Foreign key to the document copy this operation applies to.
        status: Current status of the operation (PENDING, ACCEPTED, REJECTED).
        suggested_directory_path: Suggested directory path for the file.
        suggested_filename: Suggested filename for the file.
        reason: Explanation for why this organization is suggested.
        prompt_hash: SHA256 hash of the prompt used to generate this suggestion.
        document_content_hash: Content hash when this suggestion was generated (for invalidation).
        model_name: LLM model name when this suggestion was generated (for invalidation).
        created_at: Timestamp when the suggestion was created.
        document_copy: Relationship to the document copy.
    """

    __tablename__ = "operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_copy_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("document_copies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[OperationStatus] = mapped_column(
        Enum(OperationStatus),
        nullable=False,
        default=OperationStatus.PENDING,
        index=True,
    )
    suggested_directory_path: Mapped[str] = mapped_column(String(255), nullable=False)
    suggested_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    document_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt", DateTime, nullable=False, default=get_utc_now
    )

    # Relationship to document copy (nullable - copy may be deleted but operation preserved)
    document_copy: Mapped["DocumentCopy | None"] = relationship(
        "DocumentCopy",
        foreign_keys=[document_copy_id],
        back_populates="operations"
    )

    def __repr__(self) -> str:
        """Return string representation of Operation."""
        return (
            f"<Operation(id={self.id}, document_copy_id={self.document_copy_id}, "
            f"status={self.status.value})>"
        )


def file_needs_rehashing(copy: DocumentCopy, file_path: Path) -> bool:
    """Check if a file needs to be rehashed based on stored metadata.

    This is an optimization to avoid rehashing files that haven't changed.
    We first check the file size and modification time - only if those differ
    do we need to rehash the file to check if content actually changed.

    Args:
        copy: The DocumentCopy database record with stored metadata.
        file_path: Path to the current file on disk.

    Returns:
        True if the file needs to be rehashed (metadata differs or not stored),
        False if the stored metadata matches and we can skip rehashing.
    """
    # If we don't have stored metadata, we need to hash
    if copy.stored_size is None or copy.stored_mtime is None:
        return True

    # Check if file exists
    if not file_path.exists():
        return False  # File doesn't exist, no point in rehashing

    # Get current file metadata
    stat = file_path.stat()
    current_size = stat.st_size
    current_mtime = stat.st_mtime

    # If size or mtime differs, we need to rehash
    if current_size != copy.stored_size or abs(current_mtime - copy.stored_mtime) > 0.001:
        return True

    # Metadata matches, no need to rehash
    return False


def operation_needs_regeneration(
    operation: Operation | None,
    current_prompt_hash: str,
    document_content_hash: str | None,
    model_name: str | None,
) -> tuple[bool, str | None]:
    """
    Check if an operation needs to be regenerated based on prompt/content/model changes.

    Args:
        operation: The existing pending operation (or None if no operation exists).
        current_prompt_hash: Hash of the current prompt.
        document_content_hash: Hash of the current document content.
        model_name: Name of the current model.

    Returns:
        Tuple of (needs_regeneration: bool, reason: str | None) where:
        - needs_regeneration is True if the operation should be regenerated
        - reason describes why regeneration is needed (or None if not needed)
    """
    if not operation:
        return True, None

    if operation.prompt_hash != current_prompt_hash:
        return True, "Prompt or model changed"

    if document_content_hash and operation.document_content_hash != document_content_hash:
        return True, "Document content changed"

    if model_name and operation.model_name != model_name:
        return True, "Model changed"

    return False, None


def query_documents_needing_suggestions(
    session: "Session",
    repo_root: Path,
    path_filter: str | None = None,
    reprocess: bool = False,
    recursive: bool = True,
) -> list[tuple[DocumentCopy, Document]]:
    """
    Query DocumentCopy records that need LLM processing.

    This function queries for document copies that:
    1. Have been scanned (have a DocumentCopy record)
    2. Match the optional path filter
    3. Are not organized/ignored (unless reprocess=True)
    4. Either have no pending operation or have a stale operation

    Args:
        session: SQLAlchemy database session.
        repo_root: Path to repository root.
        path_filter: Optional path filter (file or directory).
        reprocess: If True, include organized/ignored files.
        recursive: If True, include subdirectories when path_filter is a directory.

    Returns:
        List of (DocumentCopy, Document) tuples that need LLM processing.
    """
    repository_path = str(repo_root)

    # Base query: join DocumentCopy with Document
    query = (
        session.query(DocumentCopy, Document)
        .join(Document, DocumentCopy.document_id == Document.id)
        .filter(DocumentCopy.repository_path == repository_path)
    )

    # Apply path filter if provided
    if path_filter:
        # Convert to string for database comparison
        path_str = str(path_filter)
        if recursive:
            # Filter by exact match or directory prefix (recursive)
            query = query.filter(  # type: ignore[assignment]
                (DocumentCopy.file_path == path_str) |
                (DocumentCopy.file_path.like(f"{path_str}/%"))  # type: ignore[attr-defined]
            )
        else:
            # Filter by exact match or direct children only (non-recursive)
            # Match files directly in the directory (no nested slashes after prefix)
            query = query.filter(  # type: ignore[assignment]
                (DocumentCopy.file_path == path_str) |
                (
                    (DocumentCopy.file_path.like(f"{path_str}/%"))  # type: ignore[attr-defined]
                    & (~DocumentCopy.file_path.like(f"{path_str}/%/%"))  # type: ignore[attr-defined]
                )
            )

    # Filter by organization status (unless reprocess=True)
    if not reprocess:
        query = query.filter(  # type: ignore[assignment]
            DocumentCopy.organization_status.in_([  # type: ignore[attr-defined]
                OrganizationStatus.UNORGANIZED
            ])
        )

    return query.all()  # type: ignore[return-value]
