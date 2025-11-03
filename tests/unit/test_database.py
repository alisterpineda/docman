"""Unit tests for the database module."""

from pathlib import Path
from types import TracebackType

import pytest
from sqlalchemy import inspect, text

from docman.database import (
    ensure_database,
    get_database_path,
    get_engine,
    get_session,
    get_session_factory,
    run_migrations,
)
from docman.models import Document, DocumentCopy


def test_get_database_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that get_database_path returns the correct path."""
    # Set up temporary app config directory
    monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(tmp_path))

    db_path = get_database_path()

    assert db_path == tmp_path / "docman.db"
    assert db_path.parent == tmp_path


def test_get_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that get_engine creates a valid SQLAlchemy engine."""
    monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(tmp_path))

    engine = get_engine()

    assert engine is not None
    assert "sqlite" in str(engine.url)
    assert str(tmp_path / "docman.db") in str(engine.url)


def test_get_session_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that get_session_factory creates a valid session factory."""
    monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(tmp_path))

    session_factory = get_session_factory()

    assert session_factory is not None
    assert callable(session_factory)


def test_get_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that get_session yields a valid session."""
    monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(tmp_path))
    tmp_path.mkdir(parents=True, exist_ok=True)

    # Initialize database first
    ensure_database()

    # Get a session
    session_gen = get_session()
    session = next(session_gen)

    try:
        assert session is not None
        # Verify we can use the session
        result = session.execute(text("SELECT 1"))
        assert result is not None
    finally:
        # Close the session
        try:
            next(session_gen)
        except StopIteration:
            pass


def test_ensure_database_creates_db_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that ensure_database creates the database file."""
    monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(tmp_path))
    db_path = tmp_path / "docman.db"

    assert not db_path.exists()

    ensure_database()

    assert db_path.exists()
    assert db_path.is_file()


def test_ensure_database_runs_migrations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that ensure_database runs migrations and creates tables."""
    monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(tmp_path))

    ensure_database()

    # Check that both tables were created
    engine = get_engine()
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    assert "documents" in tables
    assert "document_copies" in tables

    # Check that the documents table has the expected columns
    doc_columns = inspector.get_columns("documents")
    doc_column_names = [col["name"] for col in doc_columns]

    assert "id" in doc_column_names
    assert "content_hash" in doc_column_names
    assert "content" in doc_column_names
    assert "createdAt" in doc_column_names
    assert "updatedAt" in doc_column_names

    # Check that the document_copies table has the expected columns
    copy_columns = inspector.get_columns("document_copies")
    copy_column_names = [col["name"] for col in copy_columns]

    assert "id" in copy_column_names
    assert "document_id" in copy_column_names
    assert "repository_path" in copy_column_names
    assert "file_path" in copy_column_names
    assert "createdAt" in copy_column_names
    assert "updatedAt" in copy_column_names


def test_ensure_database_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that ensure_database can be called multiple times safely."""
    monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(tmp_path))

    # Call ensure_database multiple times
    ensure_database()
    ensure_database()
    ensure_database()

    # Verify database still exists and is valid
    db_path = get_database_path()
    assert db_path.exists()

    engine = get_engine()
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "documents" in tables


def test_database_operations_with_document_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test basic CRUD operations with Document and DocumentCopy models."""
    monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(tmp_path))

    ensure_database()

    # Create a document
    session_gen = get_session()
    session = next(session_gen)

    try:
        # Create Document
        doc = Document(content_hash="abc123def456", content="Test content")
        session.add(doc)
        session.commit()

        assert doc.id is not None
        assert doc.content_hash == "abc123def456"
        assert doc.content == "Test content"
        assert doc.created_at is not None
        assert doc.updated_at is not None

        # Create DocumentCopy
        copy = DocumentCopy(
            document_id=doc.id,
            repository_path="/path/to/repo",
            file_path="docs/test.pdf",
        )
        session.add(copy)
        session.commit()

        assert copy.id is not None
        assert copy.document_id == doc.id
        assert copy.repository_path == "/path/to/repo"
        assert copy.file_path == "docs/test.pdf"

        # Read
        retrieved_doc = session.query(Document).filter_by(id=doc.id).first()
        assert retrieved_doc is not None
        assert retrieved_doc.content_hash == "abc123def456"
        assert retrieved_doc.content == "Test content"
        assert len(retrieved_doc.copies) == 1

        # Update
        retrieved_doc.content = "Updated content"
        session.commit()

        updated_doc = session.query(Document).filter_by(id=doc.id).first()
        assert updated_doc is not None
        assert updated_doc.content == "Updated content"

        # Delete
        session.delete(updated_doc)
        session.commit()

        deleted_doc = session.query(Document).filter_by(id=doc.id).first()
        assert deleted_doc is None

        # Verify cascade delete of copy
        deleted_copy = session.query(DocumentCopy).filter_by(id=copy.id).first()
        assert deleted_copy is None

    finally:
        # Close the session
        try:
            next(session_gen)
        except StopIteration:
            pass


def test_run_migrations_without_alembic_config_raises_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that run_migrations raises error if alembic.ini doesn't exist."""
    monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(tmp_path))

    import docman.database as db_module

    fake_pkg = tmp_path / "fake_pkg"
    fake_pkg.mkdir()

    def fake_files(_: str) -> Path:
        return fake_pkg

    class _ContextManager:
        def __init__(self, target: Path) -> None:
            self._target = target

        def __enter__(self) -> Path:
            return self._target

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> bool:
            return False

    def fake_as_file(target: Path) -> _ContextManager:
        return _ContextManager(target)

    monkeypatch.setattr(db_module.resources, "files", fake_files)
    monkeypatch.setattr(db_module.resources, "as_file", fake_as_file)

    with pytest.raises(FileNotFoundError, match="Alembic configuration not packaged"):
        run_migrations()
