"""Shared pytest fixtures and test utilities for docman."""

from pathlib import Path
from typing import Callable

import pytest
from click.testing import CliRunner
from pytest import MonkeyPatch

from docman.database import ensure_database, get_session
from docman.models import Document, DocumentCopy, Operation, compute_content_hash


@pytest.fixture(autouse=True, scope="function")
def isolate_app_config(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Automatically isolate app config directory for all tests.

    This fixture runs automatically for every test and ensures that tests
    never touch the real user app config directory or database.

    Args:
        tmp_path: Pytest temporary directory for this test.
        monkeypatch: Pytest monkeypatch fixture for setting environment variables.

    Returns:
        Path: The isolated temporary app config directory for the test.
    """
    # Create a subdirectory in tmp_path for app config
    isolated_config_dir = tmp_path / "app_config"
    isolated_config_dir.mkdir(exist_ok=True)

    # Set the environment variable to use the isolated directory
    monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(isolated_config_dir))

    return isolated_config_dir


@pytest.fixture
def db_session():
    """Provide a clean database session with automatic cleanup.

    Yields:
        Session: SQLAlchemy session for database operations.
    """
    ensure_database()
    session_gen = get_session()
    session = next(session_gen)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        try:
            next(session_gen)
        except StopIteration:
            pass


@pytest.fixture
def cli_runner() -> CliRunner:
    """Provide a Click CLI runner for testing commands.

    Returns:
        CliRunner: A Click test runner instance.
    """
    return CliRunner()


@pytest.fixture
def docman_dir_name() -> str:
    """Provide the standard docman directory name.

    Returns:
        str: The name of the docman configuration directory.
    """
    return ".docman"


@pytest.fixture
def config_file_name() -> str:
    """Provide the standard config file name.

    Returns:
        str: The name of the docman configuration file.
    """
    return "config.yaml"


def assert_docman_initialized(path: Path) -> None:
    """Assert that a docman repository is properly initialized at the given path.

    Args:
        path: The directory path where docman should be initialized.

    Raises:
        AssertionError: If the docman repository is not properly initialized.
    """
    docman_dir = path / ".docman"
    config_file = docman_dir / "config.yaml"

    assert docman_dir.exists(), f"Expected .docman directory at {docman_dir}"
    assert docman_dir.is_dir(), f"Expected .docman to be a directory at {docman_dir}"
    assert config_file.exists(), f"Expected config.yaml at {config_file}"
    assert config_file.is_file(), f"Expected config.yaml to be a file at {config_file}"


def setup_repository(path: Path) -> None:
    """Set up a docman repository for testing.

    Args:
        path: The directory path where the repository should be set up.
    """
    docman_dir = path / ".docman"
    docman_dir.mkdir(exist_ok=True)
    config_file = docman_dir / "config.yaml"

    # Create folder definitions (required for plan command)
    config_content = """
organization:
  variable_patterns:
    year: "4-digit year in YYYY format"
    category: "Document category"
  folders:
    Documents:
      description: "Test documents folder"
      folders:
        Archive:
          description: "Archived documents"
"""
    config_file.write_text(config_content)


@pytest.fixture
def isolated_repo(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Set up an isolated test repository with app config.

    This combines repository setup and app config isolation in one fixture.

    Args:
        tmp_path: Pytest temporary directory.
        monkeypatch: Pytest monkeypatch fixture.

    Returns:
        Path: The repository directory.
    """
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    setup_repository(repo_dir)
    return repo_dir


@pytest.fixture
def create_scanned_document(db_session) -> Callable:
    """Factory fixture for creating scanned documents in the database.

    Returns:
        Callable: Function to create scanned documents.
    """

    def _create(
        repo_dir: Path, file_path: str, content: str = "Test content"
    ) -> tuple[Document, DocumentCopy]:
        """Create a scanned document in the database (simulates scan command).

        Args:
            repo_dir: Repository directory path.
            file_path: Relative file path within repository.
            content: Document content.

        Returns:
            Tuple of (Document, DocumentCopy).
        """
        # Create the actual file
        full_path = repo_dir / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)

        # Compute content hash
        content_hash = compute_content_hash(full_path)

        # Create document
        document = Document(content_hash=content_hash, content=content)
        db_session.add(document)
        db_session.flush()

        # Create document copy with stored metadata
        stat = full_path.stat()
        copy = DocumentCopy(
            document_id=document.id,
            repository_path=str(repo_dir),
            file_path=file_path,
            stored_content_hash=content_hash,
            stored_size=stat.st_size,
            stored_mtime=stat.st_mtime,
        )
        db_session.add(copy)
        db_session.commit()

        return document, copy

    return _create


@pytest.fixture
def create_pending_operation(db_session) -> Callable:
    """Factory fixture for creating pending operations in the database.

    Returns:
        Callable: Function to create pending operations.
    """

    def _create(
        repo_path: str,
        file_path: str,
        suggested_dir: str,
        suggested_filename: str,
        reason: str = "Test reason",
        confidence: float = 0.95,
    ) -> Operation:
        """Create a pending operation in the database.

        Args:
            repo_path: Repository path.
            file_path: File path within repository.
            suggested_dir: Suggested directory path.
            suggested_filename: Suggested filename.
            reason: Reason for the suggestion.
            confidence: Confidence score.

        Returns:
            Operation: The created operation.
        """
        # Create document
        doc = Document(content_hash=f"hash_{file_path}", content="Test content")
        db_session.add(doc)
        db_session.flush()

        # Create document copy
        copy = DocumentCopy(
            document_id=doc.id,
            repository_path=repo_path,
            file_path=file_path,
        )
        db_session.add(copy)
        db_session.flush()

        # Create pending operation
        pending_op = Operation(
            document_copy_id=copy.id,
            suggested_directory_path=suggested_dir,
            suggested_filename=suggested_filename,
            reason=reason,
            prompt_hash="test_hash",
        )
        db_session.add(pending_op)
        db_session.commit()

        return pending_op

    return _create


@pytest.fixture(scope="module")
def document_converter():
    """Provide a reusable DocumentConverter for tests.

    Uses module scope to avoid expensive re-initialization.
    Improves test performance significantly.

    Returns:
        DocumentConverter: Shared converter instance.
    """
    try:
        from docling.document_converter import DocumentConverter

        return DocumentConverter()
    except ImportError:
        # If docling is not available (dev dependencies not installed),
        # return None and tests can skip or use mocks
        return None
