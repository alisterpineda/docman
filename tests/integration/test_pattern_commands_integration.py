"""Integration tests for pattern management commands."""

from pathlib import Path
from click.testing import CliRunner
import pytest

from docman.cli import main


class TestPatternCommands:
    """Integration tests for docman pattern command group."""

    def setup_repository(self, path: Path) -> None:
        """Set up a docman repository for testing."""
        docman_dir = path / ".docman"
        docman_dir.mkdir()
        config_file = docman_dir / "config.yaml"
        config_file.touch()

    def test_pattern_add_creates_new_pattern(self, tmp_path, cli_runner):
        """Test adding a new variable pattern."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        result = cli_runner.invoke(
            main,
            ["pattern", "add", "year", "--desc", "4-digit year in YYYY format"],
            cwd=str(repo_dir),
        )

        assert result.exit_code == 0
        assert "Variable pattern 'year' saved" in result.output
        assert "4-digit year in YYYY format" in result.output

    def test_pattern_add_updates_existing_pattern(self, tmp_path, cli_runner):
        """Test updating an existing variable pattern."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        # Add pattern first
        cli_runner.invoke(
            main,
            ["pattern", "add", "year", "--desc", "Old description"],
            cwd=str(repo_dir),
        )

        # Update pattern
        result = cli_runner.invoke(
            main,
            ["pattern", "add", "year", "--desc", "New description"],
            cwd=str(repo_dir),
        )

        assert result.exit_code == 0
        assert "Variable pattern 'year' saved" in result.output
        assert "New description" in result.output

    def test_pattern_list_shows_all_patterns(self, tmp_path, cli_runner):
        """Test listing all variable patterns."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        # Add multiple patterns
        cli_runner.invoke(
            main,
            ["pattern", "add", "year", "--desc", "4-digit year"],
            cwd=str(repo_dir),
        )
        cli_runner.invoke(
            main,
            ["pattern", "add", "company", "--desc", "Company name"],
            cwd=str(repo_dir),
        )

        result = cli_runner.invoke(main, ["pattern", "list"], cwd=str(repo_dir))

        assert result.exit_code == 0
        assert "year" in result.output
        assert "4-digit year" in result.output
        assert "company" in result.output
        assert "Company name" in result.output

    def test_pattern_list_shows_message_when_empty(self, tmp_path, cli_runner):
        """Test listing patterns when none are defined."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        result = cli_runner.invoke(main, ["pattern", "list"], cwd=str(repo_dir))

        assert result.exit_code == 0
        assert "No variable patterns defined" in result.output

    def test_pattern_show_displays_specific_pattern(self, tmp_path, cli_runner):
        """Test showing a specific variable pattern."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        # Add pattern
        cli_runner.invoke(
            main,
            ["pattern", "add", "year", "--desc", "4-digit year in YYYY format"],
            cwd=str(repo_dir),
        )

        result = cli_runner.invoke(main, ["pattern", "show", "year"], cwd=str(repo_dir))

        assert result.exit_code == 0
        assert "year" in result.output
        assert "4-digit year in YYYY format" in result.output

    def test_pattern_show_error_for_nonexistent_pattern(self, tmp_path, cli_runner):
        """Test showing a non-existent pattern."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        result = cli_runner.invoke(main, ["pattern", "show", "nonexistent"], cwd=str(repo_dir))

        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_pattern_remove_deletes_pattern_with_confirmation(self, tmp_path, cli_runner):
        """Test removing a pattern with confirmation."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        # Add pattern
        cli_runner.invoke(
            main,
            ["pattern", "add", "year", "--desc", "4-digit year"],
            cwd=str(repo_dir),
        )

        # Remove with confirmation (yes flag)
        result = cli_runner.invoke(
            main, ["pattern", "remove", "year", "-y"], cwd=str(repo_dir)
        )

        assert result.exit_code == 0
        assert "removed" in result.output.lower()

        # Verify pattern is gone
        list_result = cli_runner.invoke(main, ["pattern", "list"], cwd=str(repo_dir))
        assert "year" not in list_result.output

    def test_pattern_remove_error_for_nonexistent_pattern(self, tmp_path, cli_runner):
        """Test removing a non-existent pattern."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        result = cli_runner.invoke(
            main, ["pattern", "remove", "nonexistent", "-y"], cwd=str(repo_dir)
        )

        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_pattern_commands_require_repository(self, tmp_path, cli_runner):
        """Test that pattern commands fail outside a repository."""
        non_repo_dir = tmp_path / "non_repo"
        non_repo_dir.mkdir()

        result = cli_runner.invoke(
            main,
            ["pattern", "add", "year", "--desc", "Test"],
            cwd=str(non_repo_dir),
        )

        assert result.exit_code != 0
        assert "not in a docman repository" in result.output.lower()

    def test_pattern_add_with_special_characters(self, tmp_path, cli_runner):
        """Test adding a pattern with special characters in name."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        result = cli_runner.invoke(
            main,
            ["pattern", "add", "special_name-123", "--desc", "Special pattern"],
            cwd=str(repo_dir),
        )

        assert result.exit_code == 0
        assert "special_name-123" in result.output


@pytest.fixture
def cli_runner():
    """Provide a CLI runner for testing."""
    return CliRunner()
