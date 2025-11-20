"""Integration tests for the 'docman status' command."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from docman.cli import main
from docman.database import ensure_database, get_session
from docman.models import Document, DocumentCopy, Operation


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
            pending_op = Operation(
                document_copy_id=copy.id,
                suggested_directory_path=suggested_dir,
                suggested_filename=suggested_filename,
                reason=reason,
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
        )
        self.create_pending_operation(
            str(repo_dir),
            "doc2.docx",
            "memos",
            "meeting-notes.docx",
            "Meeting minutes",
        )

        result = cli_runner.invoke(main, ["status"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Pending Operations (2):" in result.output
        assert "doc1.pdf" in result.output
        assert "reports/annual-report.pdf" in result.output
        assert "Financial report" in result.output
        assert "doc2.docx" in result.output
        assert "memos/meeting-notes.docx" in result.output
        assert "Meeting minutes" in result.output

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

    def test_status_groups_duplicates(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that status groups duplicate files by content hash."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test files
        (repo_dir / "inbox" / "report.pdf").parent.mkdir(parents=True, exist_ok=True)
        (repo_dir / "inbox" / "report.pdf").touch()
        (repo_dir / "backup" / "report.pdf").parent.mkdir(parents=True, exist_ok=True)
        (repo_dir / "backup" / "report.pdf").touch()

        # Create document and copies for duplicate files
        ensure_database()
        session_gen = get_session()
        session = next(session_gen)
        try:
            # Create one document with two copies (duplicates)
            doc = Document(content_hash="hash_duplicate", content="Duplicate content")
            session.add(doc)
            session.flush()

            # Create two copies
            copy1 = DocumentCopy(
                document_id=doc.id,
                repository_path=str(repo_dir),
                file_path="inbox/report.pdf",
            )
            copy2 = DocumentCopy(
                document_id=doc.id,
                repository_path=str(repo_dir),
                file_path="backup/report.pdf",
            )
            session.add_all([copy1, copy2])
            session.flush()

            # Create pending operations for both copies
            op1 = Operation(
                document_copy_id=copy1.id,
                suggested_directory_path="reports",
                suggested_filename="annual-report.pdf",
                reason="Test reason",
                prompt_hash="hash1",
            )
            op2 = Operation(
                document_copy_id=copy2.id,
                suggested_directory_path="reports",
                suggested_filename="annual-report.pdf",
                reason="Test reason",
                prompt_hash="hash2",
            )
            session.add_all([op1, op2])
            session.commit()
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

        result = cli_runner.invoke(main, ["status"], catch_exceptions=False)

        assert result.exit_code == 0
        # Check for duplicate group header
        assert "DUPLICATE GROUP" in result.output
        assert "2 copies" in result.output
        assert "hash_dup" in result.output  # First 8 chars of hash
        # Check for sub-numbering (e.g., [1a], [1b])
        assert "[1a]" in result.output
        assert "[1b]" in result.output
        # Check for tip about dedupe command
        assert "docman dedupe" in result.output

    def test_status_shows_conflict_warnings(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that status shows conflict warnings for files with same target."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test files
        (repo_dir / "file1.pdf").touch()
        (repo_dir / "file2.pdf").touch()

        # Create two separate documents (not duplicates) with same target
        ensure_database()
        session_gen = get_session()
        session = next(session_gen)
        try:
            # Create two different documents
            doc1 = Document(content_hash="hash1", content="Content 1")
            doc2 = Document(content_hash="hash2", content="Content 2")
            session.add_all([doc1, doc2])
            session.flush()

            # Create copies
            copy1 = DocumentCopy(
                document_id=doc1.id,
                repository_path=str(repo_dir),
                file_path="file1.pdf",
            )
            copy2 = DocumentCopy(
                document_id=doc2.id,
                repository_path=str(repo_dir),
                file_path="file2.pdf",
            )
            session.add_all([copy1, copy2])
            session.flush()

            # Create pending operations with SAME target
            op1 = Operation(
                document_copy_id=copy1.id,
                suggested_directory_path="reports",
                suggested_filename="report.pdf",
                reason="Test reason",
                prompt_hash="hash1",
            )
            op2 = Operation(
                document_copy_id=copy2.id,
                suggested_directory_path="reports",
                suggested_filename="report.pdf",  # Same target!
                reason="Test reason",
                prompt_hash="hash2",
            )
            session.add_all([op1, op2])
            session.commit()
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

        result = cli_runner.invoke(main, ["status"], catch_exceptions=False)

        assert result.exit_code == 0
        # Check for conflict warning
        assert "CONFLICT" in result.output
        # Check for conflict summary
        assert "Files with conflicting targets:" in result.output

    def test_status_duplicate_summary_stats(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that status summary includes duplicate statistics."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create document with 3 copies (duplicates)
        ensure_database()
        session_gen = get_session()
        session = next(session_gen)
        try:
            doc = Document(content_hash="hash_dup", content="Duplicate content")
            session.add(doc)
            session.flush()

            # Create 3 copies
            for i in range(3):
                copy = DocumentCopy(
                    document_id=doc.id,
                    repository_path=str(repo_dir),
                    file_path=f"path{i}/file.pdf",
                )
                session.add(copy)
                session.flush()

                # Create pending operation
                op = Operation(
                    document_copy_id=copy.id,
                    suggested_directory_path="reports",
                    suggested_filename=f"report{i}.pdf",
                    reason="Test",
                    prompt_hash=f"hash{i}",
                )
                session.add(op)

            session.commit()
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

        result = cli_runner.invoke(main, ["status"], catch_exceptions=False)

        assert result.exit_code == 0
        # Check for duplicate stats in summary
        assert "Duplicate groups: 1" in result.output
        assert "3 total copies" in result.output
        assert "docman review --apply-all -y" in result.output
