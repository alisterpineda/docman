"""Integration tests for the 'docman status' command."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from docman.cli import main
from docman.database import ensure_database, get_session
from docman.models import Document, DocumentCopy, PendingOperation


class TestDocmanStatus:
    """Integration tests for docman status command."""

    def setup_repository(self, path: Path) -> None:
        """Set up a docman repository for testing."""
        docman_dir = path / ".docman"
        docman_dir.mkdir()
        config_file = docman_dir / "config.yaml"
        config_file.touch()

        # Create instructions file (required)
        instructions_file = docman_dir / "instructions.md"
        instructions_file.write_text("Test organization instructions")

    def setup_isolated_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """Set up isolated environment with separate app config and repository."""
        app_config_dir = tmp_path / "app_config"
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(app_config_dir))
        self.setup_repository(repo_dir)
        return repo_dir

    def create_pending_operation(
        self,
        repo_path: str,
        file_path: str,
        suggested_dir: str,
        suggested_filename: str,
        reason: str = "Test reason",
        confidence: float = 0.85,
    ) -> None:
        """Helper to create a pending operation in the database."""
        ensure_database()
        session_gen = get_session()
        session = next(session_gen)
        try:
            # Create document
            doc = Document(content_hash=f"hash_{file_path}", content="Test content")
            session.add(doc)
            session.flush()

            # Create document copy
            copy = DocumentCopy(
                document_id=doc.id,
                repository_path=repo_path,
                file_path=file_path,
            )
            session.add(copy)
            session.flush()

            # Create pending operation
            pending_op = PendingOperation(
                document_copy_id=copy.id,
                suggested_directory_path=suggested_dir,
                suggested_filename=suggested_filename,
                reason=reason,
                confidence=confidence,
                prompt_hash="test_hash",
            )
            session.add(pending_op)
            session.commit()
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_status_no_pending_operations(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test status when no pending operations exist."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        result = cli_runner.invoke(main, ["status"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "No pending operations found." in result.output

    def test_status_shows_pending_operations(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that status displays pending operations correctly."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test files
        (repo_dir / "doc1.pdf").touch()
        (repo_dir / "doc2.docx").touch()

        # Create pending operations
        self.create_pending_operation(
            str(repo_dir),
            "doc1.pdf",
            "reports",
            "annual-report.pdf",
            "Financial report",
            0.9,
        )
        self.create_pending_operation(
            str(repo_dir),
            "doc2.docx",
            "memos",
            "meeting-notes.docx",
            "Meeting minutes",
            0.75,
        )

        result = cli_runner.invoke(main, ["status"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Pending Operations (2):" in result.output
        assert "doc1.pdf" in result.output
        assert "reports/annual-report.pdf" in result.output
        assert "Financial report" in result.output
        assert "90%" in result.output
        assert "doc2.docx" in result.output
        assert "memos/meeting-notes.docx" in result.output
        assert "Meeting minutes" in result.output
        assert "75%" in result.output

    def test_status_filter_by_file(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test status filtering by specific file."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test files
        (repo_dir / "doc1.pdf").touch()
        (repo_dir / "doc2.pdf").touch()

        # Create pending operations
        self.create_pending_operation(
            str(repo_dir), "doc1.pdf", "reports", "report1.pdf"
        )
        self.create_pending_operation(
            str(repo_dir), "doc2.pdf", "reports", "report2.pdf"
        )

        result = cli_runner.invoke(main, ["status", "doc1.pdf"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Pending Operations (1):" in result.output
        assert "doc1.pdf" in result.output
        assert "doc2.pdf" not in result.output

    def test_status_filter_by_directory(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test status filtering by directory."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test files in different directories
        docs_dir = repo_dir / "docs"
        docs_dir.mkdir()
        (docs_dir / "doc1.pdf").touch()

        other_dir = repo_dir / "other"
        other_dir.mkdir()
        (other_dir / "doc2.pdf").touch()

        # Create pending operations
        self.create_pending_operation(
            str(repo_dir), "docs/doc1.pdf", "reports", "report1.pdf"
        )
        self.create_pending_operation(
            str(repo_dir), "other/doc2.pdf", "memos", "memo1.pdf"
        )

        result = cli_runner.invoke(main, ["status", "docs"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Pending Operations (1):" in result.output
        assert "docs/doc1.pdf" in result.output
        assert "other/doc2.pdf" not in result.output

    def test_status_confidence_colors(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that confidence scores are displayed (color coding tested visually)."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test files
        (repo_dir / "high.pdf").touch()
        (repo_dir / "medium.pdf").touch()
        (repo_dir / "low.pdf").touch()

        # Create pending operations with different confidence levels
        self.create_pending_operation(
            str(repo_dir), "high.pdf", "reports", "high.pdf", confidence=0.95
        )
        self.create_pending_operation(
            str(repo_dir), "medium.pdf", "reports", "medium.pdf", confidence=0.7
        )
        self.create_pending_operation(
            str(repo_dir), "low.pdf", "reports", "low.pdf", confidence=0.4
        )

        result = cli_runner.invoke(main, ["status"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "95%" in result.output
        assert "70%" in result.output
        assert "40%" in result.output

    def test_status_no_change_operations(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test status when operation suggests no change (file already at target)."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test file
        (repo_dir / "doc.pdf").touch()

        # Create pending operation with same path
        self.create_pending_operation(
            str(repo_dir), "doc.pdf", "", "doc.pdf", "Already in correct location"
        )

        result = cli_runner.invoke(main, ["status"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "(no change)" in result.output

    def test_status_outside_repository(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that status fails when not in a repository."""
        monkeypatch.chdir(tmp_path)

        result = cli_runner.invoke(main, ["status"])

        assert result.exit_code == 1
        assert "Error: Not in a docman repository" in result.output

    def test_status_shows_apply_suggestions(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that status shows suggestions for applying operations."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test file and pending operation
        (repo_dir / "doc.pdf").touch()
        self.create_pending_operation(
            str(repo_dir), "doc.pdf", "reports", "report.pdf"
        )

        result = cli_runner.invoke(main, ["status"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "To apply these changes, run:" in result.output
        assert "docman apply --all -y" in result.output
