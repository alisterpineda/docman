"""Integration tests for database initialization with CLI commands."""

from pathlib import Path

import pytest
from click.testing import CliRunner
from sqlalchemy import inspect

from docman.cli import main
from docman.database import get_database_path, get_engine


@pytest.fixture
def cli_runner() -> CliRunner:
    """Fixture that provides a Click CLI test runner."""
    return CliRunner()


def test_database_initialized_on_cli_startup(
    cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Test that the database is initialized when actual commands are run."""
    app_config_dir = tmp_path / "app_config"
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(app_config_dir))

    # Run the init command (which triggers main() body)
    result = cli_runner.invoke(main, ["init", str(project_dir)])

    assert result.exit_code == 0

    # Check that the database was created
    db_path = app_config_dir / "docman.db"
    assert db_path.exists()

    # Check that migrations were run
    engine = get_engine()
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "documents" in tables


def test_database_initialization_with_init_command(
    cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Test that database is initialized when running init command."""
    app_config_dir = tmp_path / "app_config"
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(app_config_dir))

    # Run init command
    result = cli_runner.invoke(main, ["init", str(project_dir)])

    assert result.exit_code == 0
    assert "Initialized empty docman repository" in result.output

    # Verify database was created
    db_path = app_config_dir / "docman.db"
    assert db_path.exists()


def test_database_persists_across_multiple_cli_calls(
    cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Test that database persists and is reused across multiple CLI invocations."""
    app_config_dir = tmp_path / "app_config"
    project_dir1 = tmp_path / "project1"
    project_dir2 = tmp_path / "project2"
    project_dir1.mkdir()
    project_dir2.mkdir()

    monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(app_config_dir))

    # First CLI call
    result1 = cli_runner.invoke(main, ["init", str(project_dir1)])
    assert result1.exit_code == 0

    db_path = app_config_dir / "docman.db"
    initial_mtime = db_path.stat().st_mtime

    # Second CLI call
    result2 = cli_runner.invoke(main, ["init", str(project_dir2)])
    assert result2.exit_code == 0

    # Database should still exist and not be recreated
    assert db_path.exists()
    # The modification time should be the same or later (not recreated from scratch)
    assert db_path.stat().st_mtime >= initial_mtime


def test_database_initialization_handles_permissions_gracefully(
    cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Test that database initialization errors are handled gracefully."""
    # Create a read-only directory
    readonly_dir = tmp_path / "readonly"
    readonly_dir.mkdir()
    readonly_dir.chmod(0o444)  # Read-only

    project_dir = tmp_path / "project"
    project_dir.mkdir()

    monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(readonly_dir))

    try:
        # This should show a warning but not crash
        result = cli_runner.invoke(main, ["init", str(project_dir)])

        # The CLI should still work even if DB init fails
        # (it will show a warning but continue with the init command)
        assert "Warning: Failed to initialize" in result.output
    finally:
        # Cleanup: restore permissions
        readonly_dir.chmod(0o755)


def test_database_schema_matches_models(
    cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Test that the database schema matches the model definitions."""
    app_config_dir = tmp_path / "app_config"
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(app_config_dir))

    # Initialize database via CLI
    result = cli_runner.invoke(main, ["init", str(project_dir)])
    assert result.exit_code == 0

    # Inspect the schema
    engine = get_engine()
    inspector = inspect(engine)

    # Check documents table
    columns = inspector.get_columns("documents")
    column_info = {col["name"]: col for col in columns}

    # Verify column names
    assert "id" in column_info
    assert "file_path" in column_info
    assert "content" in column_info
    assert "createdAt" in column_info

    # Verify column types
    assert "INTEGER" in str(column_info["id"]["type"]).upper()
    assert "VARCHAR" in str(column_info["file_path"]["type"]).upper() or "TEXT" in str(
        column_info["file_path"]["type"]
    ).upper()
    assert "TEXT" in str(column_info["content"]["type"]).upper()
    assert "DATETIME" in str(column_info["createdAt"]["type"]).upper() or "TIMESTAMP" in str(
        column_info["createdAt"]["type"]
    ).upper()

    # Verify primary key
    pk_constraint = inspector.get_pk_constraint("documents")
    assert "id" in pk_constraint["constrained_columns"]

    # Verify nullable constraints
    assert column_info["id"]["nullable"] is False
    assert column_info["file_path"]["nullable"] is False
    assert column_info["content"]["nullable"] is True
    assert column_info["createdAt"]["nullable"] is False
