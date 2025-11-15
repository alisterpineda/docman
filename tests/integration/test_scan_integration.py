"""Integration tests for the 'docman scan' command."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

from conftest import setup_repository
from docman.cli import main
from docman.database import get_session
from docman.models import Document, DocumentCopy


@pytest.mark.integration
class TestDocmanScan:
    """Integration tests for docman scan command."""

    @patch("docman.processor.extract_content")
    def test_scan_success_with_documents(
        self,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test successful scan execution with documents."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create test documents
        (repo_dir / "test1.pdf").write_text("content1")
        (repo_dir / "test2.docx").write_text("content2")

        # Mock content extraction
        mock_extract.return_value = "Extracted content"

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run scan command
        result = cli_runner.invoke(main, ["scan", "-r"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output
        assert "Scanning documents in repository:" in result.output
        assert "Found 2 document file(s)" in result.output
        assert "Scanning: test1.pdf" in result.output or "Scanning: test2.docx" in result.output
        assert "Summary:" in result.output
        assert "New documents: 2" in result.output

        # Verify documents and copies were added to database
        session_gen = get_session()
        session = next(session_gen)
        try:
            docs = session.query(Document).all()
            assert len(docs) == 2
            assert all(doc.content == "Extracted content" for doc in docs)

            copies = session.query(DocumentCopy).all()
            assert len(copies) == 2
            assert any(copy.file_path == "test1.pdf" for copy in copies)
            assert any(copy.file_path == "test2.docx" for copy in copies)
            assert all(copy.repository_path == str(repo_dir) for copy in copies)
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    @patch("docman.processor.extract_content")
    def test_scan_skips_already_scanned(
        self,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that scan skips files that haven't changed."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create test document
        test_file = repo_dir / "test.pdf"
        test_file.write_text("content")

        # Mock content extraction
        mock_extract.return_value = "Extracted content"

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run scan command first time
        result = cli_runner.invoke(main, ["scan", "-r"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "New documents: 1" in result.output

        # Run scan command second time - should skip unchanged file
        result = cli_runner.invoke(main, ["scan", "-r"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "Skipped (already scanned): 1" in result.output
        assert "New documents: 0" in result.output

    @patch("docman.processor.extract_content")
    def test_scan_non_recursive_by_default(
        self,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that scan is non-recursive by default."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create documents in root and subdirectory
        (repo_dir / "root.pdf").write_text("root content")
        subdir = repo_dir / "subdir"
        subdir.mkdir()
        (subdir / "nested.pdf").write_text("nested content")

        # Mock content extraction
        mock_extract.return_value = "Content"

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run scan command without -r flag
        result = cli_runner.invoke(main, ["scan"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify only root file was scanned
        assert "Found 1 document file(s)" in result.output
        assert "New documents: 1" in result.output

        # Verify only one document in database
        session_gen = get_session()
        session = next(session_gen)
        try:
            docs = session.query(Document).all()
            assert len(docs) == 1

            copies = session.query(DocumentCopy).all()
            assert len(copies) == 1
            assert copies[0].file_path == "root.pdf"
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    @patch("docman.processor.extract_content")
    def test_scan_with_rescan_flag(
        self,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that scan --rescan forces re-scanning of all files."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create test document
        test_file = repo_dir / "test.pdf"
        test_file.write_text("original content")

        # Mock content extraction
        mock_extract.return_value = "Extracted content"

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run scan command first time
        result = cli_runner.invoke(main, ["scan", "-r"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "New documents: 1" in result.output

        # Modify file content
        test_file.write_text("modified content")

        # Run scan with --rescan flag
        result = cli_runner.invoke(main, ["scan", "-r", "--rescan"], catch_exceptions=False)
        assert result.exit_code == 0
        # With rescan, it should detect the change
        assert "Content updated" in result.output or "New document" in result.output

    def test_scan_no_documents(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test scan when no document files are found."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create non-document files
        (repo_dir / "test.py").touch()
        (repo_dir / "test.js").touch()

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run scan command
        result = cli_runner.invoke(main, ["scan", "-r"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output
        assert "No document files found." in result.output

        # Verify no documents were added to database
        session_gen = get_session()
        session = next(session_gen)
        try:
            docs = session.query(Document).all()
            assert len(docs) == 0
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_scan_fails_outside_repository(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that scan fails when not in a repository."""
        # Change to the temporary directory (no repository)
        monkeypatch.chdir(tmp_path)

        result = cli_runner.invoke(main, ["scan"])

        # Verify exit code
        assert result.exit_code == 1

        # Verify error message
        assert "Error" in result.output
        assert "Not in a docman repository" in result.output

    @patch("docman.processor.extract_content")
    def test_scan_single_file(
        self,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test scan with a single file path."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create test documents
        (repo_dir / "target.pdf").write_text("target")
        (repo_dir / "other.pdf").write_text("other")

        # Mock content extraction
        mock_extract.return_value = "Content"

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run scan command with specific file
        result = cli_runner.invoke(main, ["scan", "target.pdf"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify only target file was scanned
        assert "Scanning single file: target.pdf" in result.output
        assert "New documents: 1" in result.output

        # Verify only one document in database
        session_gen = get_session()
        session = next(session_gen)
        try:
            docs = session.query(Document).all()
            assert len(docs) == 1

            copies = session.query(DocumentCopy).all()
            assert len(copies) == 1
            assert copies[0].file_path == "target.pdf"
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    @patch("docman.processor.extract_content")
    def test_scan_directory_path(
        self,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test scan with a directory path."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create documents in different directories
        (repo_dir / "root.pdf").write_text("root")
        subdir = repo_dir / "docs"
        subdir.mkdir()
        (subdir / "doc.pdf").write_text("doc")

        # Mock content extraction
        mock_extract.return_value = "Content"

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run scan command with directory path (non-recursive)
        result = cli_runner.invoke(main, ["scan", "docs/"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify only docs directory was scanned
        assert "docs" in result.output
        assert "New documents: 1" in result.output

        # Run scan with recursive flag
        result = cli_runner.invoke(main, ["scan", "docs/", "-r"], catch_exceptions=False)

        # Should show as already scanned
        assert "Skipped (already scanned): 1" in result.output

    @patch("docman.processor.extract_content")
    def test_scan_batch_commits(
        self,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that scan commits in batches of 10 files."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create 25 test documents to span multiple batches
        for i in range(25):
            (repo_dir / f"test{i:02d}.pdf").write_text(f"content{i}")

        # Mock content extraction
        mock_extract.return_value = "Extracted content"

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run scan command
        result = cli_runner.invoke(main, ["scan", "-r"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify batch commit messages appear
        assert "Batch 1 committed (10 files processed)" in result.output
        assert "Batch 2 committed (20 files processed)" in result.output
        assert "Final batch committed (25 files processed)" in result.output

        # Verify batch information in progress display
        assert "(Batch 1)" in result.output
        assert "(Batch 2)" in result.output
        assert "(Batch 3)" in result.output

        # Verify all documents were committed to database
        session_gen = get_session()
        session = next(session_gen)
        try:
            docs = session.query(Document).all()
            assert len(docs) == 25

            copies = session.query(DocumentCopy).all()
            assert len(copies) == 25
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    @patch("docman.processor.extract_content")
    def test_scan_batch_commit_error_handling(
        self,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that scan handles database commit errors gracefully."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create 15 test documents to trigger 2 batches
        for i in range(15):
            (repo_dir / f"test{i:02d}.pdf").write_text(f"content{i}")

        # Mock content extraction
        mock_extract.return_value = "Extracted content"

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Track commit calls and fail on the second batch commit
        commit_count = {"count": 0}

        def commit_with_error():
            """Simulate commit error on second batch commit."""
            commit_count["count"] += 1
            # First commit is from cleanup_orphaned_copies, second is batch 1
            # Third commit (batch 2) should fail
            if commit_count["count"] == 3:
                raise Exception("Database commit failed")
            # For successful commits, just return (no-op is fine for testing error handling)

        # Patch Session.commit to track calls and raise on the third one
        with patch("sqlalchemy.orm.session.Session.commit", side_effect=commit_with_error):
            # Run scan command - should fail on second batch commit
            result = cli_runner.invoke(main, ["scan", "-r"])

            # Should exit with error code
            assert result.exit_code == 1

            # Verify error message appears (can be batch or final batch)
            assert "Error: Failed to commit" in result.output
            assert "Database commit failed" in result.output

            # Verify we got through the first batch successfully
            assert "Batch 1 committed (10 files processed)" in result.output
