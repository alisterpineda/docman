"""Unit tests for database models."""

from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from docman.database import ensure_database, get_session
from docman.models import Document, DocumentCopy, compute_content_hash


def test_compute_content_hash_consistent(tmp_path: Path) -> None:
    """Test that compute_content_hash returns consistent hashes for same content."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello, World!")

    hash1 = compute_content_hash(test_file)
    hash2 = compute_content_hash(test_file)

    assert hash1 == hash2
    assert len(hash1) == 64  # SHA256 produces 64 hex characters


def test_compute_content_hash_different_content(tmp_path: Path) -> None:
    """Test that different content produces different hashes."""
    file1 = tmp_path / "file1.txt"
    file2 = tmp_path / "file2.txt"

    file1.write_text("Content A")
    file2.write_text("Content B")

    hash1 = compute_content_hash(file1)
    hash2 = compute_content_hash(file2)

    assert hash1 != hash2


def test_compute_content_hash_binary_files(tmp_path: Path) -> None:
    """Test that compute_content_hash works with binary files."""
    binary_file = tmp_path / "test.bin"
    binary_file.write_bytes(b"\x00\x01\x02\x03\xff\xfe\xfd")

    hash_result = compute_content_hash(binary_file)

    assert isinstance(hash_result, str)
    assert len(hash_result) == 64


def test_compute_content_hash_large_file(tmp_path: Path) -> None:
    """Test that compute_content_hash handles large files efficiently."""
    large_file = tmp_path / "large.txt"
    # Create a file larger than the chunk size (8192 bytes)
    large_file.write_text("x" * 100000)

    hash_result = compute_content_hash(large_file)

    assert isinstance(hash_result, str)
    assert len(hash_result) == 64


def test_document_content_hash_unique_constraint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that duplicate content_hash values are rejected."""
    monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(tmp_path))
    ensure_database()

    session_gen = get_session()
    session = next(session_gen)

    try:
        # Create first document with a hash
        doc1 = Document(content_hash="abc123", content="Test content 1")
        session.add(doc1)
        session.commit()

        # Try to create second document with same hash
        doc2 = Document(content_hash="abc123", content="Test content 2")
        session.add(doc2)

        with pytest.raises(IntegrityError):
            session.commit()

    finally:
        session.rollback()
        try:
            next(session_gen)
        except StopIteration:
            pass


def test_document_copy_relationship(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test the relationship between Document and DocumentCopy."""
    monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(tmp_path))
    ensure_database()

    session_gen = get_session()
    session = next(session_gen)

    try:
        # Create a document
        doc = Document(content_hash="hash123", content="Test content")
        session.add(doc)
        session.commit()

        # Create copies
        copy1 = DocumentCopy(
            document_id=doc.id,
            repository_path="/repo1",
            file_path="docs/test.pdf",
        )
        copy2 = DocumentCopy(
            document_id=doc.id,
            repository_path="/repo2",
            file_path="files/test.pdf",
        )
        session.add(copy1)
        session.add(copy2)
        session.commit()

        # Verify relationship from document to copies
        assert len(doc.copies) == 2
        assert copy1 in doc.copies
        assert copy2 in doc.copies

        # Verify relationship from copy to document
        assert copy1.document == doc
        assert copy2.document == doc

    finally:
        try:
            next(session_gen)
        except StopIteration:
            pass


def test_document_copy_unique_constraint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that duplicate (repository_path, file_path) combinations are rejected."""
    monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(tmp_path))
    ensure_database()

    session_gen = get_session()
    session = next(session_gen)

    try:
        # Create a document
        doc = Document(content_hash="hash456", content="Test content")
        session.add(doc)
        session.commit()

        # Create first copy
        copy1 = DocumentCopy(
            document_id=doc.id,
            repository_path="/repo1",
            file_path="docs/test.pdf",
        )
        session.add(copy1)
        session.commit()

        # Try to create duplicate copy (same repo + file path)
        copy2 = DocumentCopy(
            document_id=doc.id,
            repository_path="/repo1",
            file_path="docs/test.pdf",
        )
        session.add(copy2)

        with pytest.raises(IntegrityError):
            session.commit()

    finally:
        session.rollback()
        try:
            next(session_gen)
        except StopIteration:
            pass


def test_document_copy_allows_same_file_different_repos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that same file path in different repositories is allowed."""
    monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(tmp_path))
    ensure_database()

    session_gen = get_session()
    session = next(session_gen)

    try:
        # Create a document
        doc = Document(content_hash="hash789", content="Test content")
        session.add(doc)
        session.commit()

        # Create copies with same file_path but different repository_path
        copy1 = DocumentCopy(
            document_id=doc.id,
            repository_path="/repo1",
            file_path="docs/test.pdf",
        )
        copy2 = DocumentCopy(
            document_id=doc.id,
            repository_path="/repo2",
            file_path="docs/test.pdf",
        )
        session.add(copy1)
        session.add(copy2)
        session.commit()

        # Verify both copies were created
        copies = session.query(DocumentCopy).filter(DocumentCopy.document_id == doc.id).all()
        assert len(copies) == 2

    finally:
        try:
            next(session_gen)
        except StopIteration:
            pass


def test_document_cascade_delete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that deleting a document cascades to its copies."""
    monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(tmp_path))
    ensure_database()

    session_gen = get_session()
    session = next(session_gen)

    try:
        # Create document with copies
        doc = Document(content_hash="hashABC", content="Test content")
        session.add(doc)
        session.flush()

        copy1 = DocumentCopy(
            document_id=doc.id,
            repository_path="/repo1",
            file_path="test.pdf",
        )
        copy2 = DocumentCopy(
            document_id=doc.id,
            repository_path="/repo2",
            file_path="test.pdf",
        )
        session.add(copy1)
        session.add(copy2)
        session.commit()

        doc_id = doc.id

        # Delete the document
        session.delete(doc)
        session.commit()

        # Verify copies were also deleted
        remaining_copies = session.query(DocumentCopy).filter(
            DocumentCopy.document_id == doc_id
        ).all()
        assert len(remaining_copies) == 0

    finally:
        try:
            next(session_gen)
        except StopIteration:
            pass
