"""Unit tests for duplicate detection query helpers."""

from pathlib import Path

import pytest

from docman.cli import detect_target_conflicts, find_duplicate_groups, get_duplicate_summary
from docman.database import ensure_database, get_session
from docman.models import Document, DocumentCopy, PendingOperation


@pytest.fixture
def test_repo(tmp_path: Path) -> Path:
    """Create a test repository."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()
    return repo_dir


@pytest.fixture
def session():
    """Create a database session for testing."""
    ensure_database()
    session_gen = get_session()
    session = next(session_gen)

    # Clear all tables before test
    session.query(PendingOperation).delete()
    session.query(DocumentCopy).delete()
    session.query(Document).delete()
    session.commit()

    yield session

    # Cleanup after test
    session.query(PendingOperation).delete()
    session.query(DocumentCopy).delete()
    session.query(Document).delete()
    session.commit()

    try:
        next(session_gen)
    except StopIteration:
        pass


def test_find_duplicate_groups_no_duplicates(session, test_repo: Path) -> None:
    """Test find_duplicate_groups with no duplicates."""
    # Create two different documents
    doc1 = Document(content_hash="hash1", content="Content 1")
    doc2 = Document(content_hash="hash2", content="Content 2")
    session.add_all([doc1, doc2])
    session.flush()

    # Create one copy for each document
    copy1 = DocumentCopy(
        document_id=doc1.id,
        repository_path=str(test_repo),
        file_path="file1.pdf",
    )
    copy2 = DocumentCopy(
        document_id=doc2.id,
        repository_path=str(test_repo),
        file_path="file2.pdf",
    )
    session.add_all([copy1, copy2])
    session.commit()

    # Should return empty dict (no duplicates)
    duplicates = find_duplicate_groups(session, test_repo)
    assert duplicates == {}


def test_find_duplicate_groups_with_duplicates(session, test_repo: Path) -> None:
    """Test find_duplicate_groups with duplicate documents."""
    # Create one document with multiple copies
    doc = Document(content_hash="hash_duplicate", content="Duplicate content")
    session.add(doc)
    session.flush()

    # Create three copies of the same document
    copy1 = DocumentCopy(
        document_id=doc.id,
        repository_path=str(test_repo),
        file_path="inbox/report.pdf",
    )
    copy2 = DocumentCopy(
        document_id=doc.id,
        repository_path=str(test_repo),
        file_path="backup/report.pdf",
    )
    copy3 = DocumentCopy(
        document_id=doc.id,
        repository_path=str(test_repo),
        file_path="archive/report.pdf",
    )
    session.add_all([copy1, copy2, copy3])
    session.commit()

    # Should return one group with three copies
    duplicates = find_duplicate_groups(session, test_repo)
    assert len(duplicates) == 1
    assert doc.id in duplicates
    assert len(duplicates[doc.id]) == 3

    # Check that all copies are present
    copy_paths = {copy.file_path for copy in duplicates[doc.id]}
    assert copy_paths == {"inbox/report.pdf", "backup/report.pdf", "archive/report.pdf"}


def test_find_duplicate_groups_multiple_duplicate_groups(session, test_repo: Path) -> None:
    """Test find_duplicate_groups with multiple duplicate groups."""
    # Create two documents, each with duplicates
    doc1 = Document(content_hash="hash1", content="Content 1")
    doc2 = Document(content_hash="hash2", content="Content 2")
    session.add_all([doc1, doc2])
    session.flush()

    # Document 1: 2 copies
    copy1a = DocumentCopy(
        document_id=doc1.id,
        repository_path=str(test_repo),
        file_path="path1/file1.pdf",
    )
    copy1b = DocumentCopy(
        document_id=doc1.id,
        repository_path=str(test_repo),
        file_path="path2/file1.pdf",
    )

    # Document 2: 3 copies
    copy2a = DocumentCopy(
        document_id=doc2.id,
        repository_path=str(test_repo),
        file_path="path1/file2.pdf",
    )
    copy2b = DocumentCopy(
        document_id=doc2.id,
        repository_path=str(test_repo),
        file_path="path2/file2.pdf",
    )
    copy2c = DocumentCopy(
        document_id=doc2.id,
        repository_path=str(test_repo),
        file_path="path3/file2.pdf",
    )

    session.add_all([copy1a, copy1b, copy2a, copy2b, copy2c])
    session.commit()

    # Should return two groups
    duplicates = find_duplicate_groups(session, test_repo)
    assert len(duplicates) == 2
    assert doc1.id in duplicates
    assert doc2.id in duplicates
    assert len(duplicates[doc1.id]) == 2
    assert len(duplicates[doc2.id]) == 3


def test_find_duplicate_groups_different_repositories(session, test_repo: Path) -> None:
    """Test that find_duplicate_groups only returns duplicates for specified repository."""
    other_repo = test_repo.parent / "other_repo"

    # Create document with copies in different repositories
    doc = Document(content_hash="hash_cross_repo", content="Cross-repo content")
    session.add(doc)
    session.flush()

    # Two copies in test_repo
    copy1 = DocumentCopy(
        document_id=doc.id,
        repository_path=str(test_repo),
        file_path="file1.pdf",
    )
    copy2 = DocumentCopy(
        document_id=doc.id,
        repository_path=str(test_repo),
        file_path="file2.pdf",
    )

    # One copy in other_repo
    copy3 = DocumentCopy(
        document_id=doc.id,
        repository_path=str(other_repo),
        file_path="file3.pdf",
    )

    session.add_all([copy1, copy2, copy3])
    session.commit()

    # Should only return duplicates for test_repo (2 copies)
    duplicates = find_duplicate_groups(session, test_repo)
    assert len(duplicates) == 1
    assert len(duplicates[doc.id]) == 2


def test_detect_target_conflicts_no_conflicts(session, test_repo: Path) -> None:
    """Test detect_target_conflicts with no conflicts."""
    # Create documents and copies
    doc1 = Document(content_hash="hash1", content="Content 1")
    doc2 = Document(content_hash="hash2", content="Content 2")
    session.add_all([doc1, doc2])
    session.flush()

    copy1 = DocumentCopy(
        document_id=doc1.id,
        repository_path=str(test_repo),
        file_path="file1.pdf",
    )
    copy2 = DocumentCopy(
        document_id=doc2.id,
        repository_path=str(test_repo),
        file_path="file2.pdf",
    )
    session.add_all([copy1, copy2])
    session.flush()

    # Create pending operations with different targets
    op1 = PendingOperation(
        document_copy_id=copy1.id,
        suggested_directory_path="reports",
        suggested_filename="report1.pdf",
        reason="Test reason",
        confidence=0.9,
        prompt_hash="hash1",
    )
    op2 = PendingOperation(
        document_copy_id=copy2.id,
        suggested_directory_path="reports",
        suggested_filename="report2.pdf",
        reason="Test reason",
        confidence=0.9,
        prompt_hash="hash2",
    )
    session.add_all([op1, op2])
    session.commit()

    # Should return empty dict (no conflicts)
    conflicts = detect_target_conflicts(session, test_repo)
    assert conflicts == {}


def test_detect_target_conflicts_with_conflicts(session, test_repo: Path) -> None:
    """Test detect_target_conflicts with conflicting targets."""
    # Create document with two copies
    doc = Document(content_hash="hash_dup", content="Duplicate content")
    session.add(doc)
    session.flush()

    copy1 = DocumentCopy(
        document_id=doc.id,
        repository_path=str(test_repo),
        file_path="inbox/report.pdf",
    )
    copy2 = DocumentCopy(
        document_id=doc.id,
        repository_path=str(test_repo),
        file_path="backup/report.pdf",
    )
    session.add_all([copy1, copy2])
    session.flush()

    # Create pending operations with SAME target
    op1 = PendingOperation(
        document_copy_id=copy1.id,
        suggested_directory_path="reports/2024",
        suggested_filename="annual-report.pdf",
        reason="Test reason",
        confidence=0.95,
        prompt_hash="hash1",
    )
    op2 = PendingOperation(
        document_copy_id=copy2.id,
        suggested_directory_path="reports/2024",
        suggested_filename="annual-report.pdf",
        reason="Test reason",
        confidence=0.92,
        prompt_hash="hash2",
    )
    session.add_all([op1, op2])
    session.commit()

    # Should return one conflict with two operations
    conflicts = detect_target_conflicts(session, test_repo)
    assert len(conflicts) == 1

    target = "reports/2024/annual-report.pdf"
    assert target in conflicts
    assert len(conflicts[target]) == 2


def test_detect_target_conflicts_empty_directory_path(session, test_repo: Path) -> None:
    """Test detect_target_conflicts with empty suggested_directory_path."""
    doc = Document(content_hash="hash1", content="Content")
    session.add(doc)
    session.flush()

    copy1 = DocumentCopy(
        document_id=doc.id,
        repository_path=str(test_repo),
        file_path="file1.pdf",
    )
    copy2 = DocumentCopy(
        document_id=doc.id,
        repository_path=str(test_repo),
        file_path="file2.pdf",
    )
    session.add_all([copy1, copy2])
    session.flush()

    # Both suggest moving to root with same filename
    op1 = PendingOperation(
        document_copy_id=copy1.id,
        suggested_directory_path="",
        suggested_filename="report.pdf",
        reason="Test reason",
        confidence=0.9,
        prompt_hash="hash1",
    )
    op2 = PendingOperation(
        document_copy_id=copy2.id,
        suggested_directory_path="",
        suggested_filename="report.pdf",
        reason="Test reason",
        confidence=0.9,
        prompt_hash="hash2",
    )
    session.add_all([op1, op2])
    session.commit()

    # Should detect conflict
    conflicts = detect_target_conflicts(session, test_repo)
    assert len(conflicts) == 1
    assert "report.pdf" in conflicts


def test_get_duplicate_summary_no_duplicates(session, test_repo: Path) -> None:
    """Test get_duplicate_summary with no duplicates."""
    # Create two different documents with one copy each
    doc1 = Document(content_hash="hash1", content="Content 1")
    doc2 = Document(content_hash="hash2", content="Content 2")
    session.add_all([doc1, doc2])
    session.flush()

    copy1 = DocumentCopy(
        document_id=doc1.id,
        repository_path=str(test_repo),
        file_path="file1.pdf",
    )
    copy2 = DocumentCopy(
        document_id=doc2.id,
        repository_path=str(test_repo),
        file_path="file2.pdf",
    )
    session.add_all([copy1, copy2])
    session.commit()

    unique_docs, total_copies = get_duplicate_summary(session, test_repo)
    assert unique_docs == 0
    assert total_copies == 0


def test_get_duplicate_summary_with_duplicates(session, test_repo: Path) -> None:
    """Test get_duplicate_summary with duplicate documents."""
    # Create two documents with duplicates
    doc1 = Document(content_hash="hash1", content="Content 1")
    doc2 = Document(content_hash="hash2", content="Content 2")
    session.add_all([doc1, doc2])
    session.flush()

    # Document 1: 2 copies
    copy1a = DocumentCopy(
        document_id=doc1.id,
        repository_path=str(test_repo),
        file_path="path1/file1.pdf",
    )
    copy1b = DocumentCopy(
        document_id=doc1.id,
        repository_path=str(test_repo),
        file_path="path2/file1.pdf",
    )

    # Document 2: 3 copies
    copy2a = DocumentCopy(
        document_id=doc2.id,
        repository_path=str(test_repo),
        file_path="path1/file2.pdf",
    )
    copy2b = DocumentCopy(
        document_id=doc2.id,
        repository_path=str(test_repo),
        file_path="path2/file2.pdf",
    )
    copy2c = DocumentCopy(
        document_id=doc2.id,
        repository_path=str(test_repo),
        file_path="path3/file2.pdf",
    )

    session.add_all([copy1a, copy1b, copy2a, copy2b, copy2c])
    session.commit()

    unique_docs, total_copies = get_duplicate_summary(session, test_repo)
    assert unique_docs == 2  # Two distinct documents have duplicates
    assert total_copies == 5  # Total of 5 duplicate file copies
