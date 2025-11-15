"""Integration tests for the 'docman debug-prompt' command."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from docman.cli import main
from docman.database import ensure_database, get_session
from docman.models import Document, DocumentCopy


@pytest.mark.integration
class TestDocmanDebugPrompt:
    """Integration tests for docman debug-prompt command."""

    def setup_repository(self, path: Path) -> None:
        """Set up a docman repository for testing."""
        docman_dir = path / ".docman"
        docman_dir.mkdir()
        config_file = docman_dir / "config.yaml"
        # Create folder definitions (required)
        config_content = """
organization:
  variable_patterns:
    year: "4-digit year in YYYY format"
    category: "Document category"
  folders:
    Documents:
      description: "Test documents folder"
      folders:
        Archive:
          description: "Archived documents"
"""
        config_file.write_text(config_content)

    def setup_isolated_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """Set up isolated environment with separate app config and repository."""
        app_config_dir = tmp_path / "app_config"
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(app_config_dir))
        self.setup_repository(repo_dir)
        return repo_dir

    def create_document_in_db(
        self, repo_path: str, file_path: str, content: str = "Test document content"
    ) -> None:
        """Helper to create a document in the database."""
        ensure_database()
        session_gen = get_session()
        session = next(session_gen)
        try:
            # Create document
            doc = Document(content_hash=f"hash_{file_path}", content=content)
            session.add(doc)
            session.flush()

            # Get actual file metadata if file exists
            full_path = Path(repo_path) / file_path
            stored_size = None
            stored_mtime = None
            if full_path.exists():
                stat = full_path.stat()
                stored_size = stat.st_size
                stored_mtime = stat.st_mtime

            # Create document copy with metadata
            copy = DocumentCopy(
                document_id=doc.id,
                repository_path=repo_path,
                file_path=file_path,
                stored_size=stored_size,
                stored_mtime=stored_mtime,
            )
            session.add(copy)
            session.commit()
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_debug_prompt_file_not_found(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test debug-prompt with non-existent file."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        result = cli_runner.invoke(main, ["debug-prompt", "nonexistent.pdf"])

        assert result.exit_code != 0
        assert "does not exist" in result.output

    def test_debug_prompt_unsupported_file_type(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test debug-prompt with unsupported file type."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
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
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
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
        app_config_dir = tmp_path / "app_config"
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(app_config_dir))

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
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test debug-prompt with document already in database."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test file
        test_file = repo_dir / "test.txt"
        test_file.write_text("This is a test document with some content.")

        # Add to database
        self.create_document_in_db(
            str(repo_dir), "test.txt", "This is a test document with some content."
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
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
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
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test debug-prompt generates instructions from folder definitions."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
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

        # Create test file
        test_file = repo_dir / "test.txt"
        test_file.write_text("Test content")

        # Add to database
        self.create_document_in_db(str(repo_dir), "test.txt", "Test content")

        result = cli_runner.invoke(main, ["debug-prompt", "test.txt"])

        assert result.exit_code == 0
        assert "DEBUG PROMPT OUTPUT" in result.output
        assert "SYSTEM PROMPT" in result.output
        assert "USER PROMPT" in result.output
        # Should include auto-generated instructions from folder definitions
        assert "Financial" in result.output or "Invoices" in result.output

    def test_debug_prompt_shows_metadata(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that debug-prompt shows useful metadata."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test file
        test_file = repo_dir / "test.txt"
        test_content = "This is test content for metadata checking."
        test_file.write_text(test_content)

        # Add to database
        self.create_document_in_db(str(repo_dir), "test.txt", test_content)

        result = cli_runner.invoke(main, ["debug-prompt", "test.txt"])

        assert result.exit_code == 0
        # Check metadata is displayed
        assert "File: test.txt" in result.output
        assert "Content length:" in result.output
        assert "Structured output:" in result.output
