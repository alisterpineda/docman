"""Integration tests for app config initialization."""

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from docman.cli import main
from docman.config import get_app_config_path


class TestAppConfigIntegration:
    """Integration tests for app-level config initialization."""

    def test_app_config_created_on_init_command(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that app config is created when running init command."""
        # Set up custom config dir for testing
        config_dir = tmp_path / "system_config"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(config_dir))

        # Run init command
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["init"], input="n\n")

        # Verify command succeeded
        assert result.exit_code == 0

        # Verify app config was created
        config_path = get_app_config_path()
        assert config_path.exists()
        assert config_path.is_file()

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

    def test_app_config_not_recreated_if_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that app config is not overwritten if it already exists."""
        # Set up custom config dir for testing
        config_dir = tmp_path / "system_config"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(config_dir))

        # Create config with custom content
        config_dir.mkdir(parents=True)
        config_path = config_dir / "config.yaml"
        original_content = "custom: data\npreserved: true\n"
        config_path.write_text(original_content)

        # Run init command
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["init"], input="n\n")

        # Verify command succeeded
        assert result.exit_code == 0

        # Verify original content was preserved
        assert config_path.read_text() == original_content

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

    def test_multiple_commands_use_same_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that multiple commands use the same app config."""
        # Set up custom config dir for testing
        config_dir = tmp_path / "system_config"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(config_dir))

        runner = CliRunner()

        # Run first command
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result1 = runner.invoke(main, ["init"], input="n\n")
        assert result1.exit_code == 0

        config_path = get_app_config_path()
        assert config_path.exists()

        # Get modification time
        mtime1 = config_path.stat().st_mtime

        # Run second command
        result2 = runner.invoke(main, ["--version"])
        assert result2.exit_code == 0

        # Config should still exist
        assert config_path.exists()

        # Modification time should be the same (not recreated)
        mtime2 = config_path.stat().st_mtime
        assert mtime1 == mtime2

    def test_env_var_override_respected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that DOCMAN_APP_CONFIG_DIR environment variable is respected."""
        # Set up custom config dir
        custom_dir = tmp_path / "my_custom_location"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(custom_dir))

        # Run command
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["init"], input="n\n")

        assert result.exit_code == 0

        # Verify config was created in custom location
        expected_path = custom_dir / "config.yaml"
        assert expected_path.exists()
        assert expected_path.is_file()

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
