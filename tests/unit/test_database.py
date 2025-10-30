"""Unit tests for the database module."""

import os
from pathlib import Path

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
from docman.models import Document


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

    # Check that the documents table was created
    engine = get_engine()
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    assert "documents" in tables

    # Check that the table has the expected columns
    columns = inspector.get_columns("documents")
    column_names = [col["name"] for col in columns]

    assert "id" in column_names
    assert "file_path" in column_names
    assert "content" in column_names
    assert "createdAt" in column_names


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
    """Test basic CRUD operations with the Document model."""
    monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(tmp_path))

    ensure_database()

    # Create a document
    session_gen = get_session()
    session = next(session_gen)

    try:
        # Create
        doc = Document(file_path="/path/to/test.pdf", content="Test content")
        session.add(doc)
        session.commit()

        assert doc.id is not None
        assert doc.file_path == "/path/to/test.pdf"
        assert doc.content == "Test content"
        assert doc.created_at is not None

        # Read
        retrieved_doc = session.query(Document).filter_by(id=doc.id).first()
        assert retrieved_doc is not None
        assert retrieved_doc.file_path == "/path/to/test.pdf"
        assert retrieved_doc.content == "Test content"

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

    # Create a temporary directory that doesn't have alembic.ini
    fake_project_dir = tmp_path / "fake_project"
    fake_project_dir.mkdir()

    # Temporarily change the module path
    import docman.database as db_module

    original_file = db_module.__file__
    monkeypatch.setattr(
        db_module, "__file__", str(fake_project_dir / "src/docman/database.py")
    )

    try:
        with pytest.raises(FileNotFoundError, match="Alembic configuration not found"):
            run_migrations()
    finally:
        monkeypatch.setattr(db_module, "__file__", original_file)
