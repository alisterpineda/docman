"""Integration tests for the 'docman debug-prompt' command."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from conftest import setup_repository
from docman.cli import main


@pytest.mark.integration
class TestDocmanDebugPrompt:
    """Integration tests for docman debug-prompt command."""

    def test_debug_prompt_file_not_found(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test debug-prompt with non-existent file."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)
        monkeypatch.chdir(repo_dir)

        result = cli_runner.invoke(main, ["debug-prompt", "nonexistent.pdf"])

        assert result.exit_code != 0
        assert "does not exist" in result.output

    def test_debug_prompt_unsupported_file_type(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test debug-prompt with unsupported file type."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)
        monkeypatch.chdir(repo_dir)

        # Create unsupported file
        unsupported_file = repo_dir / "test.xyz"
        unsupported_file.write_text("test")

        result = cli_runner.invoke(main, ["debug-prompt", "test.xyz"])

        assert result.exit_code != 0
        assert "Unsupported file type" in result.output

    def test_debug_prompt_outside_repository(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test debug-prompt with file outside repository."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)
        monkeypatch.chdir(repo_dir)

        # Create file outside repo
        outside_file = tmp_path / "outside.txt"
        outside_file.write_text("test")

        result = cli_runner.invoke(main, ["debug-prompt", str(outside_file)])

        assert result.exit_code != 0
        assert "outside the repository" in result.output

    def test_debug_prompt_no_instructions(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test debug-prompt without folder definitions."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        # Set up repository WITHOUT folder definitions
        docman_dir = repo_dir / ".docman"
        docman_dir.mkdir()
        config_file = docman_dir / "config.yaml"
        config_file.write_text("organization:\n  folders: {}\n")

        monkeypatch.chdir(repo_dir)

        # Create test file (use .md which is supported by docling)
        test_file = repo_dir / "test.md"
        test_file.write_text("# Test Content\n\nThis is test content.")

        result = cli_runner.invoke(main, ["debug-prompt", "test.md"])

        assert result.exit_code != 0
        assert "No folder definitions found" in result.output

    def test_debug_prompt_with_existing_document(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_scanned_document,
    ) -> None:
        """Test debug-prompt with document already in database."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)
        monkeypatch.chdir(repo_dir)

        # Create and scan test file
        create_scanned_document(
            repo_dir, "test.txt", "This is a test document with some content."
        )

        result = cli_runner.invoke(main, ["debug-prompt", "test.txt"])

        assert result.exit_code == 0
        assert "Using existing content from database" in result.output
        assert "DEBUG PROMPT OUTPUT" in result.output
        assert "SYSTEM PROMPT" in result.output
        assert "USER PROMPT" in result.output
        assert "test.txt" in result.output
        # Should show the system prompt content
        assert "document organization assistant" in result.output.lower()

    def test_debug_prompt_with_new_document(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test debug-prompt with new document (not in database)."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)
        monkeypatch.chdir(repo_dir)

        # Create test file (not in database, use .md which is supported by docling)
        test_file = repo_dir / "new_document.md"
        test_file.write_text("# New Document\n\nThis is a new test document.")

        result = cli_runner.invoke(main, ["debug-prompt", "new_document.md"])

        assert result.exit_code == 0
        assert "Extracting content from" in result.output
        assert "DEBUG PROMPT OUTPUT" in result.output
        assert "SYSTEM PROMPT" in result.output
        assert "USER PROMPT" in result.output
        assert "new_document.md" in result.output

    def test_debug_prompt_with_folder_definitions(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_scanned_document,
    ) -> None:
        """Test debug-prompt generates instructions from folder definitions."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)
        monkeypatch.chdir(repo_dir)

        # Add folder definitions to config
        config_file = repo_dir / ".docman" / "config.yaml"
        config_file.write_text(
            """organization:
  folders:
    Financial:
      description: Financial documents
      folders:
        Invoices:
          description: Invoice documents
  variable_patterns:
    year: "4-digit year in YYYY format"
"""
        )

        # Create and scan test file
        create_scanned_document(repo_dir, "test.txt", "Test content")

        result = cli_runner.invoke(main, ["debug-prompt", "test.txt"])

        assert result.exit_code == 0
        assert "DEBUG PROMPT OUTPUT" in result.output
        assert "SYSTEM PROMPT" in result.output
        assert "USER PROMPT" in result.output
        # Should include auto-generated instructions from folder definitions
        assert "Financial" in result.output or "Invoices" in result.output

    def test_debug_prompt_shows_metadata(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_scanned_document,
    ) -> None:
        """Test that debug-prompt shows useful metadata."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)
        monkeypatch.chdir(repo_dir)

        # Create and scan test file
        test_content = "This is test content for metadata checking."
        create_scanned_document(repo_dir, "test.txt", test_content)

        result = cli_runner.invoke(main, ["debug-prompt", "test.txt"])

        assert result.exit_code == 0
        # Check metadata is displayed
        assert "File: test.txt" in result.output
        assert "Content length:" in result.output
        assert "Structured output:" in result.output
