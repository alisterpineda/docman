"""Integration tests for the 'docman reject' command."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from docman.cli import main
from docman.database import ensure_database, get_session
from docman.models import Document, DocumentCopy, PendingOperation


class TestDocmanReject:
    """Integration tests for docman reject command."""

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

    def test_reject_requires_all_or_path(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that reject requires either --all or a PATH argument."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        result = cli_runner.invoke(main, ["reject"])

        assert result.exit_code == 1
        assert "Error: Must specify either --all or a PATH" in result.output

    def test_reject_no_pending_operations(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test reject when no pending operations exist."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        result = cli_runner.invoke(main, ["reject", "--all", "-y"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "No pending operations found." in result.output

    def test_reject_all_operations(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test rejecting all operations."""
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

        result = cli_runner.invoke(main, ["reject", "--all", "-y"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Successfully rejected 2 pending operation(s)" in result.output

        # Verify pending operations were deleted
        session_gen = get_session()
        session = next(session_gen)
        try:
            pending_ops = session.query(PendingOperation).all()
            assert len(pending_ops) == 0

            # Verify documents and copies still exist
            docs = session.query(Document).all()
            assert len(docs) == 2
            copies = session.query(DocumentCopy).all()
            assert len(copies) == 2
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_reject_single_file(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test rejecting operation for a specific file."""
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

        result = cli_runner.invoke(
            main, ["reject", "doc1.pdf", "-y"], catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Successfully rejected 1 pending operation(s)" in result.output

        # Verify only doc1 operation was deleted
        session_gen = get_session()
        session = next(session_gen)
        try:
            pending_ops = session.query(PendingOperation).all()
            assert len(pending_ops) == 1

            # The remaining operation should be for doc2
            remaining_copy = session.query(DocumentCopy).filter_by(id=pending_ops[0].document_copy_id).first()
            assert remaining_copy.file_path == "doc2.pdf"
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_reject_directory_non_recursive(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test rejecting operations for a directory (non-recursive)."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test files in different directories
        docs_dir = repo_dir / "docs"
        docs_dir.mkdir()
        (docs_dir / "doc1.pdf").touch()

        nested_dir = docs_dir / "nested"
        nested_dir.mkdir()
        (nested_dir / "doc2.pdf").touch()

        other_dir = repo_dir / "other"
        other_dir.mkdir()
        (other_dir / "doc3.pdf").touch()

        # Create pending operations
        self.create_pending_operation(
            str(repo_dir), "docs/doc1.pdf", "reports", "report1.pdf"
        )
        self.create_pending_operation(
            str(repo_dir), "docs/nested/doc2.pdf", "reports", "report2.pdf"
        )
        self.create_pending_operation(
            str(repo_dir), "other/doc3.pdf", "reports", "report3.pdf"
        )

        result = cli_runner.invoke(
            main, ["reject", "docs/", "-y"], catch_exceptions=False
        )

        assert result.exit_code == 0
        # Should only reject doc1 (not the nested doc2)
        assert "Successfully rejected 1 pending operation(s)" in result.output

        # Verify correct operations were deleted
        session_gen = get_session()
        session = next(session_gen)
        try:
            pending_ops = session.query(PendingOperation).all()
            assert len(pending_ops) == 2

            # Remaining operations should be for nested/doc2 and other/doc3
            remaining_paths = {
                session.query(DocumentCopy).filter_by(id=op.document_copy_id).first().file_path
                for op in pending_ops
            }
            assert "docs/nested/doc2.pdf" in remaining_paths
            assert "other/doc3.pdf" in remaining_paths
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_reject_directory_recursive(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test rejecting operations for a directory (recursive)."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test files in different directories
        docs_dir = repo_dir / "docs"
        docs_dir.mkdir()
        (docs_dir / "doc1.pdf").touch()

        nested_dir = docs_dir / "nested"
        nested_dir.mkdir()
        (nested_dir / "doc2.pdf").touch()

        other_dir = repo_dir / "other"
        other_dir.mkdir()
        (other_dir / "doc3.pdf").touch()

        # Create pending operations
        self.create_pending_operation(
            str(repo_dir), "docs/doc1.pdf", "reports", "report1.pdf"
        )
        self.create_pending_operation(
            str(repo_dir), "docs/nested/doc2.pdf", "reports", "report2.pdf"
        )
        self.create_pending_operation(
            str(repo_dir), "other/doc3.pdf", "reports", "report3.pdf"
        )

        result = cli_runner.invoke(
            main, ["reject", "docs/", "-r", "-y"], catch_exceptions=False
        )

        assert result.exit_code == 0
        # Should reject both doc1 and nested/doc2
        assert "Successfully rejected 2 pending operation(s)" in result.output

        # Verify correct operations were deleted
        session_gen = get_session()
        session = next(session_gen)
        try:
            pending_ops = session.query(PendingOperation).all()
            assert len(pending_ops) == 1

            # Remaining operation should be for other/doc3
            remaining_copy = session.query(DocumentCopy).filter_by(id=pending_ops[0].document_copy_id).first()
            assert remaining_copy.file_path == "other/doc3.pdf"
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_reject_confirmation_prompt(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that reject prompts for confirmation without -y flag."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test file
        (repo_dir / "doc.pdf").touch()

        # Create pending operation
        self.create_pending_operation(
            str(repo_dir), "doc.pdf", "reports", "report.pdf"
        )

        # Test with "no" answer
        result = cli_runner.invoke(
            main, ["reject", "--all"], input="n\n", catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Reject (delete) 1 pending operation(s)?" in result.output
        assert "Aborted" in result.output

        # Verify operation was NOT deleted
        session_gen = get_session()
        session = next(session_gen)
        try:
            pending_ops = session.query(PendingOperation).all()
            assert len(pending_ops) == 1
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_reject_shows_file_list(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that reject shows list of files to be rejected."""
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

        result = cli_runner.invoke(
            main, ["reject", "--all"], input="n\n", catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "doc1.pdf" in result.output
        assert "doc2.pdf" in result.output

    def test_reject_many_files_truncates_list(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that reject truncates long file lists."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create many test files
        for i in range(15):
            (repo_dir / f"doc{i}.pdf").touch()
            self.create_pending_operation(
                str(repo_dir), f"doc{i}.pdf", "reports", f"report{i}.pdf"
            )

        result = cli_runner.invoke(
            main, ["reject", "--all"], input="n\n", catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "and" in result.output and "more" in result.output

    def test_reject_outside_repository(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that reject fails when not in a repository."""
        monkeypatch.chdir(tmp_path)

        result = cli_runner.invoke(main, ["reject", "--all", "-y"])

        assert result.exit_code == 1
        assert "Error: Not in a docman repository" in result.output

    def test_reject_nonexistent_path(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that reject handles nonexistent paths gracefully."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        result = cli_runner.invoke(main, ["reject", "nonexistent.pdf", "-y"])

        assert result.exit_code == 1
        assert "Error: Path 'nonexistent.pdf' does not exist" in result.output
