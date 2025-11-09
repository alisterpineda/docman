"""Integration tests for the 'docman review' command."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from docman.cli import main
from docman.database import ensure_database, get_session
from docman.llm_config import ProviderConfig
from docman.models import Document, DocumentCopy, Operation, OperationStatus, OrganizationStatus, get_utc_now


class TestDocmanReview:
    """Integration tests for docman review command."""

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

    # === VALIDATION TESTS ===

    def test_review_apply_all_and_reject_all_conflict(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that review rejects both --apply-all and --reject-all."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        result = cli_runner.invoke(main, ["review", "--apply-all", "--reject-all"])

        assert result.exit_code == 1
        assert "Cannot use both --apply-all and --reject-all" in result.output

    def test_review_dry_run_requires_bulk_mode(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that --dry-run requires --apply-all or --reject-all."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        result = cli_runner.invoke(main, ["review", "--dry-run"])

        assert result.exit_code == 1
        assert "--dry-run can only be used with --apply-all or --reject-all" in result.output

    def test_review_apply_all_requires_confirmation(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that --apply-all without -y prompts for confirmation."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create source file
        source_file = repo_dir / "inbox" / "test.pdf"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("test content")

        # Create pending operation
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test.pdf",
            suggested_dir="documents",
            suggested_filename="test.pdf",
        )

        # Simulate user declining confirmation
        result = cli_runner.invoke(main, ["review", "--apply-all"], input="n\n", catch_exceptions=False)

        assert result.exit_code == 0
        assert "Apply 1 operation(s)?" in result.output
        assert "Aborted" in result.output
        # File should not have moved
        assert source_file.exists()
        assert not (repo_dir / "documents" / "test.pdf").exists()

    def test_review_no_pending_operations(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test review when no pending operations exist."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        result = cli_runner.invoke(main, ["review", "--apply-all", "-y"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "No pending operations found" in result.output

    # === BULK APPLY MODE TESTS ===

    def test_review_apply_all_basic(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test basic bulk apply functionality."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create source file
        source_file = repo_dir / "inbox" / "test.pdf"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("test content")

        # Create pending operation
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test.pdf",
            suggested_dir="documents",
            suggested_filename="test.pdf",
        )

        result = cli_runner.invoke(main, ["review", "--apply-all", "-y"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Applied: 1" in result.output
        assert (repo_dir / "documents" / "test.pdf").exists()
        assert not source_file.exists()

    def test_review_apply_all_with_dry_run(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test bulk apply with --dry-run flag."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create source file
        source_file = repo_dir / "inbox" / "test.pdf"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("test content")

        # Create pending operation
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test.pdf",
            suggested_dir="documents",
            suggested_filename="test.pdf",
        )

        result = cli_runner.invoke(main, ["review", "--apply-all", "--dry-run"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "DRY RUN" in result.output
        assert "Would apply: 1" in result.output
        # File should not have moved
        assert source_file.exists()
        assert not (repo_dir / "documents" / "test.pdf").exists()

    def test_review_apply_all_with_force(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test bulk apply with --force to overwrite conflicts."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create source and target files
        source_file = repo_dir / "inbox" / "test.pdf"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("new content")

        target_file = repo_dir / "documents" / "test.pdf"
        target_file.parent.mkdir(parents=True)
        target_file.write_text("old content")

        # Create pending operation
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test.pdf",
            suggested_dir="documents",
            suggested_filename="test.pdf",
        )

        result = cli_runner.invoke(main, ["review", "--apply-all", "-y", "--force"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Applied: 1" in result.output
        assert target_file.read_text() == "new content"
        assert not source_file.exists()

    def test_review_apply_all_conflict_without_force(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test bulk apply with conflict but no --force flag."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create source and target files
        source_file = repo_dir / "inbox" / "test.pdf"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("new content")

        target_file = repo_dir / "documents" / "test.pdf"
        target_file.parent.mkdir(parents=True)
        target_file.write_text("old content")

        # Create pending operation
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test.pdf",
            suggested_dir="documents",
            suggested_filename="test.pdf",
        )

        result = cli_runner.invoke(main, ["review", "--apply-all", "-y"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Skipped: 1" in result.output
        # Original files should remain
        assert source_file.exists()
        assert target_file.exists()
        assert target_file.read_text() == "old content"

    # === BULK REJECT MODE TESTS ===

    def test_review_reject_all_basic(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test basic bulk reject functionality."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create pending operation
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test.pdf",
            suggested_dir="documents",
            suggested_filename="test.pdf",
        )

        result = cli_runner.invoke(main, ["review", "--reject-all", "-y"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Successfully rejected 1 pending operation" in result.output

        # Verify operation was marked as REJECTED
        session_gen = get_session()
        session = next(session_gen)
        try:
            op = session.query(Operation).first()
            assert op.status == OperationStatus.REJECTED
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_review_reject_all_with_dry_run(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test bulk reject with --dry-run flag."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create pending operation
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test.pdf",
            suggested_dir="documents",
            suggested_filename="test.pdf",
        )

        result = cli_runner.invoke(main, ["review", "--reject-all", "--dry-run"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "DRY RUN" in result.output
        assert "Would reject 1 operation(s)" in result.output

        # Verify operation was NOT rejected
        session_gen = get_session()
        session = next(session_gen)
        try:
            op = session.query(Operation).first()
            assert op.status == OperationStatus.PENDING
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_review_reject_all_with_confirmation_abort(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test bulk reject with confirmation prompt - user aborts."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create pending operation
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test.pdf",
            suggested_dir="documents",
            suggested_filename="test.pdf",
        )

        # Simulate user aborting
        result = cli_runner.invoke(main, ["review", "--reject-all"], input="n\n", catch_exceptions=False)

        assert result.exit_code == 0
        assert "Aborted" in result.output

        # Verify operation was NOT rejected
        session_gen = get_session()
        session = next(session_gen)
        try:
            op = session.query(Operation).first()
            assert op.status == OperationStatus.PENDING
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    # === INTERACTIVE MODE TESTS ===

    def test_review_interactive_apply(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test interactive mode - user applies operation."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create source file
        source_file = repo_dir / "inbox" / "test.pdf"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("test content")

        # Create pending operation
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test.pdf",
            suggested_dir="documents",
            suggested_filename="test.pdf",
        )

        # Simulate user choosing to apply
        result = cli_runner.invoke(main, ["review"], input="A\n", catch_exceptions=False)

        assert result.exit_code == 0
        assert "Applied: 1" in result.output
        assert (repo_dir / "documents" / "test.pdf").exists()
        assert not source_file.exists()

    def test_review_interactive_reject(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test interactive mode - user rejects operation."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create source file
        source_file = repo_dir / "inbox" / "test.pdf"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("test content")

        # Create pending operation
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test.pdf",
            suggested_dir="documents",
            suggested_filename="test.pdf",
        )

        # Simulate user choosing to reject
        result = cli_runner.invoke(main, ["review"], input="R\n", catch_exceptions=False)

        assert result.exit_code == 0
        assert "Rejected: 1" in result.output
        # File should not have moved
        assert source_file.exists()
        assert not (repo_dir / "documents" / "test.pdf").exists()

        # Verify operation was marked as REJECTED
        session_gen = get_session()
        session = next(session_gen)
        try:
            op = session.query(Operation).first()
            assert op.status == OperationStatus.REJECTED
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_review_interactive_skip(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test interactive mode - user skips operation."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create source file
        source_file = repo_dir / "inbox" / "test.pdf"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("test content")

        # Create pending operation
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test.pdf",
            suggested_dir="documents",
            suggested_filename="test.pdf",
        )

        # Simulate user choosing to skip
        result = cli_runner.invoke(main, ["review"], input="S\n", catch_exceptions=False)

        assert result.exit_code == 0
        assert "Skipped: 1" in result.output
        # File should not have moved
        assert source_file.exists()
        assert not (repo_dir / "documents" / "test.pdf").exists()

        # Verify operation still PENDING
        session_gen = get_session()
        session = next(session_gen)
        try:
            op = session.query(Operation).first()
            assert op.status == OperationStatus.PENDING
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_review_interactive_quit(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test interactive mode - user quits early."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create two pending operations
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test1.pdf",
            suggested_dir="documents",
            suggested_filename="test1.pdf",
        )
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test2.pdf",
            suggested_dir="documents",
            suggested_filename="test2.pdf",
        )

        # Simulate user quitting after first operation
        result = cli_runner.invoke(main, ["review"], input="Q\n", catch_exceptions=False)

        assert result.exit_code == 0
        assert "Quitting" in result.output
        assert "Not processed (quit early): 1" in result.output

    def test_review_interactive_help(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test interactive mode - user requests help then applies."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create source file
        source_file = repo_dir / "inbox" / "test.pdf"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("test content")

        # Create pending operation
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test.pdf",
            suggested_dir="documents",
            suggested_filename="test.pdf",
        )

        # Simulate user requesting help then applying
        result = cli_runner.invoke(main, ["review"], input="H\nA\n", catch_exceptions=False)

        assert result.exit_code == 0
        assert "[A]pply  - Move this file to the suggested location" in result.output
        assert "[R]eject - Reject this suggestion" in result.output
        assert "Applied: 1" in result.output

    def test_review_interactive_invalid_input(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test interactive mode - user provides invalid input then applies."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create source file
        source_file = repo_dir / "inbox" / "test.pdf"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("test content")

        # Create pending operation
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test.pdf",
            suggested_dir="documents",
            suggested_filename="test.pdf",
        )

        # Simulate invalid input then apply
        result = cli_runner.invoke(main, ["review"], input="X\nA\n", catch_exceptions=False)

        assert result.exit_code == 0
        assert "Invalid option 'X'" in result.output
        assert "Applied: 1" in result.output

    def test_review_interactive_multiple_operations(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test interactive mode with multiple operations - mixed actions."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create source files
        for i in range(1, 4):
            source_file = repo_dir / "inbox" / f"test{i}.pdf"
            source_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_text(f"test content {i}")

        # Create pending operations
        for i in range(1, 4):
            self.create_pending_operation(
                repo_path=str(repo_dir),
                file_path=f"inbox/test{i}.pdf",
                suggested_dir="documents",
                suggested_filename=f"test{i}.pdf",
            )

        # Simulate: Apply first, Reject second, Skip third
        result = cli_runner.invoke(main, ["review"], input="A\nR\nS\n", catch_exceptions=False)

        assert result.exit_code == 0
        assert "Applied: 1" in result.output
        assert "Rejected: 1" in result.output
        assert "Skipped: 1" in result.output

        # Verify file movements
        assert (repo_dir / "documents" / "test1.pdf").exists()
        assert (repo_dir / "inbox" / "test2.pdf").exists()  # Not moved (rejected)
        assert (repo_dir / "inbox" / "test3.pdf").exists()  # Not moved (skipped)

    # === PATH FILTERING TESTS ===

    def test_review_apply_all_with_path_filter(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test bulk apply with path filter."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create source files in different directories
        for dir_name in ["inbox", "drafts"]:
            source_file = repo_dir / dir_name / "test.pdf"
            source_file.parent.mkdir(parents=True)
            source_file.write_text(f"content from {dir_name}")

            self.create_pending_operation(
                repo_path=str(repo_dir),
                file_path=f"{dir_name}/test.pdf",
                suggested_dir="documents",
                suggested_filename=f"test_{dir_name}.pdf",
            )

        # Apply only inbox operations
        result = cli_runner.invoke(
            main, ["review", "--apply-all", "-y", str(repo_dir / "inbox")], catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Applied: 1" in result.output
        assert (repo_dir / "documents" / "test_inbox.pdf").exists()
        # Drafts should not be processed
        assert not (repo_dir / "documents" / "test_drafts.pdf").exists()

    def test_review_reject_all_recursive_vs_non_recursive(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test bulk reject with recursive flag."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create directory structure
        (repo_dir / "inbox").mkdir()
        (repo_dir / "inbox" / "subdir").mkdir()

        # Create operations in directory and subdirectory
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test.pdf",
            suggested_dir="documents",
            suggested_filename="test.pdf",
        )
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/subdir/test2.pdf",
            suggested_dir="documents",
            suggested_filename="test2.pdf",
        )

        # Non-recursive: should only reject inbox/test.pdf
        result = cli_runner.invoke(
            main, ["review", "--reject-all", "-y", str(repo_dir / "inbox")], catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Successfully rejected 1 pending operation" in result.output

        # Reset for recursive test
        # Create new operation
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test3.pdf",
            suggested_dir="documents",
            suggested_filename="test3.pdf",
        )

        # Recursive: should reject both remaining operations
        result = cli_runner.invoke(
            main, ["review", "--reject-all", "-y", "-r", str(repo_dir / "inbox")],
            catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Successfully rejected 2 pending operation" in result.output

    # === EDGE CASES ===

    def test_review_no_op_operation(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test review with operation where file is already at target."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create file at target location
        target_file = repo_dir / "documents" / "test.pdf"
        target_file.parent.mkdir(parents=True)
        target_file.write_text("test content")

        # Create pending operation pointing to same location
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="documents/test.pdf",
            suggested_dir="documents",
            suggested_filename="test.pdf",
        )

        # Interactive mode - user confirms removal
        result = cli_runner.invoke(main, ["review"], input="y\n", catch_exceptions=False)

        assert result.exit_code == 0
        assert "no change needed, already at target location" in result.output
        assert "Removed" in result.output

    def test_review_outside_repository(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test review command outside a repository."""
        non_repo_dir = tmp_path / "not_a_repo"
        non_repo_dir.mkdir()
        monkeypatch.chdir(non_repo_dir)

        result = cli_runner.invoke(main, ["review", "--apply-all", "-y"])

        assert result.exit_code == 1
        assert "Not in a docman repository" in result.output

    def test_review_interactive_with_path_filter(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test interactive review with path filter."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create source files
        (repo_dir / "inbox").mkdir()
        (repo_dir / "inbox" / "test1.pdf").write_text("content 1")
        (repo_dir / "drafts").mkdir()
        (repo_dir / "drafts" / "test2.pdf").write_text("content 2")

        # Create operations
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test1.pdf",
            suggested_dir="documents",
            suggested_filename="test1.pdf",
        )
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="drafts/test2.pdf",
            suggested_dir="documents",
            suggested_filename="test2.pdf",
        )

        # Review only inbox - apply
        result = cli_runner.invoke(
            main, ["review", str(repo_dir / "inbox")], input="A\n", catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Operations to review: 1" in result.output
        assert "Applied: 1" in result.output

    # === RE-PROCESS TESTS ===

    def test_review_interactive_reprocess_basic(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test re-processing a suggestion with additional instructions."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create source file
        source_file = repo_dir / "inbox" / "test.pdf"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("test content")

        # Create pending operation
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test.pdf",
            suggested_dir="documents",
            suggested_filename="test.pdf",
            reason="Initial reason",
        )

        # Mock LLM provider to return a new suggestion
        mock_provider_config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )
        mock_provider_instance = Mock()
        mock_provider_instance.supports_structured_output = True
        mock_provider_instance.generate_suggestions.return_value = {
            "suggested_directory_path": "archived",
            "suggested_filename": "archived_test.pdf",
            "reason": "New reason with additional context",
        }

        monkeypatch.setattr("docman.cli.get_active_provider", Mock(return_value=mock_provider_config))
        monkeypatch.setattr("docman.cli.get_api_key", Mock(return_value="test-api-key"))
        monkeypatch.setattr("docman.cli.get_llm_provider", Mock(return_value=mock_provider_instance))

        # Simulate user input: Process -> additional instructions -> Apply
        result = cli_runner.invoke(
            main,
            ["review"],
            input="P\nUse archived directory\nA\n",
            catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Re-process this suggestion" in result.output
        assert "New suggestion generated!" in result.output
        assert "archived/archived_test.pdf" in result.output
        assert "New reason with additional context" in result.output
        assert "Applied: 1" in result.output

        # Verify file was moved to new location
        assert (repo_dir / "archived" / "archived_test.pdf").exists()
        assert not source_file.exists()

        # Verify operation was updated and accepted
        session_gen = get_session()
        session = next(session_gen)
        try:
            op = session.query(Operation).first()
            assert op.status == OperationStatus.ACCEPTED
            assert op.suggested_directory_path == "archived"
            assert op.suggested_filename == "archived_test.pdf"
            assert op.reason == "New reason with additional context"
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_review_interactive_reprocess_multiple_iterations(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test re-processing multiple times before applying."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create source file
        source_file = repo_dir / "inbox" / "test.pdf"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("test content")

        # Create pending operation
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test.pdf",
            suggested_dir="documents",
            suggested_filename="test.pdf",
            reason="Initial reason",
        )

        # Mock LLM provider to return different suggestions each time
        mock_provider_config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )
        mock_provider_instance = Mock()
        mock_provider_instance.supports_structured_output = True

        # First call returns one suggestion, second call returns another
        mock_provider_instance.generate_suggestions.side_effect = [
            {
                "suggested_directory_path": "temp",
                "suggested_filename": "temp_test.pdf",
                "reason": "First attempt",
            },
            {
                "suggested_directory_path": "final",
                "suggested_filename": "final_test.pdf",
                "reason": "Second attempt - better",
            },
        ]

        monkeypatch.setattr("docman.cli.get_active_provider", Mock(return_value=mock_provider_config))
        monkeypatch.setattr("docman.cli.get_api_key", Mock(return_value="test-api-key"))
        monkeypatch.setattr("docman.cli.get_llm_provider", Mock(return_value=mock_provider_instance))

        # Simulate user input: Process -> instructions -> Process again -> different instructions -> Apply
        result = cli_runner.invoke(
            main,
            ["review"],
            input="P\nFirst instructions\nP\nSecond instructions\nA\n",
            catch_exceptions=False
        )

        assert result.exit_code == 0
        assert result.output.count("New suggestion generated!") == 2
        assert "final/final_test.pdf" in result.output
        assert "Second attempt - better" in result.output
        assert "Applied: 1" in result.output

        # Verify file was moved to final location
        assert (repo_dir / "final" / "final_test.pdf").exists()
        assert not source_file.exists()

    def test_review_interactive_reprocess_then_reject(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test re-processing and then rejecting the new suggestion."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create source file
        source_file = repo_dir / "inbox" / "test.pdf"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("test content")

        # Create pending operation
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test.pdf",
            suggested_dir="documents",
            suggested_filename="test.pdf",
        )

        # Mock LLM provider
        mock_provider_config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )
        mock_provider_instance = Mock()
        mock_provider_instance.supports_structured_output = True
        mock_provider_instance.generate_suggestions.return_value = {
            "suggested_directory_path": "bad_location",
            "suggested_filename": "bad_name.pdf",
            "reason": "Not a good suggestion",
        }

        monkeypatch.setattr("docman.cli.get_active_provider", Mock(return_value=mock_provider_config))
        monkeypatch.setattr("docman.cli.get_api_key", Mock(return_value="test-api-key"))
        monkeypatch.setattr("docman.cli.get_llm_provider", Mock(return_value=mock_provider_instance))

        # Simulate user input: Process -> instructions -> Reject
        result = cli_runner.invoke(
            main,
            ["review"],
            input="P\nTry something different\nR\n",
            catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "New suggestion generated!" in result.output
        assert "Rejected: 1" in result.output

        # Verify file was NOT moved
        assert source_file.exists()
        assert not (repo_dir / "bad_location" / "bad_name.pdf").exists()

        # Verify operation was rejected
        session_gen = get_session()
        session = next(session_gen)
        try:
            op = session.query(Operation).first()
            assert op.status == OperationStatus.REJECTED
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_review_interactive_reprocess_cancel(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test cancelling re-process by providing empty instructions."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create source file
        source_file = repo_dir / "inbox" / "test.pdf"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("test content")

        # Create pending operation
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test.pdf",
            suggested_dir="documents",
            suggested_filename="test.pdf",
        )

        # Mock LLM provider (should NOT be called if cancelled)
        mock_provider_config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )
        mock_provider_instance = Mock()
        mock_provider_instance.supports_structured_output = True

        monkeypatch.setattr("docman.cli.get_active_provider", Mock(return_value=mock_provider_config))
        monkeypatch.setattr("docman.cli.get_api_key", Mock(return_value="test-api-key"))
        monkeypatch.setattr("docman.cli.get_llm_provider", Mock(return_value=mock_provider_instance))

        # Simulate user input: Process -> empty instructions (cancel) -> Skip
        result = cli_runner.invoke(
            main,
            ["review"],
            input="P\n\nS\n",
            catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Cancelled re-processing" in result.output
        assert "Skipped: 1" in result.output

        # Verify LLM was NOT called
        mock_provider_instance.generate_suggestions.assert_not_called()

        # Verify operation is still pending
        session_gen = get_session()
        session = next(session_gen)
        try:
            op = session.query(Operation).first()
            assert op.status == OperationStatus.PENDING
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_review_interactive_reprocess_invalid_path_security(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that invalid paths from LLM during re-process don't corrupt the operation."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create source file
        source_file = repo_dir / "inbox" / "test.pdf"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("test content")

        # Create pending operation with valid suggestion
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test.pdf",
            suggested_dir="documents",
            suggested_filename="test.pdf",
            reason="Original valid reason",
        )

        # Mock LLM provider to return INVALID path (absolute path)
        mock_provider_config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )
        mock_provider_instance = Mock()
        mock_provider_instance.supports_structured_output = True
        mock_provider_instance.generate_suggestions.return_value = {
            "suggested_directory_path": "/etc",  # Invalid: absolute path!
            "suggested_filename": "passwd",
            "reason": "Malicious suggestion",
        }

        monkeypatch.setattr("docman.cli.get_active_provider", Mock(return_value=mock_provider_config))
        monkeypatch.setattr("docman.cli.get_api_key", Mock(return_value="test-api-key"))
        monkeypatch.setattr("docman.cli.get_llm_provider", Mock(return_value=mock_provider_instance))

        # Simulate user input: Process -> instructions -> (LLM returns invalid path) -> Skip
        result = cli_runner.invoke(
            main,
            ["review"],
            input="P\nTry to break security\nS\n",
            catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Error: LLM generated invalid path" in result.output
        assert "Failed to regenerate suggestion" in result.output
        assert "Skipped: 1" in result.output

        # Verify operation STILL has the original valid suggestion (not corrupted)
        session_gen = get_session()
        session = next(session_gen)
        try:
            op = session.query(Operation).first()
            assert op.status == OperationStatus.PENDING
            assert op.suggested_directory_path == "documents"  # Original value preserved
            assert op.suggested_filename == "test.pdf"  # Original value preserved
            assert op.reason == "Original valid reason"  # Original reason preserved
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass


class TestReviewSecurityCleanup:
    """Test cleanup of invalid operations with security issues."""

    def setup_repository(self, path: Path) -> None:
        """Set up a docman repository for testing."""
        docman_dir = path / ".docman"
        docman_dir.mkdir()
        config_file = docman_dir / "config.yaml"
        config_file.touch()
        instructions_file = docman_dir / "instructions.md"
        instructions_file.write_text("Test organization instructions")

    def setup_isolated_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """Set up isolated environment."""
        app_config_dir = tmp_path / "app_config"
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(app_config_dir))
        self.setup_repository(repo_dir)
        return repo_dir

    def test_interactive_review_allows_rejecting_invalid_operations(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that invalid operations can be rejected in interactive mode."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create a test file
        test_file = repo_dir / "test.pdf"
        test_file.write_text("test content")

        # Initialize database
        monkeypatch.chdir(repo_dir)
        result = cli_runner.invoke(main, ["init"], catch_exceptions=False)
        assert result.exit_code == 0

        # Manually insert an invalid operation into the database
        # (simulating legacy data created before security fix)
        session_gen = get_session()
        session = next(session_gen)
        try:
            # Create document and copy
            doc = Document(
                content_hash="test_hash",
                content="test content",
                created_at=get_utc_now(),
            )
            session.add(doc)
            session.flush()

            doc_copy = DocumentCopy(
                document_id=doc.id,
                repository_path=str(repo_dir),
                file_path="test.pdf",
                stored_content_hash="test_hash",
                stored_size=12,
                stored_mtime=test_file.stat().st_mtime,
                organization_status=OrganizationStatus.UNORGANIZED,
                last_seen_at=get_utc_now(),
            )
            session.add(doc_copy)
            session.flush()

            # Create operation with malicious path (this bypasses Pydantic validation)
            malicious_op = Operation(
                document_copy_id=doc_copy.id,
                suggested_directory_path="../../etc",  # Path traversal!
                suggested_filename="passwd",
                reason="Malicious suggestion",
                status=OperationStatus.PENDING,
                prompt_hash="test_hash",
                document_content_hash="test_hash",
                model_name="test-model",
                created_at=get_utc_now(),
            )
            session.add(malicious_op)
            session.commit()
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

        # Run review in interactive mode, automatically answering "y" to reject
        result = cli_runner.invoke(
            main,
            ["review"],
            input="y\n",  # Confirm rejection
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "Security Error" in result.output
        assert "Invalid path suggestion detected" in result.output
        assert "Rejected (invalid path)" in result.output or "Rejected" in result.output

        # Verify the operation was marked as rejected
        session_gen = get_session()
        session = next(session_gen)
        try:
            op = session.query(Operation).filter(
                Operation.document_copy_id == doc_copy.id
            ).first()
            assert op is not None
            assert op.status == OperationStatus.REJECTED
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_bulk_apply_auto_rejects_invalid_operations(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that invalid operations are auto-rejected in bulk mode."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create a test file
        test_file = repo_dir / "test.pdf"
        test_file.write_text("test content")

        # Initialize database
        monkeypatch.chdir(repo_dir)
        result = cli_runner.invoke(main, ["init"], catch_exceptions=False)
        assert result.exit_code == 0

        # Manually insert an invalid operation
        session_gen = get_session()
        session = next(session_gen)
        try:
            doc = Document(
                content_hash="test_hash",
                content="test content",
                created_at=get_utc_now(),
            )
            session.add(doc)
            session.flush()

            doc_copy = DocumentCopy(
                document_id=doc.id,
                repository_path=str(repo_dir),
                file_path="test.pdf",
                stored_content_hash="test_hash",
                stored_size=12,
                stored_mtime=test_file.stat().st_mtime,
                organization_status=OrganizationStatus.UNORGANIZED,
                last_seen_at=get_utc_now(),
            )
            session.add(doc_copy)
            session.flush()

            malicious_op = Operation(
                document_copy_id=doc_copy.id,
                suggested_directory_path="/etc",  # Absolute path!
                suggested_filename="hosts",
                reason="Malicious suggestion",
                status=OperationStatus.PENDING,
                prompt_hash="test_hash",
                document_content_hash="test_hash",
                model_name="test-model",
                created_at=get_utc_now(),
            )
            session.add(malicious_op)
            session.commit()

            copy_id = doc_copy.id
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

        # Run review with --apply-all -y (bulk mode)
        result = cli_runner.invoke(
            main,
            ["review", "--apply-all", "-y"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "Security Error" in result.output
        assert "Auto-rejected (invalid path)" in result.output or "Auto-rejected" in result.output

        # Verify the operation was marked as rejected
        session_gen = get_session()
        session = next(session_gen)
        try:
            op = session.query(Operation).filter(
                Operation.document_copy_id == copy_id
            ).first()
            assert op is not None
            assert op.status == OperationStatus.REJECTED
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass


class TestReprocessConversationHistory:
    """Tests for conversational re-process feature with prompt history tracking."""

    def setup_repository(self, path: Path) -> None:
        """Set up a docman repository for testing."""
        docman_dir = path / ".docman"
        docman_dir.mkdir()
        config_file = docman_dir / "config.yaml"
        config_file.touch()

        # Create instructions file (required)
        instructions_file = docman_dir / "instructions.md"
        instructions_file.write_text("Organize documents by category and date.")

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
            doc = Document(
                content="Invoice #123\nDate: 2024-01-15\nVendor: ACME Corp",
                content_hash="test_hash_123",
            )
            session.add(doc)
            session.flush()

            # Create document copy
            doc_copy = DocumentCopy(
                repository_path=repo_path,
                file_path=file_path,
                document_id=doc.id,
                stored_content_hash="test_hash_123",
                stored_size=100,
                stored_mtime=123456.0,
                organization_status=OrganizationStatus.UNORGANIZED,
            )
            session.add(doc_copy)
            session.flush()

            # Create pending operation
            op = Operation(
                document_copy_id=doc_copy.id,
                suggested_directory_path=suggested_dir,
                suggested_filename=suggested_filename,
                reason=reason,
                status=OperationStatus.PENDING,
                prompt_hash="test_hash",
                document_content_hash="test_hash_123",
                model_name="test-model",
                created_at=get_utc_now(),
            )
            session.add(op)
            session.commit()
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_prompt_includes_first_iteration_history(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that prompt includes first suggestion and user feedback after first re-process."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create source file
        source_file = repo_dir / "inbox" / "invoice.pdf"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("Invoice #123\nDate: 2024-01-15\nVendor: ACME Corp")

        # Create pending operation with initial suggestion
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/invoice.pdf",
            suggested_dir="invoices/2024",
            suggested_filename="invoice.pdf",
            reason="Organizing by year",
        )

        # Mock LLM provider
        mock_provider_config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )
        mock_provider_instance = Mock()
        mock_provider_instance.supports_structured_output = True
        mock_provider_instance.generate_suggestions.return_value = {
            "suggested_directory_path": "invoices/2024/acme-corp",
            "suggested_filename": "invoice.pdf",
            "reason": "Added vendor directory",
        }

        monkeypatch.setattr("docman.cli.get_active_provider", Mock(return_value=mock_provider_config))
        monkeypatch.setattr("docman.cli.get_api_key", Mock(return_value="test-api-key"))
        monkeypatch.setattr("docman.cli.get_llm_provider", Mock(return_value=mock_provider_instance))

        # Simulate: Process -> user feedback -> Skip
        result = cli_runner.invoke(
            main,
            ["review"],
            input="P\nInclude vendor name in directory\nS\n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "New suggestion generated!" in result.output

        # Verify generate_suggestions was called once
        assert mock_provider_instance.generate_suggestions.call_count == 1

        # Get the actual prompt that was passed
        call_args = mock_provider_instance.generate_suggestions.call_args
        system_prompt = call_args[0][0]
        user_prompt = call_args[0][1]

        # Verify base prompt structure
        assert "<organizationInstructions>" in user_prompt
        assert "Organize documents by category and date" in user_prompt
        assert "<documentContent" in user_prompt
        assert 'filePath="inbox/invoice.pdf"' in user_prompt

        # Verify conversation history is included
        # Should have: original suggestion in JSON format
        assert '"suggested_directory_path": "invoices/2024"' in user_prompt
        assert '"suggested_filename": "invoice.pdf"' in user_prompt
        assert '"reason": "Organizing by year"' in user_prompt

        # Should have: user feedback in XML tags
        assert "<userFeedback>" in user_prompt
        assert "Include vendor name in directory" in user_prompt
        assert "</userFeedback>" in user_prompt

    def test_prompt_includes_multiple_iteration_history(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that prompt grows to include all iterations in conversation."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create source file
        source_file = repo_dir / "inbox" / "invoice.pdf"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("Invoice #123\nDate: 2024-01-15\nVendor: ACME Corp")

        # Create pending operation with initial suggestion
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/invoice.pdf",
            suggested_dir="invoices/2024",
            suggested_filename="invoice.pdf",
            reason="Organizing by year",
        )

        # Mock LLM provider with different responses for each call
        mock_provider_config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )
        mock_provider_instance = Mock()
        mock_provider_instance.supports_structured_output = True
        mock_provider_instance.generate_suggestions.side_effect = [
            # First re-process response
            {
                "suggested_directory_path": "invoices/2024/acme-corp",
                "suggested_filename": "invoice.pdf",
                "reason": "Added vendor directory",
            },
            # Second re-process response
            {
                "suggested_directory_path": "invoices/2024/acme-corp",
                "suggested_filename": "invoice_123.pdf",
                "reason": "Added invoice number to filename",
            },
        ]

        monkeypatch.setattr("docman.cli.get_active_provider", Mock(return_value=mock_provider_config))
        monkeypatch.setattr("docman.cli.get_api_key", Mock(return_value="test-api-key"))
        monkeypatch.setattr("docman.cli.get_llm_provider", Mock(return_value=mock_provider_instance))

        # Simulate: Process -> feedback 1 -> Process -> feedback 2 -> Skip
        result = cli_runner.invoke(
            main,
            ["review"],
            input="P\nInclude vendor name\nP\nInclude invoice number in filename\nS\n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert result.output.count("New suggestion generated!") == 2

        # Verify generate_suggestions was called twice
        assert mock_provider_instance.generate_suggestions.call_count == 2

        # Check the SECOND call to verify it has full conversation history
        second_call_args = mock_provider_instance.generate_suggestions.call_args_list[1]
        user_prompt_iter2 = second_call_args[0][1]

        # Should have base document content
        assert "<documentContent" in user_prompt_iter2
        assert 'filePath="inbox/invoice.pdf"' in user_prompt_iter2

        # Should have FIRST iteration (original suggestion + feedback)
        assert '"suggested_directory_path": "invoices/2024"' in user_prompt_iter2
        assert '"reason": "Organizing by year"' in user_prompt_iter2
        assert "Include vendor name" in user_prompt_iter2

        # Should have SECOND iteration (first regenerated suggestion + feedback)
        assert '"suggested_directory_path": "invoices/2024/acme-corp"' in user_prompt_iter2
        assert '"reason": "Added vendor directory"' in user_prompt_iter2
        assert "Include invoice number in filename" in user_prompt_iter2

        # Count occurrences of userFeedback tags - should have 2 sets
        assert user_prompt_iter2.count("<userFeedback>") == 2
        assert user_prompt_iter2.count("</userFeedback>") == 2

    def test_conversation_resets_between_operations(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that conversation history resets when moving to next operation."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create two source files
        file1 = repo_dir / "inbox" / "doc1.pdf"
        file2 = repo_dir / "inbox" / "doc2.pdf"
        file1.parent.mkdir(parents=True)
        file1.write_text("Document 1 content")
        file2.write_text("Document 2 content")

        # Create two pending operations
        # First operation
        ensure_database()
        session_gen = get_session()
        session = next(session_gen)
        try:
            doc1 = Document(content="Document 1 content", content_hash="hash1")
            session.add(doc1)
            session.flush()

            copy1 = DocumentCopy(
                repository_path=str(repo_dir),
                file_path="inbox/doc1.pdf",
                document_id=doc1.id,
                stored_content_hash="hash1",
                stored_size=100,
                stored_mtime=123456.0,
                organization_status=OrganizationStatus.UNORGANIZED,
            )
            session.add(copy1)
            session.flush()

            op1 = Operation(
                document_copy_id=copy1.id,
                suggested_directory_path="docs",
                suggested_filename="doc1.pdf",
                reason="First doc",
                status=OperationStatus.PENDING,
                prompt_hash="hash1",
                document_content_hash="hash1",
                model_name="test-model",
                created_at=get_utc_now(),
            )
            session.add(op1)

            # Second operation
            doc2 = Document(content="Document 2 content", content_hash="hash2")
            session.add(doc2)
            session.flush()

            copy2 = DocumentCopy(
                repository_path=str(repo_dir),
                file_path="inbox/doc2.pdf",
                document_id=doc2.id,
                stored_content_hash="hash2",
                stored_size=100,
                stored_mtime=123456.0,
                organization_status=OrganizationStatus.UNORGANIZED,
            )
            session.add(copy2)
            session.flush()

            op2 = Operation(
                document_copy_id=copy2.id,
                suggested_directory_path="docs",
                suggested_filename="doc2.pdf",
                reason="Second doc",
                status=OperationStatus.PENDING,
                prompt_hash="hash2",
                document_content_hash="hash2",
                model_name="test-model",
                created_at=get_utc_now(),
            )
            session.add(op2)
            session.commit()
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

        # Mock LLM provider
        mock_provider_config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )
        mock_provider_instance = Mock()
        mock_provider_instance.supports_structured_output = True
        mock_provider_instance.generate_suggestions.side_effect = [
            # First re-process on doc1
            {"suggested_directory_path": "new1", "suggested_filename": "new1.pdf", "reason": "Updated 1"},
            # Re-process on doc2 (should NOT have doc1's history)
            {"suggested_directory_path": "new2", "suggested_filename": "new2.pdf", "reason": "Updated 2"},
        ]

        monkeypatch.setattr("docman.cli.get_active_provider", Mock(return_value=mock_provider_config))
        monkeypatch.setattr("docman.cli.get_api_key", Mock(return_value="test-api-key"))
        monkeypatch.setattr("docman.cli.get_llm_provider", Mock(return_value=mock_provider_instance))

        # Simulate: Process doc1 -> feedback -> Skip -> Process doc2 -> feedback -> Skip
        result = cli_runner.invoke(
            main,
            ["review"],
            input="P\nFeedback for doc1\nS\nP\nFeedback for doc2\nS\n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert mock_provider_instance.generate_suggestions.call_count == 2

        # Check first call - should have doc1 info
        first_call_prompt = mock_provider_instance.generate_suggestions.call_args_list[0][0][1]
        assert 'filePath="inbox/doc1.pdf"' in first_call_prompt
        assert "Feedback for doc1" in first_call_prompt
        assert "Feedback for doc2" not in first_call_prompt

        # Check second call - should have doc2 info, NOT doc1 history
        second_call_prompt = mock_provider_instance.generate_suggestions.call_args_list[1][0][1]
        assert 'filePath="inbox/doc2.pdf"' in second_call_prompt
        assert "Feedback for doc2" in second_call_prompt
        # Should NOT contain doc1's feedback
        assert "Feedback for doc1" not in second_call_prompt
        assert 'filePath="inbox/doc1.pdf"' not in second_call_prompt

    def test_special_characters_in_feedback(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that special characters in feedback are properly handled in prompt."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create source file
        source_file = repo_dir / "inbox" / "test.pdf"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("Test content")

        # Create pending operation
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test.pdf",
            suggested_dir="docs",
            suggested_filename="test.pdf",
            reason="Initial",
        )

        # Mock LLM provider
        mock_provider_config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )
        mock_provider_instance = Mock()
        mock_provider_instance.supports_structured_output = True
        mock_provider_instance.generate_suggestions.return_value = {
            "suggested_directory_path": "updated",
            "suggested_filename": "updated.pdf",
            "reason": "Updated",
        }

        monkeypatch.setattr("docman.cli.get_active_provider", Mock(return_value=mock_provider_config))
        monkeypatch.setattr("docman.cli.get_api_key", Mock(return_value="test-api-key"))
        monkeypatch.setattr("docman.cli.get_llm_provider", Mock(return_value=mock_provider_instance))

        # Feedback with special XML/JSON characters
        special_feedback = 'Use <tag> & "quotes" and \\slashes\\ in path'

        # Simulate: Process -> special feedback -> Skip
        result = cli_runner.invoke(
            main,
            ["review"],
            input=f"P\n{special_feedback}\nS\n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0

        # Verify the feedback was included in the prompt
        call_args = mock_provider_instance.generate_suggestions.call_args
        user_prompt = call_args[0][1]

        # Feedback should be in XML tags
        assert "<userFeedback>" in user_prompt
        assert special_feedback in user_prompt
        assert "</userFeedback>" in user_prompt

    def test_very_long_feedback(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test handling of very long user feedback in conversation."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create source file
        source_file = repo_dir / "inbox" / "test.pdf"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("Test content")

        # Create pending operation
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test.pdf",
            suggested_dir="docs",
            suggested_filename="test.pdf",
            reason="Initial",
        )

        # Mock LLM provider
        mock_provider_config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )
        mock_provider_instance = Mock()
        mock_provider_instance.supports_structured_output = True
        mock_provider_instance.generate_suggestions.return_value = {
            "suggested_directory_path": "updated",
            "suggested_filename": "updated.pdf",
            "reason": "Updated",
        }

        monkeypatch.setattr("docman.cli.get_active_provider", Mock(return_value=mock_provider_config))
        monkeypatch.setattr("docman.cli.get_api_key", Mock(return_value="test-api-key"))
        monkeypatch.setattr("docman.cli.get_llm_provider", Mock(return_value=mock_provider_instance))

        # Very long feedback (2000+ characters)
        long_feedback = ("Please organize this document carefully. " * 50).strip()

        # Simulate: Process -> long feedback -> Skip
        result = cli_runner.invoke(
            main,
            ["review"],
            input=f"P\n{long_feedback}\nS\n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0

        # Verify the full feedback was included
        call_args = mock_provider_instance.generate_suggestions.call_args
        user_prompt = call_args[0][1]

        assert long_feedback in user_prompt
        assert len(user_prompt) > 2000

    def test_prompt_structure_with_no_organization_instructions(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test prompt structure when organization instructions are missing."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        app_config_dir = tmp_path / "app_config"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(app_config_dir))
        
        # Setup repo WITHOUT instructions file
        docman_dir = repo_dir / ".docman"
        docman_dir.mkdir()
        config_file = docman_dir / "config.yaml"
        config_file.touch()
        # Note: NOT creating instructions.md file

        monkeypatch.chdir(repo_dir)

        # Create source file
        source_file = repo_dir / "inbox" / "test.pdf"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("Test content")

        # Create pending operation
        self.create_pending_operation(
            repo_path=str(repo_dir),
            file_path="inbox/test.pdf",
            suggested_dir="docs",
            suggested_filename="test.pdf",
            reason="Initial",
        )

        # Mock LLM provider
        mock_provider_config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )
        mock_provider_instance = Mock()
        mock_provider_instance.supports_structured_output = True

        monkeypatch.setattr("docman.cli.get_active_provider", Mock(return_value=mock_provider_config))
        monkeypatch.setattr("docman.cli.get_api_key", Mock(return_value="test-api-key"))
        monkeypatch.setattr("docman.cli.get_llm_provider", Mock(return_value=mock_provider_instance))

        # Simulate: Process -> feedback
        result = cli_runner.invoke(
            main,
            ["review"],
            input="P\nSome feedback\nS\n",
            catch_exceptions=False,
        )

        # Should show error about missing instructions
        assert "Error: Organization instructions not found" in result.output
        # Should NOT call generate_suggestions since instructions are required
        assert mock_provider_instance.generate_suggestions.call_count == 0
