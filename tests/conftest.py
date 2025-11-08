"""Shared pytest fixtures and test utilities for docman."""

from pathlib import Path

import pytest
from click.testing import CliRunner
from pytest import MonkeyPatch


@pytest.fixture(autouse=True)
def isolate_app_config(tmp_path_factory: pytest.TempPathFactory, monkeypatch: MonkeyPatch) -> Path:
    """Automatically isolate app config directory for all tests.

    This fixture runs automatically for every test and ensures that tests
    never touch the real user app config directory or database.

    Args:
        tmp_path_factory: Pytest factory for creating temporary directories.
        monkeypatch: Pytest monkeypatch fixture for setting environment variables.

    Returns:
        Path: The isolated temporary app config directory for the test.
    """
    # Create a unique temporary directory for this test's app config
    isolated_config_dir = tmp_path_factory.mktemp("app_config")

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
