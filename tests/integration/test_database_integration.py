"""Integration tests for database initialization with CLI commands.

Note: Database creation, schema validation, and idempotency are tested in unit tests.
These integration tests focus on CLI-specific error handling and edge cases.
"""

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from docman.cli import main


@pytest.fixture
def cli_runner() -> CliRunner:
    """Fixture that provides a Click CLI test runner."""
    return CliRunner()


@pytest.mark.skipif(
    getattr(os, "geteuid", lambda: 1)() == 0, reason="Permission tests don't work as root"
)
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
        result = cli_runner.invoke(main, ["init", str(project_dir)], input="n\n")

        # The CLI should still work even if DB init fails
        # (it will show a warning but continue with the init command)
        assert "Warning: Failed to initialize" in result.output
    finally:
        # Cleanup: restore permissions
        readonly_dir.chmod(0o755)
