"""Integration tests for the 'docman apply' command."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from docman.cli import main
from docman.database import ensure_database, get_session
from docman.models import Document, DocumentCopy, PendingOperation


class TestDocmanApply:
    """Integration tests for docman apply command."""

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

    def test_apply_requires_all_or_path(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that apply requires either --all or a PATH argument."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        result = cli_runner.invoke(main, ["apply"])

        assert result.exit_code == 1
        assert "Error: Must specify either --all or a PATH" in result.output

    def test_apply_no_pending_operations(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test apply when no pending operations exist."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        result = cli_runner.invoke(main, ["apply", "--all", "-y"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "No pending operations found." in result.output

    def test_apply_all_moves_files(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that apply --all -y moves files correctly."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test files
        (repo_dir / "doc1.pdf").write_text("content1")
        (repo_dir / "doc2.pdf").write_text("content2")

        # Create pending operations
        self.create_pending_operation(
            str(repo_dir), "doc1.pdf", "reports", "annual-report.pdf"
        )
        self.create_pending_operation(
            str(repo_dir), "doc2.pdf", "memos", "meeting-notes.pdf"
        )

        result = cli_runner.invoke(main, ["apply", "--all", "-y"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Applied: 2" in result.output

        # Verify files were moved
        assert not (repo_dir / "doc1.pdf").exists()
        assert not (repo_dir / "doc2.pdf").exists()
        assert (repo_dir / "reports" / "annual-report.pdf").exists()
        assert (repo_dir / "memos" / "meeting-notes.pdf").exists()
        assert (repo_dir / "reports" / "annual-report.pdf").read_text() == "content1"
        assert (repo_dir / "memos" / "meeting-notes.pdf").read_text() == "content2"

    def test_apply_creates_directories(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that apply creates target directories."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test file
        (repo_dir / "doc.pdf").write_text("content")

        # Create pending operation with nested path
        self.create_pending_operation(
            str(repo_dir), "doc.pdf", "a/b/c", "doc.pdf"
        )

        result = cli_runner.invoke(main, ["apply", "--all", "-y"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Applied: 1" in result.output

        # Verify directory was created and file was moved
        assert (repo_dir / "a" / "b" / "c" / "doc.pdf").exists()
        assert (repo_dir / "a" / "b" / "c" / "doc.pdf").read_text() == "content"

    def test_apply_updates_database(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that apply updates DocumentCopy paths and deletes PendingOperation."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test file
        (repo_dir / "doc.pdf").write_text("content")

        # Create pending operation
        self.create_pending_operation(
            str(repo_dir), "doc.pdf", "reports", "report.pdf"
        )

        # Verify initial state
        session_gen = get_session()
        session = next(session_gen)
        try:
            copy = session.query(DocumentCopy).first()
            assert copy.file_path == "doc.pdf"

            pending_ops = session.query(PendingOperation).all()
            assert len(pending_ops) == 1
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

        # Apply operation
        result = cli_runner.invoke(main, ["apply", "--all", "-y"], catch_exceptions=False)
        assert result.exit_code == 0

        # Verify database was updated
        session_gen = get_session()
        session = next(session_gen)
        try:
            copy = session.query(DocumentCopy).first()
            assert copy.file_path == "reports/report.pdf"

            pending_ops = session.query(PendingOperation).all()
            assert len(pending_ops) == 0
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_apply_conflict_skip(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that apply skips files when target exists (default behavior)."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create source file
        (repo_dir / "doc.pdf").write_text("source content")

        # Create target file that already exists
        reports_dir = repo_dir / "reports"
        reports_dir.mkdir()
        (reports_dir / "report.pdf").write_text("existing content")

        # Create pending operation
        self.create_pending_operation(
            str(repo_dir), "doc.pdf", "reports", "report.pdf"
        )

        result = cli_runner.invoke(main, ["apply", "--all", "-y"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Skipped: 1" in result.output
        assert "Target file already exists" in result.output

        # Verify files were not changed
        assert (repo_dir / "doc.pdf").exists()
        assert (repo_dir / "doc.pdf").read_text() == "source content"
        assert (reports_dir / "report.pdf").read_text() == "existing content"

    def test_apply_conflict_force(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that apply overwrites files when --force is used."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create source file
        (repo_dir / "doc.pdf").write_text("source content")

        # Create target file that already exists
        reports_dir = repo_dir / "reports"
        reports_dir.mkdir()
        (reports_dir / "report.pdf").write_text("existing content")

        # Create pending operation
        self.create_pending_operation(
            str(repo_dir), "doc.pdf", "reports", "report.pdf"
        )

        result = cli_runner.invoke(
            main, ["apply", "--all", "-y", "--force"], catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Applied: 1" in result.output

        # Verify file was overwritten
        assert not (repo_dir / "doc.pdf").exists()
        assert (reports_dir / "report.pdf").read_text() == "source content"

    def test_apply_dry_run(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that --dry-run previews changes without applying them."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test file
        (repo_dir / "doc.pdf").write_text("content")

        # Create pending operation
        self.create_pending_operation(
            str(repo_dir), "doc.pdf", "reports", "report.pdf"
        )

        result = cli_runner.invoke(
            main, ["apply", "--all", "--dry-run"], catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "DRY RUN" in result.output
        assert "Would apply: 1" in result.output

        # Verify file was NOT moved
        assert (repo_dir / "doc.pdf").exists()
        assert not (repo_dir / "reports" / "report.pdf").exists()

        # Verify database was NOT changed
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

    def test_apply_filter_by_file(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test applying operations for a specific file."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test files
        (repo_dir / "doc1.pdf").write_text("content1")
        (repo_dir / "doc2.pdf").write_text("content2")

        # Create pending operations
        self.create_pending_operation(
            str(repo_dir), "doc1.pdf", "reports", "report1.pdf"
        )
        self.create_pending_operation(
            str(repo_dir), "doc2.pdf", "reports", "report2.pdf"
        )

        result = cli_runner.invoke(
            main, ["apply", "doc1.pdf", "-y"], catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Applied: 1" in result.output

        # Verify only doc1 was moved
        assert not (repo_dir / "doc1.pdf").exists()
        assert (repo_dir / "doc2.pdf").exists()
        assert (repo_dir / "reports" / "report1.pdf").exists()
        assert not (repo_dir / "reports" / "report2.pdf").exists()

    def test_apply_filter_by_directory(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test applying operations for files in a directory."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test files in different directories
        docs_dir = repo_dir / "docs"
        docs_dir.mkdir()
        (docs_dir / "doc1.pdf").write_text("content1")
        (docs_dir / "doc2.pdf").write_text("content2")

        other_dir = repo_dir / "other"
        other_dir.mkdir()
        (other_dir / "doc3.pdf").write_text("content3")

        # Create pending operations
        self.create_pending_operation(
            str(repo_dir), "docs/doc1.pdf", "reports", "report1.pdf"
        )
        self.create_pending_operation(
            str(repo_dir), "docs/doc2.pdf", "reports", "report2.pdf"
        )
        self.create_pending_operation(
            str(repo_dir), "other/doc3.pdf", "reports", "report3.pdf"
        )

        result = cli_runner.invoke(
            main, ["apply", "docs", "-y"], catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Applied: 2" in result.output

        # Verify only docs/ files were moved
        assert not (docs_dir / "doc1.pdf").exists()
        assert not (docs_dir / "doc2.pdf").exists()
        assert (other_dir / "doc3.pdf").exists()

    def test_apply_no_change_operation(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test applying operation when file is already at target location."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test file
        (repo_dir / "doc.pdf").write_text("content")

        # Create pending operation with same path (no change)
        self.create_pending_operation(str(repo_dir), "doc.pdf", "", "doc.pdf")

        result = cli_runner.invoke(main, ["apply", "--all", "-y"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "no change needed" in result.output
        assert "Skipped: 1" in result.output

        # Verify file is still at original location
        assert (repo_dir / "doc.pdf").exists()

        # Verify pending operation was deleted
        session_gen = get_session()
        session = next(session_gen)
        try:
            pending_ops = session.query(PendingOperation).all()
            assert len(pending_ops) == 0
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_apply_source_not_found(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that apply handles missing source files gracefully."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create pending operation but DON'T create the actual file
        self.create_pending_operation(
            str(repo_dir), "missing.pdf", "reports", "report.pdf"
        )

        result = cli_runner.invoke(main, ["apply", "--all", "-y"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Failed: 1" in result.output
        assert "Source file not found" in result.output

    def test_apply_interactive_mode_default(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that apply without -y flag runs in interactive mode."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test file
        (repo_dir / "doc.pdf").write_text("content")

        # Create pending operation
        self.create_pending_operation(
            str(repo_dir), "doc.pdf", "reports", "report.pdf"
        )

        # Test that interactive prompt appears and user can skip
        result = cli_runner.invoke(
            main, ["apply", "--all"], input="S\n", catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "[A]pply / [S]kip / [Q]uit / [H]elp" in result.output
        assert "Skipped by user" in result.output

        # Verify file was NOT moved
        assert (repo_dir / "doc.pdf").exists()

    def test_apply_outside_repository(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that apply fails when not in a repository."""
        monkeypatch.chdir(tmp_path)

        result = cli_runner.invoke(main, ["apply", "--all", "-y"])

        assert result.exit_code == 1
        assert "Error: Not in a docman repository" in result.output

    def test_apply_interactive_apply_operation(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test interactive mode with Apply (A) choice."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test file
        (repo_dir / "doc.pdf").write_text("content")

        # Create pending operation
        self.create_pending_operation(
            str(repo_dir), "doc.pdf", "reports", "report.pdf"
        )

        # Simulate user pressing 'A' for Apply
        result = cli_runner.invoke(
            main, ["apply", "--all"], input="A\n", catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "[A]pply / [S]kip / [Q]uit / [H]elp" in result.output
        assert "Applied: 1" in result.output

        # Verify file was moved
        assert not (repo_dir / "doc.pdf").exists()
        assert (repo_dir / "reports" / "report.pdf").exists()

    def test_apply_interactive_skip_operation(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test interactive mode with Skip (S) choice."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test file
        (repo_dir / "doc.pdf").write_text("content")

        # Create pending operation
        self.create_pending_operation(
            str(repo_dir), "doc.pdf", "reports", "report.pdf"
        )

        # Simulate user pressing 'S' for Skip
        result = cli_runner.invoke(
            main, ["apply", "--all"], input="S\n", catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Skipped by user" in result.output
        assert "Skipped: 1" in result.output

        # Verify file was NOT moved
        assert (repo_dir / "doc.pdf").exists()
        assert not (repo_dir / "reports" / "report.pdf").exists()

        # Verify pending operation still exists
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

    def test_apply_interactive_quit(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test interactive mode with Quit (Q) choice."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test files
        (repo_dir / "doc1.pdf").write_text("content1")
        (repo_dir / "doc2.pdf").write_text("content2")

        # Create pending operations
        self.create_pending_operation(
            str(repo_dir), "doc1.pdf", "reports", "report1.pdf"
        )
        self.create_pending_operation(
            str(repo_dir), "doc2.pdf", "reports", "report2.pdf"
        )

        # Simulate user pressing 'Q' for Quit on first operation
        result = cli_runner.invoke(
            main, ["apply", "--all"], input="Q\n", catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Quitting..." in result.output
        assert "Not processed (quit early): 1" in result.output

        # Verify files were NOT moved
        assert (repo_dir / "doc1.pdf").exists()
        assert (repo_dir / "doc2.pdf").exists()

    def test_apply_interactive_help(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test interactive mode with Help (H) choice."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test file
        (repo_dir / "doc.pdf").write_text("content")

        # Create pending operation
        self.create_pending_operation(
            str(repo_dir), "doc.pdf", "reports", "report.pdf"
        )

        # Simulate user pressing 'H' for Help, then 'A' to apply
        result = cli_runner.invoke(
            main, ["apply", "--all"], input="H\nA\n", catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Commands:" in result.output
        assert "[A]pply - Move this file" in result.output
        assert "[S]kip  - Skip this operation" in result.output
        assert "[Q]uit  - Stop processing" in result.output
        assert "Applied: 1" in result.output

    def test_apply_interactive_invalid_then_valid(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test interactive mode with invalid input followed by valid input."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test file
        (repo_dir / "doc.pdf").write_text("content")

        # Create pending operation
        self.create_pending_operation(
            str(repo_dir), "doc.pdf", "reports", "report.pdf"
        )

        # Simulate user entering invalid input, then valid 'A'
        result = cli_runner.invoke(
            main, ["apply", "--all"], input="X\nA\n", catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Invalid option" in result.output
        assert "Applied: 1" in result.output

    def test_apply_interactive_multiple_operations(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test interactive mode with multiple operations (mixed responses)."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test files
        (repo_dir / "doc1.pdf").write_text("content1")
        (repo_dir / "doc2.pdf").write_text("content2")
        (repo_dir / "doc3.pdf").write_text("content3")

        # Create pending operations
        self.create_pending_operation(
            str(repo_dir), "doc1.pdf", "reports", "report1.pdf"
        )
        self.create_pending_operation(
            str(repo_dir), "doc2.pdf", "reports", "report2.pdf"
        )
        self.create_pending_operation(
            str(repo_dir), "doc3.pdf", "reports", "report3.pdf"
        )

        # Simulate: Apply first, Skip second, Apply third
        result = cli_runner.invoke(
            main, ["apply", "--all"], input="A\nS\nA\n", catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Applied: 2" in result.output
        assert "Skipped: 1" in result.output

        # Verify files
        assert not (repo_dir / "doc1.pdf").exists()
        assert (repo_dir / "doc2.pdf").exists()  # Skipped
        assert not (repo_dir / "doc3.pdf").exists()
        assert (repo_dir / "reports" / "report1.pdf").exists()
        assert (repo_dir / "reports" / "report3.pdf").exists()

    def test_apply_interactive_shows_details(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that interactive mode shows operation details."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create test file
        (repo_dir / "doc.pdf").write_text("content")

        # Create pending operation with specific details
        self.create_pending_operation(
            str(repo_dir),
            "doc.pdf",
            "reports",
            "annual-report.pdf",
            "This is a financial report",
            0.92,
        )

        # Simulate user applying
        result = cli_runner.invoke(
            main, ["apply", "--all"], input="A\n", catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Current:  doc.pdf" in result.output
        assert "Suggested: reports/annual-report.pdf" in result.output
        assert "Reason: This is a financial report" in result.output
        assert "Confidence: 92%" in result.output
