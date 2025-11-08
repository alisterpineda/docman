"""Integration tests for the 'docman scan' command."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

from docman.cli import main
from docman.database import get_session
from docman.models import Document, DocumentCopy


class TestDocmanScan:
    """Integration tests for docman scan command."""

    def setup_repository(self, path: Path) -> None:
        """Set up a docman repository for testing."""
        docman_dir = path / ".docman"
        docman_dir.mkdir()
        config_file = docman_dir / "config.yaml"
        config_file.touch()

    def setup_isolated_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """Set up isolated environment with separate app config and repository."""
        app_config_dir = tmp_path / "app_config"
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(app_config_dir))
        self.setup_repository(repo_dir)
        return repo_dir

    @patch("docman.cli.extract_content")
    @patch("docman.cli.compute_content_hash")
    def test_scan_success_with_documents(
        self,
        mock_hash: Mock,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test successful scan execution with documents."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create test documents
        (repo_dir / "test1.pdf").touch()
        (repo_dir / "test2.docx").touch()

        # Mock content hash to return unique hashes
        mock_hash.side_effect = ["hash_test1", "hash_test2"]

        # Mock content extraction
        mock_extract.return_value = "Extracted content"

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run scan command
        result = cli_runner.invoke(main, ["scan"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output
        assert "Scanning documents in repository:" in result.output
        assert "Found 2 document file(s)" in result.output
        assert "Processing: test1.pdf" in result.output or "Processing: test2.docx" in result.output
        assert "Scan Summary:" in result.output
        assert "New documents processed: 2" in result.output

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

    @patch("docman.cli.extract_content")
    @patch("docman.cli.compute_content_hash")
    def test_scan_skips_existing_documents(
        self,
        mock_hash: Mock,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that scan reuses existing document copies."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create test document
        test_file = repo_dir / "test1.pdf"
        test_file.touch()

        # Get file metadata
        stat = test_file.stat()

        # Add existing document and copy to database
        session_gen = get_session()
        session = next(session_gen)
        try:
            existing_doc = Document(content_hash="hash1", content="Existing content")
            session.add(existing_doc)
            session.flush()

            existing_copy = DocumentCopy(
                document_id=existing_doc.id,
                repository_path=str(repo_dir),
                file_path="test1.pdf",
                stored_content_hash="hash1",
                stored_size=stat.st_size,
                stored_mtime=stat.st_mtime,
            )
            session.add(existing_copy)
            session.commit()
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

        # Mock content hash to return same hash (no change)
        mock_hash.return_value = "hash1"

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run scan command
        result = cli_runner.invoke(main, ["scan"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output shows reuse
        assert "Reusing existing copy" in result.output
        assert "Scan Summary:" in result.output
        assert "Reused copies (already in this repo): 1" in result.output

        # extract_content should not be called since content didn't change
        mock_extract.assert_not_called()

    @patch("docman.cli.extract_content")
    @patch("docman.cli.compute_content_hash")
    def test_scan_single_file(
        self,
        mock_hash: Mock,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test scanning a single file."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create test documents
        (repo_dir / "test1.pdf").touch()
        (repo_dir / "test2.pdf").touch()

        # Mock content hash
        mock_hash.return_value = "hash_test1"

        # Mock content extraction
        mock_extract.return_value = "Extracted content"

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run scan command on single file
        result = cli_runner.invoke(main, ["scan", "test1.pdf"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output
        assert "Processing single file: test1.pdf" in result.output
        assert "Scan Summary:" in result.output

        # Verify only one document was scanned
        session_gen = get_session()
        session = next(session_gen)
        try:
            copies = session.query(DocumentCopy).all()
            assert len(copies) == 1
            assert copies[0].file_path == "test1.pdf"
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    @patch("docman.cli.extract_content")
    @patch("docman.cli.compute_content_hash")
    def test_scan_directory_non_recursive(
        self,
        mock_hash: Mock,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test scanning a directory non-recursively."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create test documents
        (repo_dir / "test1.pdf").touch()
        subdir = repo_dir / "subdir"
        subdir.mkdir()
        (subdir / "test2.pdf").touch()

        # Mock content hash
        mock_hash.return_value = "hash_test1"

        # Mock content extraction
        mock_extract.return_value = "Extracted content"

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run scan command on directory without -r flag
        result = cli_runner.invoke(main, ["scan", "."], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify only the file in the root directory was scanned
        session_gen = get_session()
        session = next(session_gen)
        try:
            copies = session.query(DocumentCopy).all()
            assert len(copies) == 1
            assert copies[0].file_path == "test1.pdf"
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    @patch("docman.cli.extract_content")
    @patch("docman.cli.compute_content_hash")
    def test_scan_directory_recursive(
        self,
        mock_hash: Mock,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test scanning a directory recursively."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create test documents
        (repo_dir / "test1.pdf").touch()
        subdir = repo_dir / "subdir"
        subdir.mkdir()
        (subdir / "test2.pdf").touch()

        # Mock content hash
        mock_hash.side_effect = ["hash_test1", "hash_test2"]

        # Mock content extraction
        mock_extract.return_value = "Extracted content"

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run scan command on directory with -r flag
        result = cli_runner.invoke(main, ["scan", ".", "-r"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify both files were scanned
        session_gen = get_session()
        session = next(session_gen)
        try:
            copies = session.query(DocumentCopy).all()
            assert len(copies) == 2
            assert any(copy.file_path == "test1.pdf" for copy in copies)
            assert any(copy.file_path == "subdir/test2.pdf" for copy in copies)
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass
