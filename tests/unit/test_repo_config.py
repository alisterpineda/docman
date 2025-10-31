"""Unit tests for repo_config module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docman.repo_config import (
    edit_instructions_interactive,
    get_instructions_path,
    load_instructions,
    save_instructions,
)


class TestGetInstructionsPath:
    """Tests for get_instructions_path function."""

    def test_returns_correct_path(self, tmp_path: Path) -> None:
        """Test that function returns correct path."""
        result = get_instructions_path(tmp_path)
        expected = tmp_path / ".docman" / "instructions.md"
        assert result == expected


class TestLoadInstructions:
    """Tests for load_instructions function."""

    def test_file_does_not_exist(self, tmp_path: Path) -> None:
        """Test when instructions file doesn't exist."""
        result = load_instructions(tmp_path)
        assert result is None

    def test_empty_file(self, tmp_path: Path) -> None:
        """Test when instructions file is empty."""
        instructions_path = get_instructions_path(tmp_path)
        instructions_path.parent.mkdir(parents=True)
        instructions_path.write_text("")

        result = load_instructions(tmp_path)
        assert result is None

    def test_whitespace_only(self, tmp_path: Path) -> None:
        """Test when instructions file contains only whitespace."""
        instructions_path = get_instructions_path(tmp_path)
        instructions_path.parent.mkdir(parents=True)
        instructions_path.write_text("   \n\t  ")

        result = load_instructions(tmp_path)
        assert result is None

    def test_valid_content(self, tmp_path: Path) -> None:
        """Test when instructions file has valid content."""
        instructions_path = get_instructions_path(tmp_path)
        instructions_path.parent.mkdir(parents=True)
        content = "Test instructions"
        instructions_path.write_text(content)

        result = load_instructions(tmp_path)
        assert result == content

    def test_strips_whitespace(self, tmp_path: Path) -> None:
        """Test that leading/trailing whitespace is stripped."""
        instructions_path = get_instructions_path(tmp_path)
        instructions_path.parent.mkdir(parents=True)
        instructions_path.write_text("  Test instructions  \n")

        result = load_instructions(tmp_path)
        assert result == "Test instructions"


class TestSaveInstructions:
    """Tests for save_instructions function."""

    def test_creates_directory_if_not_exists(self, tmp_path: Path) -> None:
        """Test that .docman directory is created if it doesn't exist."""
        content = "Test instructions"
        save_instructions(tmp_path, content)

        instructions_path = get_instructions_path(tmp_path)
        assert instructions_path.parent.exists()
        assert instructions_path.parent.is_dir()

    def test_saves_content(self, tmp_path: Path) -> None:
        """Test that content is saved correctly."""
        content = "Test instructions"
        save_instructions(tmp_path, content)

        instructions_path = get_instructions_path(tmp_path)
        assert instructions_path.exists()
        assert instructions_path.read_text() == content

    def test_overwrites_existing_content(self, tmp_path: Path) -> None:
        """Test that existing content is overwritten."""
        instructions_path = get_instructions_path(tmp_path)
        instructions_path.parent.mkdir(parents=True)
        instructions_path.write_text("Old content")

        new_content = "New content"
        save_instructions(tmp_path, new_content)

        assert instructions_path.read_text() == new_content


class TestEditInstructionsInteractive:
    """Tests for edit_instructions_interactive function."""

    @patch("docman.repo_config.subprocess.run")
    @patch.dict("os.environ", {"EDITOR": "nano"})
    def test_uses_editor_from_environment(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Test that EDITOR environment variable is used."""
        mock_run.return_value = MagicMock(returncode=0)

        result = edit_instructions_interactive(tmp_path)

        assert result is True
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0][0] == "nano"

    @patch("docman.repo_config.subprocess.run")
    @patch.dict("os.environ", {}, clear=True)
    def test_falls_back_to_default_editor_unix(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Test fallback to default editor on Unix."""
        # Mock successful `which` command for nano
        def run_side_effect(cmd: list[str], **kwargs):  # type: ignore[no-untyped-def]
            if cmd[0] == "which":
                return MagicMock(returncode=0)
            return MagicMock(returncode=0)

        mock_run.side_effect = run_side_effect

        with patch("os.name", "posix"):
            result = edit_instructions_interactive(tmp_path)

        assert result is True

    @patch("docman.repo_config.subprocess.run")
    def test_creates_template_if_not_exists(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Test that template is created if instructions file doesn't exist."""
        mock_run.return_value = MagicMock(returncode=0)

        with patch.dict("os.environ", {"EDITOR": "nano"}):
            edit_instructions_interactive(tmp_path)

        instructions_path = get_instructions_path(tmp_path)
        assert instructions_path.exists()

        content = instructions_path.read_text()
        assert "Document Organization Instructions" in content
        assert "Examples:" in content

    @patch("docman.repo_config.subprocess.run")
    def test_does_not_overwrite_existing_file(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Test that existing instructions file is not overwritten."""
        instructions_path = get_instructions_path(tmp_path)
        instructions_path.parent.mkdir(parents=True)
        existing_content = "Existing instructions"
        instructions_path.write_text(existing_content)

        mock_run.return_value = MagicMock(returncode=0)

        with patch.dict("os.environ", {"EDITOR": "nano"}):
            edit_instructions_interactive(tmp_path)

        # Content should remain unchanged
        assert instructions_path.read_text() == existing_content

    @patch("docman.repo_config.subprocess.run")
    def test_returns_false_on_editor_failure(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Test that function returns False if editor fails."""
        mock_run.side_effect = FileNotFoundError()

        with patch.dict("os.environ", {"EDITOR": "nonexistent-editor"}):
            result = edit_instructions_interactive(tmp_path)

        assert result is False

    @patch("docman.repo_config.subprocess.run")
    @patch.dict("os.environ", {}, clear=True)
    def test_returns_false_when_no_editor_found(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Test that function returns False when no editor is found."""
        # Mock failed `which` commands for all editors
        mock_run.return_value = MagicMock(returncode=1)

        with patch("os.name", "posix"):
            result = edit_instructions_interactive(tmp_path)

        assert result is False
