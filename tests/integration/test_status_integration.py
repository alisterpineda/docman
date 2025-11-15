"""Integration tests for the 'docman status' command."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from conftest import setup_repository
from docman.cli import main
from docman.database import ensure_database, get_session
from docman.models import Document, DocumentCopy, Operation, OperationStatus


@pytest.mark.integration
class TestDocmanStatus:
    """Integration tests for docman status command."""

    def test_status_no_pending_operations(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test status when no pending operations exist."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)
        monkeypatch.chdir(repo_dir)

        result = cli_runner.invoke(main, ["status"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "No pending operations found." in result.output

    def test_status_shows_pending_operations(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_pending_operation,
    ) -> None:
        """Test that status displays pending operations correctly."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)
        monkeypatch.chdir(repo_dir)

        # Create test files
        (repo_dir / "doc1.pdf").touch()
        (repo_dir / "doc2.docx").touch()

        # Create pending operations
        create_pending_operation(
            str(repo_dir),
            "doc1.pdf",
            "reports",
            "annual-report.pdf",
            "Financial report",
        )
        create_pending_operation(
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
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_pending_operation,
    ) -> None:
        """Test status filtering by specific file."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)
        monkeypatch.chdir(repo_dir)

        # Create test files
        (repo_dir / "doc1.pdf").touch()
        (repo_dir / "doc2.pdf").touch()

        # Create pending operations
        create_pending_operation(
            str(repo_dir), "doc1.pdf", "reports", "report1.pdf"
        )
        create_pending_operation(
            str(repo_dir), "doc2.pdf", "reports", "report2.pdf"
        )

        result = cli_runner.invoke(main, ["status", "doc1.pdf"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Pending Operations (1):" in result.output
        assert "doc1.pdf" in result.output
        assert "doc2.pdf" not in result.output

    def test_status_filter_by_directory(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_pending_operation,
    ) -> None:
        """Test status filtering by directory."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)
        monkeypatch.chdir(repo_dir)

        # Create test files in different directories
        docs_dir = repo_dir / "docs"
        docs_dir.mkdir()
        (docs_dir / "doc1.pdf").touch()

        other_dir = repo_dir / "other"
        other_dir.mkdir()
        (other_dir / "doc2.pdf").touch()

        # Create pending operations
        create_pending_operation(
            str(repo_dir), "docs/doc1.pdf", "reports", "report1.pdf"
        )
        create_pending_operation(
            str(repo_dir), "other/doc2.pdf", "memos", "memo1.pdf"
        )

        result = cli_runner.invoke(main, ["status", "docs"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Pending Operations (1):" in result.output
        assert "docs/doc1.pdf" in result.output
        assert "other/doc2.pdf" not in result.output

    def test_status_no_change_operations(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_pending_operation,
    ) -> None:
        """Test status when operation suggests no change (file already at target)."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)
        monkeypatch.chdir(repo_dir)

        # Create test file
        (repo_dir / "doc.pdf").touch()

        # Create pending operation with same path
        create_pending_operation(
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
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_pending_operation,
    ) -> None:
        """Test that status shows suggestions for applying operations."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)
        monkeypatch.chdir(repo_dir)

        # Create test file and pending operation
        (repo_dir / "doc.pdf").touch()
        create_pending_operation(
            str(repo_dir), "doc.pdf", "reports", "report.pdf"
        )

        result = cli_runner.invoke(main, ["status"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "To apply these changes, run:" in result.output

    def test_status_groups_duplicates(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that status groups duplicate files by content hash."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)
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
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)
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
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)
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
        assert "docman apply --all -y" in result.output
