"""Shared pytest fixtures and test utilities for docman."""

from pathlib import Path

import pytest
from click.testing import CliRunner
from pytest import MonkeyPatch


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


@pytest.fixture
def db_session():
    """Provide a database session with automatic cleanup.

    This fixture eliminates the need for repetitive try/finally blocks
    for session management in every test.

    Yields:
        Session: A database session that will be properly closed after the test.
    """
    from docman.database import get_session

    session_gen = get_session()
    session = next(session_gen)
    yield session
    try:
        next(session_gen)
    except StopIteration:
        pass


@pytest.fixture
def docman_repo(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Create an isolated docman repository for testing.

    This fixture provides a complete test repository with proper isolation,
    eliminating the need for setup_repository() methods in test classes.

    Args:
        tmp_path: Pytest temporary directory.
        monkeypatch: Pytest monkeypatch for environment isolation.

    Returns:
        Path: The repository root directory.
    """
    # Create separate directories for app config and repository
    app_config_dir = tmp_path / "app_config"
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    # Set up .docman directory structure
    docman_dir = repo_dir / ".docman"
    docman_dir.mkdir()
    (docman_dir / "config.yaml").touch()
    (docman_dir / "instructions.md").write_text("Test organization instructions")

    # Isolate app config
    monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(app_config_dir))

    # Change to repository directory for convenience
    monkeypatch.chdir(repo_dir)

    return repo_dir


@pytest.fixture
def llm_provider_mock(monkeypatch: MonkeyPatch):
    """Provide a pre-configured LLM provider mock.

    This fixture eliminates repetitive LLM provider mocking setup in integration tests.
    The mock is configured to return successful suggestions by default.

    Args:
        monkeypatch: Pytest monkeypatch for patching.

    Returns:
        Mock: A configured LLM provider mock.
    """
    from unittest.mock import Mock

    mock_provider = Mock()
    mock_provider.supports_structured_output = True
    mock_provider.generate_suggestions.return_value = {
        "suggested_directory_path": "documents/reports",
        "suggested_filename": "test_report.pdf",
        "reason": "Test suggestion",
    }
    mock_provider.test_connection.return_value = True

    # Patch the get_llm_provider function
    def mock_get_llm_provider(config, api_key):
        return mock_provider

    monkeypatch.setattr("docman.cli.get_llm_provider", mock_get_llm_provider)

    return mock_provider


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
