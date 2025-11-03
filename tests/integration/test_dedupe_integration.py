"""Integration tests for the 'docman dedupe' command."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from docman.cli import main
from docman.database import ensure_database, get_session
from docman.models import Document, DocumentCopy, Operation, OperationStatus


class TestDocmanDedupe:
    """Integration tests for docman dedupe command."""

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

    def create_duplicate_group(
        self,
        repo_root: Path,
        document_hash: str,
        file_paths: list[str],
        content: str = "Duplicate content",
    ) -> None:
        """Helper to create a duplicate group for testing.

        Args:
            repo_root: Path to the repository root.
            document_hash: Content hash for the document.
            file_paths: List of file paths to create as duplicates.
            content: Content to write to the files.
        """
        ensure_database()
        session_gen = get_session()
        session = next(session_gen)
        try:
            # Create one document with multiple copies
            doc = Document(content_hash=document_hash, content=content)
            session.add(doc)
            session.flush()

            for file_path in file_paths:
                # Create actual files
                full_path = repo_root / file_path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content)

                # Create database copy
                copy = DocumentCopy(
                    document_id=doc.id,
                    repository_path=str(repo_root),
                    file_path=file_path,
                )
                session.add(copy)

            session.commit()
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_dedupe_shows_duplicate_groups(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that dedupe shows duplicate groups with correct metadata."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create 2 duplicate groups
        self.create_duplicate_group(
            repo_dir,
            "hash1",
            ["inbox/doc1.pdf", "archive/doc1.pdf", "backup/doc1.pdf"],
        )
        self.create_duplicate_group(
            repo_dir,
            "hash2",
            ["docs/doc2.pdf", "downloads/doc2.pdf"],
        )

        # Run dedupe in dry-run + bulk mode to avoid prompts
        result = cli_runner.invoke(main, ["dedupe", "-y", "--dry-run"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Found 2 duplicate group(s)" in result.output
        assert "Total copies: 5" in result.output
        assert "inbox/doc1.pdf" in result.output
        assert "archive/doc1.pdf" in result.output
        assert "docs/doc2.pdf" in result.output

    def test_dedupe_interactive_mode_keep_choice(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test dedupe interactive mode with keep choice."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create duplicate group
        file_paths = ["inbox/report.pdf", "backup/report.pdf", "downloads/report.pdf"]
        self.create_duplicate_group(repo_dir, "hash1", file_paths)

        # Mock user choosing to keep first copy (choice "1") and confirming deletion
        result = cli_runner.invoke(
            main, ["dedupe"], input="1\ny\n", catch_exceptions=False
        )

        assert result.exit_code == 0
        # First copy should exist
        assert (repo_dir / "inbox/report.pdf").exists()
        # Others should be deleted
        assert not (repo_dir / "backup/report.pdf").exists()
        assert not (repo_dir / "downloads/report.pdf").exists()

        # Check database
        session_gen = get_session()
        session = next(session_gen)
        try:
            copies = session.query(DocumentCopy).filter(
                DocumentCopy.repository_path == str(repo_dir)
            ).all()
            assert len(copies) == 1
            assert copies[0].file_path == "inbox/report.pdf"
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_dedupe_interactive_mode_skip_group(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test dedupe interactive mode with skip choice."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create duplicate group
        file_paths = ["inbox/report.pdf", "backup/report.pdf"]
        self.create_duplicate_group(repo_dir, "hash1", file_paths)

        # Mock user choosing to skip (choice "s")
        result = cli_runner.invoke(
            main, ["dedupe"], input="s\n", catch_exceptions=False
        )

        assert result.exit_code == 0
        # All copies should still exist
        assert (repo_dir / "inbox/report.pdf").exists()
        assert (repo_dir / "backup/report.pdf").exists()

        # Check database
        session_gen = get_session()
        session = next(session_gen)
        try:
            copies = session.query(DocumentCopy).filter(
                DocumentCopy.repository_path == str(repo_dir)
            ).all()
            assert len(copies) == 2
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_dedupe_interactive_mode_keep_all(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test dedupe interactive mode with keep all choice."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create duplicate group
        file_paths = ["inbox/report.pdf", "backup/report.pdf"]
        self.create_duplicate_group(repo_dir, "hash1", file_paths)

        # Mock user choosing to keep all (choice "a")
        result = cli_runner.invoke(
            main, ["dedupe"], input="a\n", catch_exceptions=False
        )

        assert result.exit_code == 0
        # All copies should still exist
        assert (repo_dir / "inbox/report.pdf").exists()
        assert (repo_dir / "backup/report.pdf").exists()

        # Check database
        session_gen = get_session()
        session = next(session_gen)
        try:
            copies = session.query(DocumentCopy).filter(
                DocumentCopy.repository_path == str(repo_dir)
            ).all()
            assert len(copies) == 2
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_dedupe_bulk_mode(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test dedupe bulk mode (-y flag)."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create 3 duplicate groups
        self.create_duplicate_group(
            repo_dir, "hash1", ["inbox/doc1.pdf", "backup/doc1.pdf"]
        )
        self.create_duplicate_group(
            repo_dir, "hash2", ["docs/doc2.pdf", "archive/doc2.pdf"]
        )
        self.create_duplicate_group(
            repo_dir, "hash3", ["downloads/doc3.pdf", "temp/doc3.pdf", "old/doc3.pdf"]
        )

        # Run with -y flag
        result = cli_runner.invoke(main, ["dedupe", "-y"], catch_exceptions=False)

        assert result.exit_code == 0
        # First copy of each group should be kept
        assert (repo_dir / "inbox/doc1.pdf").exists()
        assert (repo_dir / "docs/doc2.pdf").exists()
        assert (repo_dir / "downloads/doc3.pdf").exists()
        # Others should be deleted
        assert not (repo_dir / "backup/doc1.pdf").exists()
        assert not (repo_dir / "archive/doc2.pdf").exists()
        assert not (repo_dir / "temp/doc3.pdf").exists()
        assert not (repo_dir / "old/doc3.pdf").exists()

        # Check database
        session_gen = get_session()
        session = next(session_gen)
        try:
            copies = session.query(DocumentCopy).filter(
                DocumentCopy.repository_path == str(repo_dir)
            ).all()
            assert len(copies) == 3
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_dedupe_dry_run(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test dedupe dry-run mode."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create duplicate group
        file_paths = ["inbox/report.pdf", "backup/report.pdf"]
        self.create_duplicate_group(repo_dir, "hash1", file_paths)

        # Run with --dry-run and provide input to keep first copy
        result = cli_runner.invoke(main, ["dedupe", "--dry-run"], input="1\n", catch_exceptions=False)

        assert result.exit_code == 0
        assert "DRY RUN" in result.output
        # All files should still exist
        assert (repo_dir / "inbox/report.pdf").exists()
        assert (repo_dir / "backup/report.pdf").exists()

        # Check database unchanged
        session_gen = get_session()
        session = next(session_gen)
        try:
            copies = session.query(DocumentCopy).filter(
                DocumentCopy.repository_path == str(repo_dir)
            ).all()
            assert len(copies) == 2
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_dedupe_with_path_filter(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test dedupe with path filter."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create duplicates in different directories
        self.create_duplicate_group(
            repo_dir, "hash1", ["docs/doc1.pdf", "docs/backup/doc1.pdf"]
        )
        self.create_duplicate_group(
            repo_dir, "hash2", ["archive/doc2.pdf", "archive/old/doc2.pdf"]
        )

        # Run dedupe with docs/ filter
        result = cli_runner.invoke(main, ["dedupe", "docs/", "-y"], catch_exceptions=False)

        assert result.exit_code == 0
        # Only docs duplicates should be processed
        assert (repo_dir / "docs/doc1.pdf").exists()
        assert not (repo_dir / "docs/backup/doc1.pdf").exists()
        # Archive duplicates should be untouched
        assert (repo_dir / "archive/doc2.pdf").exists()
        assert (repo_dir / "archive/old/doc2.pdf").exists()

        # Check database
        session_gen = get_session()
        session = next(session_gen)
        try:
            copies = session.query(DocumentCopy).filter(
                DocumentCopy.repository_path == str(repo_dir)
            ).all()
            # Should have 3 copies remaining (1 from docs, 2 from archive)
            assert len(copies) == 3
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_dedupe_deletes_pending_operations(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that dedupe deletes pending operations (cascade)."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create duplicate group
        file_paths = ["inbox/report.pdf", "backup/report.pdf"]
        self.create_duplicate_group(repo_dir, "hash1", file_paths)

        # Create pending operations for the duplicates
        session_gen = get_session()
        session = next(session_gen)
        try:
            copies = session.query(DocumentCopy).filter(
                DocumentCopy.repository_path == str(repo_dir)
            ).all()
            for copy in copies:
                pending_op = Operation(
                    document_copy_id=copy.id,
                    suggested_directory_path="organized",
                    suggested_filename=f"organized_{Path(copy.file_path).name}",
                    reason="Test organization",
                    confidence=0.85,
                    prompt_hash="test_hash",
                )
                session.add(pending_op)
            session.commit()
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

        # Run dedupe
        result = cli_runner.invoke(main, ["dedupe", "-y"], catch_exceptions=False)

        assert result.exit_code == 0

        # Check that operations are preserved but orphaned copy's operation has NULL document_copy_id
        session_gen = get_session()
        session = next(session_gen)
        try:
            ops = session.query(Operation).all()
            # 2 operations: 1 orphaned (document_copy_id=None) from deleted copy, 1 for kept copy
            assert len(ops) == 2
            orphaned_ops = [op for op in ops if op.document_copy_id is None]
            active_ops = [op for op in ops if op.document_copy_id is not None]
            assert len(orphaned_ops) == 1
            assert len(active_ops) == 1
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_dedupe_no_duplicates(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test dedupe when no duplicates exist."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create unique documents only
        self.create_duplicate_group(repo_dir, "hash1", ["inbox/doc1.pdf"])
        self.create_duplicate_group(repo_dir, "hash2", ["docs/doc2.pdf"])

        # Run dedupe
        result = cli_runner.invoke(main, ["dedupe"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "No duplicate files found" in result.output

    def test_dedupe_handles_missing_files(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test dedupe gracefully handles missing files."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)
        monkeypatch.chdir(repo_dir)

        # Create duplicate group
        file_paths = ["inbox/report.pdf", "backup/report.pdf"]
        self.create_duplicate_group(repo_dir, "hash1", file_paths)

        # Delete one file from disk (but keep database entry)
        (repo_dir / "backup/report.pdf").unlink()

        # Run dedupe with -y flag
        result = cli_runner.invoke(main, ["dedupe", "-y"], catch_exceptions=False)

        assert result.exit_code == 0
        # Should complete successfully
        assert (repo_dir / "inbox/report.pdf").exists()

    def test_dedupe_outside_repository(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test dedupe outside a repository."""
        # Create a directory but don't initialize as repository
        work_dir = tmp_path / "not_a_repo"
        work_dir.mkdir()
        monkeypatch.chdir(work_dir)

        # Set up isolated app config
        app_config_dir = tmp_path / "app_config"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(app_config_dir))

        # Run dedupe
        result = cli_runner.invoke(main, ["dedupe"], catch_exceptions=False)

        assert result.exit_code == 1
        assert "Not in a docman repository" in result.output
