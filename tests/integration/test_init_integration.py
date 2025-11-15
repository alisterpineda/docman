"""Integration tests for the 'docman init' command."""

from pathlib import Path

from click.testing import CliRunner
from conftest import assert_docman_initialized

from docman.cli import main


class TestDocmanInit:
    """Integration tests for docman init command with real filesystem operations."""

    def test_init_success(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Test successful initialization creates complete structure with correct output."""
        result = cli_runner.invoke(main, ["init", str(tmp_path)])

        # Verify exit code
        assert result.exit_code == 0

        # Verify complete structure
        assert_docman_initialized(tmp_path)

        # Verify success message with absolute path
        expected_path = tmp_path / ".docman"
        assert f"Initialized empty docman repository in {expected_path}/" in result.output

        # Verify config is created empty
        config_file = tmp_path / ".docman" / "config.yaml"
        assert config_file.read_text() == ""

        # Verify "Next steps" guidance is shown
        assert "Next steps:" in result.output
        assert "Define variable patterns: docman pattern add" in result.output
        assert "Define folder structure: docman define" in result.output
        assert "Scan documents: docman scan -r" in result.output
        assert "Generate suggestions: docman plan" in result.output

        # Verify instructions.md is NOT created
        instructions_file = tmp_path / ".docman" / "instructions.md"
        assert not instructions_file.exists()

    def test_init_idempotency(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Test that re-initializing multiple times is safe and shows appropriate message."""
        # First initialization
        result1 = cli_runner.invoke(main, ["init", str(tmp_path)])
        assert result1.exit_code == 0

        # Re-initialize multiple times
        for _ in range(3):
            result = cli_runner.invoke(main, ["init", str(tmp_path)])
            assert result.exit_code == 0
            expected_path = tmp_path / ".docman"
            assert f"docman repository already exists in {expected_path}/" in result.output

        # Structure should still be valid
        assert_docman_initialized(tmp_path)

    def test_init_nonexistent_directory(self, cli_runner: CliRunner) -> None:
        """Test that init fails gracefully when directory doesn't exist."""
        nonexistent = "/path/that/does/not/exist"
        result = cli_runner.invoke(main, ["init", nonexistent])

        assert result.exit_code == 1
        assert "Error" in result.output
        assert "does not exist" in result.output

    def test_init_path_is_file(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test that init fails when path is a file, not a directory."""
        # Create a file
        test_file = tmp_path / "testfile.txt"
        test_file.touch()

        result = cli_runner.invoke(main, ["init", str(test_file)])

        assert result.exit_code == 1
        assert "Error" in result.output
        assert "is not a directory" in result.output

    def test_init_path_handling(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test that init handles default, relative, and nested paths correctly."""
        with cli_runner.isolated_filesystem(temp_dir=tmp_path):
            # Test default directory (current dir)
            result = cli_runner.invoke(main, ["init"])
            assert result.exit_code == 0
            assert_docman_initialized(Path.cwd())

            # Test relative path
            subdir_name = "subdir"
            Path(subdir_name).mkdir()
            result = cli_runner.invoke(main, ["init", subdir_name])
            assert result.exit_code == 0
            assert_docman_initialized(Path.cwd() / subdir_name)

        # Test nested paths
        nested_dir = tmp_path / "level1" / "level2" / "level3"
        nested_dir.mkdir(parents=True)
        result = cli_runner.invoke(main, ["init", str(nested_dir)])
        assert result.exit_code == 0
        assert_docman_initialized(nested_dir)

    def test_init_preserves_existing_files(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test that init doesn't affect other files in the directory."""
        # Create some existing files
        existing_file = tmp_path / "existing.txt"
        existing_file.write_text("important data")
        existing_dir = tmp_path / "existing_dir"
        existing_dir.mkdir()

        result = cli_runner.invoke(main, ["init", str(tmp_path)])

        assert result.exit_code == 0
        # Check that existing files are preserved
        assert existing_file.exists()
        assert existing_file.read_text() == "important data"
        assert existing_dir.exists()
        assert existing_dir.is_dir()

    def test_init_permission_error_handling(
        self, cli_runner: CliRunner, tmp_path: Path, mocker
    ) -> None:
        """Test that init handles permission errors gracefully."""
        # Mock mkdir to raise PermissionError
        mocker.patch(
            "pathlib.Path.mkdir",
            side_effect=PermissionError("Permission denied"),
        )

        result = cli_runner.invoke(main, ["init", str(tmp_path)])

        assert result.exit_code == 1
        assert "Error" in result.output
        assert "Permission denied" in result.output

    def test_init_generic_exception_handling(
        self, cli_runner: CliRunner, tmp_path: Path, mocker
    ) -> None:
        """Test that init handles unexpected exceptions gracefully."""
        # Mock touch to raise a generic exception
        mocker.patch(
            "pathlib.Path.touch",
            side_effect=RuntimeError("Unexpected error"),
        )

        result = cli_runner.invoke(main, ["init", str(tmp_path)])

        assert result.exit_code == 1
        assert "Error" in result.output
        assert "Failed to initialize repository" in result.output
