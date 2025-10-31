"""Integration tests for the 'docman reset' command."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from docman.cli import main
from docman.database import ensure_database, get_session
from docman.models import Document, DocumentCopy, PendingOperation


class TestDocmanReset:
    """Integration tests for docman reset command."""

    def setup_repository(self, path: Path) -> None:
        """Set up a docman repository for testing."""
        docman_dir = path / ".docman"
        docman_dir.mkdir()
        config_file = docman_dir / "config.yaml"
        config_file.touch()

    def setup_isolated_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> Path:
        """Set up isolated environment with separate app config and repository."""
        app_config_dir = tmp_path / "app_config"
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(app_config_dir))
        self.setup_repository(repo_dir)
        return repo_dir

    def create_test_pending_operation(
        self, repository_path: str, file_path: str = "test.pdf"
    ) -> int:
        """Create a test document, copy, and pending operation.

        Returns the pending operation ID.
        """
        session_gen = get_session()
        session = next(session_gen)

        try:
            # Create document
            doc = Document(
                content_hash=f"hash_{file_path}", content=f"Test content for {file_path}"
            )
            session.add(doc)
            session.flush()

            # Create document copy
            copy = DocumentCopy(
                document_id=doc.id,
                repository_path=repository_path,
                file_path=file_path,
            )
            session.add(copy)
            session.flush()

            # Create pending operation
            pending_op = PendingOperation(
                document_copy_id=copy.id,
                suggested_directory_path="docs/",
                suggested_filename=f"renamed_{file_path}",
                reason="Test reason",
                confidence=0.8,
            )
            session.add(pending_op)
            session.commit()

            return pending_op.id
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_reset_success_with_yes_flag(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test reset successfully deletes pending operations with -y flag."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        ensure_database()

        # Create test pending operation
        self.create_test_pending_operation(str(repo_dir))

        # Verify pending op exists
        session_gen = get_session()
        session = next(session_gen)
        try:
            ops_before = session.query(PendingOperation).all()
            assert len(ops_before) == 1
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

        # Change to repository directory
        monkeypatch.chdir(repo_dir)

        # Run reset command with -y flag
        result = cli_runner.invoke(main, ["reset", "-y"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Repository:" in result.output
        assert "Found 1 pending operation(s) to delete" in result.output
        assert "Successfully deleted 1 pending operation(s)" in result.output

        # Verify pending operations were deleted
        session_gen = get_session()
        session = next(session_gen)
        try:
            ops_after = session.query(PendingOperation).all()
            assert len(ops_after) == 0

            # Verify document and copy still exist (only pending ops deleted)
            docs = session.query(Document).all()
            assert len(docs) == 1
            copies = session.query(DocumentCopy).all()
            assert len(copies) == 1
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_reset_with_confirmation_accepted(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test reset with user confirmation accepted."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        ensure_database()

        # Create multiple test pending operations
        self.create_test_pending_operation(str(repo_dir), "file1.pdf")
        self.create_test_pending_operation(str(repo_dir), "file2.pdf")

        monkeypatch.chdir(repo_dir)

        # Run reset command without -y flag, providing 'y' as input
        result = cli_runner.invoke(main, ["reset"], input="y\n", catch_exceptions=False)

        assert result.exit_code == 0
        assert "Found 2 pending operation(s) to delete" in result.output
        assert "Are you sure you want to delete these pending operations?" in result.output
        assert "Successfully deleted 2 pending operation(s)" in result.output

        # Verify all pending operations were deleted
        session_gen = get_session()
        session = next(session_gen)
        try:
            ops_after = session.query(PendingOperation).all()
            assert len(ops_after) == 0
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_reset_with_confirmation_declined(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test reset aborts when user declines confirmation."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        ensure_database()

        self.create_test_pending_operation(str(repo_dir))

        monkeypatch.chdir(repo_dir)

        # Run reset command without -y flag, providing 'n' as input
        result = cli_runner.invoke(main, ["reset"], input="n\n", catch_exceptions=False)

        assert result.exit_code == 0
        assert "Are you sure you want to delete these pending operations?" in result.output
        assert "Aborted." in result.output

        # Verify pending operation still exists
        session_gen = get_session()
        session = next(session_gen)
        try:
            ops_after = session.query(PendingOperation).all()
            assert len(ops_after) == 1
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_reset_no_pending_operations(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test reset when no pending operations exist."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        ensure_database()

        monkeypatch.chdir(repo_dir)

        result = cli_runner.invoke(main, ["reset", "-y"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "No pending operations found for this repository" in result.output

    def test_reset_isolates_multiple_repositories(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test reset only deletes pending operations for target repository."""
        # Set up app config isolation
        app_config_dir = tmp_path / "app_config"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(app_config_dir))

        # Create two separate repositories
        repo1_dir = tmp_path / "repo1"
        repo2_dir = tmp_path / "repo2"
        repo1_dir.mkdir()
        repo2_dir.mkdir()

        self.setup_repository(repo1_dir)
        self.setup_repository(repo2_dir)

        ensure_database()

        # Create pending operations for both repositories
        self.create_test_pending_operation(str(repo1_dir), "repo1_file.pdf")
        op2_id = self.create_test_pending_operation(str(repo2_dir), "repo2_file.pdf")

        # Verify both pending ops exist
        session_gen = get_session()
        session = next(session_gen)
        try:
            ops_before = session.query(PendingOperation).all()
            assert len(ops_before) == 2
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

        # Reset only repo1
        monkeypatch.chdir(repo1_dir)
        result = cli_runner.invoke(main, ["reset", "-y"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Successfully deleted 1 pending operation(s)" in result.output

        # Verify only repo1's pending operation was deleted
        session_gen = get_session()
        session = next(session_gen)
        try:
            ops_after = session.query(PendingOperation).all()
            assert len(ops_after) == 1
            assert ops_after[0].id == op2_id  # repo2's operation still exists
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_reset_fails_outside_repository(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test reset fails gracefully when not in a repository."""
        # Set up isolated environment but no repository
        app_config_dir = tmp_path / "app_config"
        non_repo_dir = tmp_path / "not_a_repo"
        non_repo_dir.mkdir()

        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(app_config_dir))
        ensure_database()

        # Try to run reset from non-repository directory
        monkeypatch.chdir(non_repo_dir)
        result = cli_runner.invoke(main, ["reset", "-y"], catch_exceptions=False)

        assert result.exit_code == 1
        assert "Error: Not in a docman repository" in result.output

    def test_reset_from_subdirectory(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test reset works when run from a subdirectory of the repository."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        ensure_database()

        # Create a subdirectory
        subdir = repo_dir / "docs" / "nested"
        subdir.mkdir(parents=True)

        self.create_test_pending_operation(str(repo_dir))

        # Run reset from subdirectory
        monkeypatch.chdir(subdir)
        result = cli_runner.invoke(main, ["reset", "-y"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Successfully deleted 1 pending operation(s)" in result.output

        # Verify pending operation was deleted
        session_gen = get_session()
        session = next(session_gen)
        try:
            ops_after = session.query(PendingOperation).all()
            assert len(ops_after) == 0
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_reset_with_explicit_path(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test reset with explicit repository path parameter."""
        # Set up app config isolation
        app_config_dir = tmp_path / "app_config"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(app_config_dir))

        # Create repository in a specific location
        repo_dir = tmp_path / "my_repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        # Create a different working directory
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        ensure_database()
        self.create_test_pending_operation(str(repo_dir))

        # Run reset from work_dir but specify repo path
        monkeypatch.chdir(work_dir)
        result = cli_runner.invoke(
            main, ["reset", str(repo_dir), "-y"], catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Successfully deleted 1 pending operation(s)" in result.output

        # Verify pending operation was deleted
        session_gen = get_session()
        session = next(session_gen)
        try:
            ops_after = session.query(PendingOperation).all()
            assert len(ops_after) == 0
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass
