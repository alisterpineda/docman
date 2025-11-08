"""Integration tests for the 'docman review' command."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from docman.cli import main
from docman.database import ensure_database, get_session
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
