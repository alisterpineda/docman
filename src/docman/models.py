"""Database models for docman."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship  # type: ignore[attr-defined]


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
        repository_path: Absolute path to the repository root.
        file_path: Path to the file (absolute or relative to repository).
        created_at: Timestamp when this copy was first discovered.
        updated_at: Timestamp when this copy was last verified.
        document: Relationship to the canonical document.
    """

    __tablename__ = "document_copies"
    __table_args__ = (
        UniqueConstraint("repository_path", "file_path", name="uix_repo_file"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("documents.id"), nullable=False, index=True
    )
    repository_path: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt", DateTime, nullable=False, default=get_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt", DateTime, nullable=False, default=get_utc_now, onupdate=get_utc_now
    )

    # Relationship to canonical document
    document: Mapped["Document"] = relationship("Document", back_populates="copies")

    def __repr__(self) -> str:
        """Return string representation of DocumentCopy."""
        return f"<DocumentCopy(id={self.id}, document_id={self.document_id}, file_path='{self.file_path}')>"
