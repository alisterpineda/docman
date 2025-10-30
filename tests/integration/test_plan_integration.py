"""Integration tests for the 'docman plan' command."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

from docman.cli import main
from docman.database import ensure_database, get_session
from docman.models import Document, DocumentCopy


class TestDocmanPlan:
    """Integration tests for docman plan command."""

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
    def test_plan_success_with_documents(
        self,
        mock_hash: Mock,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test successful plan execution with documents."""
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

        # Run plan command
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output
        assert "Processing documents in repository:" in result.output
        assert "Found 2 document file(s)" in result.output
        assert "Processing: test1.pdf" in result.output or "Processing: test2.docx" in result.output
        assert "Summary:" in result.output
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
    def test_plan_skips_existing_documents(
        self,
        mock_hash: Mock,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that plan skips document copies already in the same repository."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create test documents
        (repo_dir / "test1.pdf").touch()
        (repo_dir / "test2.pdf").touch()

        # Ensure database is initialized
        ensure_database()

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
            )
            session.add(existing_copy)
            session.commit()
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

        # Mock content hash and extraction
        mock_hash.side_effect = ["hash2"]  # test2.pdf gets new hash
        mock_extract.return_value = "New content"

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output
        assert "Skipping: test1.pdf" in result.output
        assert "Processing: test2.pdf" in result.output
        assert "New documents processed: 1" in result.output
        assert "Skipped (copy exists in this repo): 1" in result.output

        # Verify one new document and copy were added
        session_gen = get_session()
        session = next(session_gen)
        try:
            docs = session.query(Document).all()
            assert len(docs) == 2

            copies = session.query(DocumentCopy).all()
            assert len(copies) == 2
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    @patch("docman.cli.extract_content")
    @patch("docman.cli.compute_content_hash")
    def test_plan_handles_extraction_failures(
        self,
        mock_hash: Mock,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that plan handles extraction failures gracefully."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create test documents
        (repo_dir / "success.pdf").touch()
        (repo_dir / "failure.pdf").touch()

        # Mock content hash based on filename
        def hash_side_effect(path: Path) -> str:
            if "failure" in str(path):
                return "hash_failure"
            return "hash_success"

        mock_hash.side_effect = hash_side_effect

        # Mock content extraction to return None for failure
        def extract_side_effect(path: Path) -> str | None:
            if "failure" in str(path):
                return None
            return "Extracted content"

        mock_extract.side_effect = extract_side_effect

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output
        assert "Processing: failure.pdf" in result.output
        assert "Processing: success.pdf" in result.output
        assert "New documents processed: 1" in result.output
        assert "Failed (hash or extraction errors): 1" in result.output

        # Verify both documents were added (one with null content)
        session_gen = get_session()
        session = next(session_gen)
        try:
            docs = session.query(Document).all()
            assert len(docs) == 2

            copies = session.query(DocumentCopy).all()
            assert len(copies) == 2

            # Find the success document
            success_doc = (
                session.query(Document).filter_by(content_hash="hash_success").first()
            )
            assert success_doc.content == "Extracted content"

            # Find the failure document
            failure_doc = (
                session.query(Document).filter_by(content_hash="hash_failure").first()
            )
            assert failure_doc.content is None
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_plan_fails_outside_repository(self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that plan fails when not in a repository."""
        # Change to the temporary directory
        monkeypatch.chdir(tmp_path)

        result = cli_runner.invoke(main, ["plan"])

        # Verify exit code
        assert result.exit_code == 1

        # Verify error message
        assert "Error" in result.output
        assert "Not in a docman repository" in result.output

    def test_plan_fails_with_invalid_repository(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that plan fails when repository is invalid."""
        # Create .docman directory but no config.yaml
        docman_dir = tmp_path / ".docman"
        docman_dir.mkdir()

        # Change to the temporary directory
        monkeypatch.chdir(tmp_path)

        result = cli_runner.invoke(main, ["plan"])

        # Verify exit code
        assert result.exit_code == 1

        # Verify error message
        assert "Error" in result.output
        assert "Invalid docman repository" in result.output

    @patch("docman.cli.extract_content")
    def test_plan_no_documents(
        self, mock_extract: Mock, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test plan when no document files are found."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create non-document files
        (repo_dir / "test.py").touch()
        (repo_dir / "test.js").touch()

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output
        assert "No document files found in repository." in result.output

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

    @patch("docman.cli.extract_content")
    @patch("docman.cli.compute_content_hash")
    def test_plan_discovers_nested_documents(
        self,
        mock_hash: Mock,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that plan discovers documents in nested directories."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create nested directories with documents
        subdir1 = repo_dir / "docs" / "reports"
        subdir1.mkdir(parents=True)
        subdir2 = repo_dir / "data"
        subdir2.mkdir()

        (repo_dir / "root.pdf").touch()
        (subdir1 / "report.docx").touch()
        (subdir2 / "data.xlsx").touch()

        # Mock content hash to return unique hashes
        mock_hash.side_effect = ["hash_data", "hash_report", "hash_root"]

        # Mock content extraction
        mock_extract.return_value = "Content"

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output
        assert "Found 3 document file(s)" in result.output
        assert "New documents processed: 3" in result.output

        # Verify all documents and copies were added with correct paths
        session_gen = get_session()
        session = next(session_gen)
        try:
            docs = session.query(Document).all()
            assert len(docs) == 3

            copies = session.query(DocumentCopy).all()
            assert len(copies) == 3

            paths = {copy.file_path for copy in copies}
            assert "root.pdf" in paths
            assert "docs/reports/report.docx" in paths or "docs\\reports\\report.docx" in paths
            assert "data/data.xlsx" in paths or "data\\data.xlsx" in paths
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    @patch("docman.cli.extract_content")
    def test_plan_excludes_docman_directory(
        self, mock_extract: Mock, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that plan excludes files in .docman directory."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create documents
        (repo_dir / "include.pdf").touch()
        (repo_dir / ".docman" / "exclude.pdf").touch()

        # Mock content extraction
        mock_extract.return_value = "Content"

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify only one document was found
        assert "Found 1 document file(s)" in result.output
        assert "include.pdf" in result.output
        assert "exclude.pdf" not in result.output

        # Verify only one document and copy were added
        session_gen = get_session()
        session = next(session_gen)
        try:
            docs = session.query(Document).all()
            assert len(docs) == 1

            copies = session.query(DocumentCopy).all()
            assert len(copies) == 1
            assert copies[0].file_path == "include.pdf"
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    @patch("docman.cli.extract_content")
    def test_plan_shows_progress(
        self, mock_extract: Mock, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that plan shows progress indicators."""
        # Set up repository
        self.setup_repository(tmp_path)

        # Create multiple documents
        for i in range(5):
            (tmp_path / f"test{i}.pdf").touch()

        # Mock content extraction
        mock_extract.return_value = "Content"

        # Change to the repository directory
        monkeypatch.chdir(tmp_path)

        # Run plan command
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify progress indicators
        assert "[1/5]" in result.output
        assert "[5/5]" in result.output
        assert "20%" in result.output
        assert "100%" in result.output

    @patch("docman.cli.extract_content")
    def test_plan_from_subdirectory(
        self, mock_extract: Mock, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that plan works when run from a subdirectory."""
        # Set up repository in root
        self.setup_repository(tmp_path)

        # Create subdirectory
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        # Create document in root
        (tmp_path / "test.pdf").touch()

        # Mock content extraction
        mock_extract.return_value = "Content"

        # Run plan command from subdirectory
        monkeypatch.chdir(subdir)

        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify it found the repository root and processed the document
        assert "Processing documents in repository:" in result.output
        assert str(tmp_path) in result.output
        assert "Found 1 document file(s)" in result.output
