"""Integration tests for app config initialization."""

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from docman.cli import main
from docman.config import get_app_config_path


class TestAppConfigIntegration:
    """Integration tests for app-level config initialization.

    Note: Basic app config creation and persistence are tested in unit tests.
    These integration tests focus on command-specific behaviors.
    """

    def test_app_config_not_created_on_version_command(self, tmp_path: Path) -> None:
        """Test that app config is NOT created when running --version.

        --version is an eager option that exits before main() executes.
        """
        # Set up custom config dir for testing
        config_dir = tmp_path / "system_config"
        env_vars = {"DOCMAN_APP_CONFIG_DIR": str(config_dir)}

        # Run version command
        runner = CliRunner()
        result = runner.invoke(main, ["--version"], env=env_vars)

        # Verify command succeeded
        assert result.exit_code == 0

        # Verify app config was NOT created (--version exits early)
        config_path = config_dir / "config.yaml"
        assert not config_path.exists()

    def test_app_config_not_created_on_help_command(self, tmp_path: Path) -> None:
        """Test that app config is NOT created when running --help.

        --help is an eager option that exits before main() executes.
        """
        # Set up custom config dir for testing
        config_dir = tmp_path / "system_config"
        env_vars = {"DOCMAN_APP_CONFIG_DIR": str(config_dir)}

        # Run help command
        runner = CliRunner()
        result = runner.invoke(main, ["--help"], env=env_vars)

        # Verify command succeeded
        assert result.exit_code == 0

        # Verify app config was NOT created (--help exits early)
        config_path = config_dir / "config.yaml"
        assert not config_path.exists()

    @pytest.mark.skipif(
        getattr(os, "geteuid", lambda: 1)() == 0, reason="Permission tests don't work as root"
    )
    def test_permission_error_shows_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that permission errors show a warning but don't crash."""
        # Set up a config dir that will cause permission error
        config_dir = tmp_path / "readonly_config"
        config_dir.mkdir(parents=True)
        config_dir.chmod(0o444)  # Read-only

        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(config_dir))

        try:
            # Run init command
            runner = CliRunner()
            with runner.isolated_filesystem(temp_dir=tmp_path):
                result = runner.invoke(main, ["init"], input="n\n")

            # Command should complete but show warning
            # Exit code might be 0 or 1 depending on whether init succeeds
            assert "Warning" in result.output or "Error" in result.output
        finally:
            # Clean up: restore permissions
            config_dir.chmod(0o755)

    def test_system_and_project_configs_are_separate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that system and project configs exist separately."""
        # Set up custom app config dir
        system_config_dir = tmp_path / "system_config"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(system_config_dir))

        # Run init command in a project directory
        runner = CliRunner()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        result = runner.invoke(main, ["init", str(project_dir)], input="n\n")
        assert result.exit_code == 0

        # Verify both configs exist
        system_config_path = system_config_dir / "config.yaml"
        project_config_path = project_dir / ".docman" / "config.yaml"

        assert system_config_path.exists()
        assert project_config_path.exists()

        # Verify they are different files
        assert system_config_path != project_config_path
