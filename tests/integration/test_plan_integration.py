"""Integration tests for the 'docman plan' command."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

from docman.cli import main
from docman.database import ensure_database, get_session
from docman.llm_config import ProviderConfig
from docman.models import Document, DocumentCopy, Operation, OperationStatus


class TestDocmanPlan:
    """Integration tests for docman plan command."""

    @pytest.fixture(autouse=True)
    def _mock_llm_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Automatically mock LLM provider for all tests in this class."""
        # Create a mock provider config
        mock_provider_config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )

        # Create mock provider instance
        mock_provider_instance = Mock()
        mock_provider_instance.test_connection.return_value = True
        mock_provider_instance.supports_structured_output = True
        mock_provider_instance.generate_suggestions.return_value = {
            "suggested_directory_path": "test/directory",
            "suggested_filename": "test_file.pdf",
            "reason": "Test reason",
            "confidence": 0.85,
        }

        # Patch the LLM-related functions
        monkeypatch.setattr("docman.cli.get_active_provider", Mock(return_value=mock_provider_config))
        monkeypatch.setattr("docman.cli.get_api_key", Mock(return_value="test-api-key"))
        monkeypatch.setattr("docman.cli.get_llm_provider", Mock(return_value=mock_provider_instance))

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

            # Get file metadata for stored fields
            test_file = repo_dir / "test1.pdf"
            stat = test_file.stat()

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

        # Mock content hash and extraction
        # test1.pdf will be reused (no hash computed), test2.pdf gets hash2 for new document
        mock_hash.side_effect = ["hash2"]
        mock_extract.return_value = "New content"

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output
        assert "Reusing existing copy: test1.pdf" in result.output
        assert "Processing: test2.pdf" in result.output
        assert "New documents processed: 1" in result.output
        assert "Reused copies (already in this repo): 1" in result.output

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
        def extract_side_effect(path: Path, converter=None) -> str | None:
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

    @patch("docman.cli.extract_content")
    @patch("docman.cli.compute_content_hash")
    def test_plan_single_file(
        self,
        mock_hash: Mock,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test plan with a single file path."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create test documents
        (repo_dir / "target.pdf").touch()
        (repo_dir / "other.pdf").touch()

        # Mock content hash
        mock_hash.return_value = "hash_target"

        # Mock content extraction
        mock_extract.return_value = "Target content"

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command with single file
        result = cli_runner.invoke(main, ["plan", "target.pdf"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output
        assert "Processing single file: target.pdf" in result.output
        assert "New documents processed: 1" in result.output

        # Verify only the target file was processed
        session_gen = get_session()
        session = next(session_gen)
        try:
            copies = session.query(DocumentCopy).all()
            assert len(copies) == 1
            assert copies[0].file_path == "target.pdf"
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_plan_single_file_unsupported_type(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test plan with an unsupported file type."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create unsupported file
        (repo_dir / "test.py").touch()

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command with unsupported file
        result = cli_runner.invoke(main, ["plan", "test.py"])

        # Verify exit code
        assert result.exit_code == 1

        # Verify error message
        assert "Error: Unsupported file type '.py'" in result.output
        assert "Supported extensions:" in result.output

    @patch("docman.cli.extract_content")
    @patch("docman.cli.compute_content_hash")
    def test_plan_shallow_directory(
        self,
        mock_hash: Mock,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test plan with directory path (non-recursive)."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create documents in root and subdirectory
        (repo_dir / "root.pdf").touch()
        subdir = repo_dir / "docs"
        subdir.mkdir()
        (subdir / "doc1.pdf").touch()
        (subdir / "doc2.docx").touch()
        nested = subdir / "nested"
        nested.mkdir()
        (nested / "nested.pdf").touch()

        # Mock content hash to return unique hashes
        mock_hash.side_effect = ["hash_doc1", "hash_doc2"]

        # Mock content extraction
        mock_extract.return_value = "Content"

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command with directory path (non-recursive by default)
        result = cli_runner.invoke(main, ["plan", "docs"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output
        assert "Discovering documents in: docs (non-recursive)" in result.output
        assert "New documents processed: 2" in result.output

        # Verify only files in docs/ were processed (not nested/)
        session_gen = get_session()
        session = next(session_gen)
        try:
            copies = session.query(DocumentCopy).all()
            assert len(copies) == 2
            paths = {copy.file_path for copy in copies}
            # Should have docs/doc1.pdf and docs/doc2.docx but not docs/nested/nested.pdf
            assert any("doc1.pdf" in p for p in paths)
            assert any("doc2.docx" in p for p in paths)
            assert not any("nested.pdf" in p for p in paths)
            assert not any("root.pdf" in p for p in paths)
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    @patch("docman.cli.extract_content")
    @patch("docman.cli.compute_content_hash")
    def test_plan_recursive_subdirectory(
        self,
        mock_hash: Mock,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test plan with directory path and recursive flag."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create documents in subdirectory and nested subdirectory
        (repo_dir / "root.pdf").touch()
        subdir = repo_dir / "docs"
        subdir.mkdir()
        (subdir / "doc1.pdf").touch()
        nested = subdir / "nested"
        nested.mkdir()
        (nested / "nested.pdf").touch()

        # Mock content hash to return unique hashes
        mock_hash.side_effect = ["hash_doc1", "hash_nested"]

        # Mock content extraction
        mock_extract.return_value = "Content"

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command with directory path and recursive flag
        result = cli_runner.invoke(main, ["plan", "docs", "-r"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output
        assert "Discovering documents recursively in: docs" in result.output
        assert "New documents processed: 2" in result.output

        # Verify files in docs/ and docs/nested/ were processed
        session_gen = get_session()
        session = next(session_gen)
        try:
            copies = session.query(DocumentCopy).all()
            assert len(copies) == 2
            paths = {copy.file_path for copy in copies}
            # Should have both docs/doc1.pdf and docs/nested/nested.pdf
            assert any("doc1.pdf" in p for p in paths)
            assert any("nested.pdf" in p for p in paths)
            # But not root.pdf
            assert not any("root.pdf" in p for p in paths)
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_plan_path_outside_repository(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that plan fails when path is outside repository."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        (outside_dir / "test.pdf").touch()

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Try to plan with path outside repository
        result = cli_runner.invoke(main, ["plan", str(outside_dir / "test.pdf")])

        # Verify exit code
        assert result.exit_code == 1

        # Verify error message
        assert "Error: Path" in result.output
        assert "is outside the repository" in result.output

    def test_plan_nonexistent_path(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that plan fails when path does not exist."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Try to plan with nonexistent path
        result = cli_runner.invoke(main, ["plan", "nonexistent.pdf"])

        # Verify exit code
        assert result.exit_code == 1

        # Verify error message
        assert "Error: Path 'nonexistent.pdf' does not exist" in result.output

    @patch("docman.cli.extract_content")
    @patch("docman.cli.compute_content_hash")
    def test_plan_backward_compatibility(
        self,
        mock_hash: Mock,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that 'docman plan' without arguments still processes entire repository recursively."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create nested documents
        (repo_dir / "root.pdf").touch()
        subdir = repo_dir / "docs"
        subdir.mkdir()
        (subdir / "doc.pdf").touch()
        nested = subdir / "nested"
        nested.mkdir()
        (nested / "nested.pdf").touch()

        # Mock content hash to return unique hashes
        mock_hash.side_effect = ["hash_doc", "hash_nested", "hash_root"]

        # Mock content extraction
        mock_extract.return_value = "Content"

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command without any arguments (backward compatibility)
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output shows recursive discovery
        assert "Discovering documents recursively in entire repository" in result.output
        assert "Found 3 document file(s)" in result.output
        assert "New documents processed: 3" in result.output

        # Verify all documents were processed
        session_gen = get_session()
        session = next(session_gen)
        try:
            copies = session.query(DocumentCopy).all()
            assert len(copies) == 3
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    @patch("docman.cli.extract_content")
    @patch("docman.cli.compute_content_hash")
    def test_plan_explicit_dot_is_non_recursive(
        self,
        mock_hash: Mock,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that 'docman plan .' explicitly processes current directory non-recursively."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create nested documents
        (repo_dir / "root.pdf").touch()
        subdir = repo_dir / "docs"
        subdir.mkdir()
        (subdir / "doc.pdf").touch()

        # Mock content hash to return unique hashes
        mock_hash.return_value = "hash_root"

        # Mock content extraction
        mock_extract.return_value = "Content"

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command with explicit "." argument
        result = cli_runner.invoke(main, ["plan", "."], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output shows non-recursive discovery
        assert "(non-recursive)" in result.output
        assert "Found 1 document file(s)" in result.output
        assert "New documents processed: 1" in result.output

        # Verify only root document was processed (not nested subdirectory)
        session_gen = get_session()
        session = next(session_gen)
        try:
            copies = session.query(DocumentCopy).all()
            assert len(copies) == 1
            assert copies[0].file_path == "root.pdf"
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    @patch("docman.cli.extract_content")
    @patch("docman.cli.compute_content_hash")
    def test_plan_creates_pending_operations_for_reused_copies(
        self,
        mock_hash: Mock,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that pending operations are created even for reused document copies."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create test document
        (repo_dir / "test.pdf").touch()

        # First run: create document and copy
        mock_hash.return_value = "hash_test"
        mock_extract.return_value = "Test content"
        monkeypatch.chdir(repo_dir)

        result1 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result1.exit_code == 0

        # Verify document, copy, and pending operation were created
        session_gen = get_session()
        session = next(session_gen)
        try:
            docs = session.query(Document).all()
            assert len(docs) == 1

            copies = session.query(DocumentCopy).all()
            assert len(copies) == 1
            copy_id = copies[0].id

            pending_ops = session.query(Operation).all()
            assert len(pending_ops) == 1
            assert pending_ops[0].document_copy_id == copy_id

            # Delete the pending operation (simulating reset)
            session.delete(pending_ops[0])
            session.commit()
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

        # Second run: should reuse copy and recreate pending operation
        result2 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result2.exit_code == 0

        # Verify output shows reused copy
        assert "Reusing existing copy: test.pdf" in result2.output
        assert "Generating LLM suggestions..." in result2.output
        assert "Pending operations created: 1" in result2.output

        # Verify pending operation was recreated
        session_gen = get_session()
        session = next(session_gen)
        try:
            # Still only one document and copy
            docs = session.query(Document).all()
            assert len(docs) == 1

            copies = session.query(DocumentCopy).all()
            assert len(copies) == 1

            # But pending operation was recreated
            pending_ops = session.query(Operation).all()
            assert len(pending_ops) == 1
            assert pending_ops[0].document_copy_id == copy_id
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    @patch("docman.cli.extract_content")
    @patch("docman.cli.compute_content_hash")
    def test_plan_after_reset_workflow(
        self,
        mock_hash: Mock,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test the complete reject --all -> plan workflow recreates pending operations."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create multiple test documents
        (repo_dir / "file1.pdf").touch()
        (repo_dir / "file2.docx").touch()

        mock_hash.side_effect = ["hash1", "hash2", "hash1", "hash2"]
        mock_extract.return_value = "Content"
        monkeypatch.chdir(repo_dir)

        # Step 1: Initial plan - creates everything
        result1 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result1.exit_code == 0
        assert "New documents processed: 2" in result1.output
        assert "Pending operations created: 2" in result1.output

        # Verify initial state
        session_gen = get_session()
        session = next(session_gen)
        try:
            assert len(session.query(Document).all()) == 2
            assert len(session.query(DocumentCopy).all()) == 2
            assert len(session.query(Operation).all()) == 2
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

        # Step 2: Reject all - clears pending operations
        result2 = cli_runner.invoke(main, ["review", "--reject-all", "-y"], catch_exceptions=False)
        assert result2.exit_code == 0
        assert "Successfully rejected 2 pending operation(s)" in result2.output

        # Verify pending operations were marked as REJECTED
        session_gen = get_session()
        session = next(session_gen)
        try:
            assert len(session.query(Document).all()) == 2
            assert len(session.query(DocumentCopy).all()) == 2
            ops = session.query(Operation).all()
            assert len(ops) == 2
            assert all(op.status == OperationStatus.REJECTED for op in ops)
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

        # Step 3: Plan again - reuses copies and recreates pending operations
        result3 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result3.exit_code == 0
        assert "Reusing existing copy: file1.pdf" in result3.output or "Reusing existing copy: file2.docx" in result3.output
        assert "Reused copies (already in this repo): 2" in result3.output
        assert "Pending operations created: 2" in result3.output

        # Verify final state: still 2 documents/copies, now with 4 operations total (2 REJECTED + 2 PENDING)
        session_gen = get_session()
        session = next(session_gen)
        try:
            assert len(session.query(Document).all()) == 2
            assert len(session.query(DocumentCopy).all()) == 2
            ops = session.query(Operation).all()
            assert len(ops) == 4
            # 2 rejected from earlier, 2 new pending
            assert len([op for op in ops if op.status == OperationStatus.REJECTED]) == 2
            assert len([op for op in ops if op.status == OperationStatus.PENDING]) == 2
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    @patch("docman.cli.extract_content")
    @patch("docman.cli.compute_content_hash")
    def test_plan_skips_creating_duplicate_pending_operations(
        self,
        mock_hash: Mock,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that plan doesn't create duplicate pending operations on repeated runs."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create test document
        (repo_dir / "test.pdf").touch()

        mock_hash.return_value = "hash_test"
        mock_extract.return_value = "Test content"
        monkeypatch.chdir(repo_dir)

        # First run: creates everything
        result1 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result1.exit_code == 0
        assert "Processing: test.pdf" in result1.output
        assert "Generating LLM suggestions..." in result1.output
        assert "Pending operations created: 1" in result1.output

        # Second run: reuses copy but doesn't duplicate pending operation
        result2 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result2.exit_code == 0
        assert "Reusing existing copy: test.pdf" in result2.output
        assert "Reusing existing suggestions (prompt unchanged)" in result2.output
        assert "Pending operations created: 0" in result2.output

        # Verify only one of everything exists
        session_gen = get_session()
        session = next(session_gen)
        try:
            assert len(session.query(Document).all()) == 1
            assert len(session.query(DocumentCopy).all()) == 1
            assert len(session.query(Operation).all()) == 1
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    @patch("docman.cli.extract_content")
    @patch("docman.cli.compute_content_hash")
    def test_plan_mixed_new_and_reused_copies(
        self,
        mock_hash: Mock,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test plan with mix of new files and existing copies."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create first document
        (repo_dir / "existing.pdf").touch()

        mock_hash.side_effect = ["hash_existing", "hash_new"]
        mock_extract.return_value = "Content"
        monkeypatch.chdir(repo_dir)

        # First run: create one document
        result1 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result1.exit_code == 0

        # Add a new document
        (repo_dir / "new.pdf").touch()

        # Second run: mix of existing and new
        result2 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result2.exit_code == 0

        # Verify output shows both behaviors
        assert "Reusing existing copy: existing.pdf" in result2.output
        assert "Processing: new.pdf" in result2.output
        assert "New documents processed: 1" in result2.output
        assert "Reused copies (already in this repo): 1" in result2.output
        assert "Pending operations created: 1" in result2.output  # Only new file creates pending op

        # Verify database state
        session_gen = get_session()
        session = next(session_gen)
        try:
            assert len(session.query(Document).all()) == 2
            assert len(session.query(DocumentCopy).all()) == 2
            # Both should have pending operations (one from first run, one from second)
            assert len(session.query(Operation).all()) == 2
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_plan_fails_without_instructions(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that plan fails with error when instructions are missing."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Remove the instructions file that setup_repository creates
        instructions_file = repo_dir / ".docman" / "instructions.md"
        instructions_file.unlink()

        # Create a test document
        (repo_dir / "test.pdf").touch()

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Verify it fails with appropriate error
        assert result.exit_code == 1
        assert "Error: Document organization instructions are required" in result.output
        assert "Run 'docman config set-instructions' to create them" in result.output

    @patch("docman.cli.extract_content")
    @patch("docman.cli.compute_content_hash")
    def test_plan_detects_stale_content(
        self,
        mock_hash: Mock,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that plan detects when file content changes and regenerates suggestions."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create test document with initial content
        test_file = repo_dir / "test.pdf"
        test_file.write_text("Initial content")

        # First run: create document with initial hash
        mock_hash.return_value = "hash_initial"
        mock_extract.return_value = "Initial extracted content"
        monkeypatch.chdir(repo_dir)

        result1 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result1.exit_code == 0
        assert "Processing: test.pdf" in result1.output

        # Verify initial state
        session_gen = get_session()
        session = next(session_gen)
        try:
            docs = session.query(Document).all()
            assert len(docs) == 1
            assert docs[0].content_hash == "hash_initial"
            assert docs[0].content == "Initial extracted content"

            copies = session.query(DocumentCopy).all()
            assert len(copies) == 1
            initial_copy_id = copies[0].id

            pending_ops = session.query(Operation).all()
            assert len(pending_ops) == 1
            assert pending_ops[0].document_content_hash == "hash_initial"
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

        # Modify file content (same path, different content)
        test_file.write_text("Modified content - much longer to change size")

        # Second run: should detect change, re-extract, and regenerate suggestions
        mock_hash.return_value = "hash_modified"
        mock_extract.return_value = "Modified extracted content"

        result2 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result2.exit_code == 0
        assert "Checking for changes: test.pdf" in result2.output
        assert "Content changed, updating document..." in result2.output
        assert "Extracted" in result2.output

        # Verify content was re-extracted and suggestion regenerated
        session_gen = get_session()
        session = next(session_gen)
        try:
            # Should have two documents now (old and new content)
            docs = session.query(Document).all()
            assert len(docs) == 2

            # Find the new document
            new_doc = session.query(Document).filter_by(content_hash="hash_modified").first()
            assert new_doc is not None
            assert new_doc.content == "Modified extracted content"

            # Copy should still exist with same ID but point to new document
            copies = session.query(DocumentCopy).all()
            assert len(copies) == 1
            assert copies[0].id == initial_copy_id
            assert copies[0].document_id == new_doc.id

            # Pending operation should be regenerated with new content hash
            pending_ops = session.query(Operation).all()
            assert len(pending_ops) == 1
            assert pending_ops[0].document_content_hash == "hash_modified"
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    @patch("docman.cli.extract_content")
    @patch("docman.cli.compute_content_hash")
    def test_plan_cleans_up_deleted_files(
        self,
        mock_hash: Mock,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that plan cleans up DocumentCopy and Operation when file is deleted."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create multiple test documents
        file1 = repo_dir / "file1.pdf"
        file2 = repo_dir / "file2.pdf"
        file1.touch()
        file2.touch()

        # First run: create documents and copies
        mock_hash.side_effect = ["hash1", "hash2"]
        mock_extract.return_value = "Content"
        monkeypatch.chdir(repo_dir)

        result1 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result1.exit_code == 0
        assert "New documents processed: 2" in result1.output

        # Verify initial state
        session_gen = get_session()
        session = next(session_gen)
        try:
            assert len(session.query(Document).all()) == 2
            assert len(session.query(DocumentCopy).all()) == 2
            assert len(session.query(Operation).all()) == 2
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

        # Delete file1 outside docman (simulating user deletion)
        file1.unlink()

        # Second run: should clean up file1's copy and pending operation
        # Reset the mock and set up for only file2 to be processed
        mock_hash.reset_mock()
        mock_hash.return_value = "hash2"

        result2 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result2.exit_code == 0
        assert "Cleaned up 1 orphaned file(s)" in result2.output
        assert "Reusing existing copy: file2.pdf" in result2.output

        # Verify cleanup: Document remains, but Copy and Operation for file1 are gone
        session_gen = get_session()
        session = next(session_gen)
        try:
            # Documents remain (canonical documents are not deleted)
            docs = session.query(Document).all()
            assert len(docs) == 2

            # Only file2's copy remains
            copies = session.query(DocumentCopy).all()
            assert len(copies) == 1
            assert copies[0].file_path == "file2.pdf"

            # 2 operations: 1 orphaned (document_copy_id=None) from deleted file1, 1 for file2
            ops = session.query(Operation).all()
            assert len(ops) == 2
            orphaned_ops = [op for op in ops if op.document_copy_id is None]
            active_ops = [op for op in ops if op.document_copy_id is not None]
            assert len(orphaned_ops) == 1
            assert len(active_ops) == 1
            assert active_ops[0].document_copy_id == copies[0].id
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    @patch("docman.cli.extract_content")
    @patch("docman.cli.compute_content_hash")
    def test_plan_regenerates_on_model_change(
        self,
        mock_hash: Mock,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that plan regenerates suggestions when model changes."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create test document
        test_file = repo_dir / "test.pdf"
        test_file.touch()

        # First run with gemini-1.5-flash
        mock_provider_config_flash = ProviderConfig(
            name="test-provider-flash",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )
        mock_provider_instance_flash = Mock()
        mock_provider_instance_flash.generate_suggestions.return_value = {
            "suggested_directory_path": "flash/directory",
            "suggested_filename": "flash_file.pdf",
            "reason": "Flash model reason",
            "confidence": 0.80,
        }

        monkeypatch.setattr("docman.cli.get_active_provider", Mock(return_value=mock_provider_config_flash))
        monkeypatch.setattr("docman.cli.get_llm_provider", Mock(return_value=mock_provider_instance_flash))

        mock_hash.return_value = "hash_test"
        mock_extract.return_value = "Test content"
        monkeypatch.chdir(repo_dir)

        result1 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result1.exit_code == 0
        assert "Processing: test.pdf" in result1.output

        # Verify initial pending operation with flash model
        session_gen = get_session()
        session = next(session_gen)
        try:
            pending_ops = session.query(Operation).all()
            assert len(pending_ops) == 1
            assert pending_ops[0].model_name == "gemini-1.5-flash"
            assert pending_ops[0].suggested_directory_path == "flash/directory"
            assert pending_ops[0].reason == "Flash model reason"
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

        # Change model to gemini-1.5-pro
        mock_provider_config_pro = ProviderConfig(
            name="test-provider-pro",
            provider_type="google",
            model="gemini-1.5-pro",
            is_active=True,
        )
        mock_provider_instance_pro = Mock()
        mock_provider_instance_pro.generate_suggestions.return_value = {
            "suggested_directory_path": "pro/directory",
            "suggested_filename": "pro_file.pdf",
            "reason": "Pro model reason",
            "confidence": 0.90,
        }

        monkeypatch.setattr("docman.cli.get_active_provider", Mock(return_value=mock_provider_config_pro))
        monkeypatch.setattr("docman.cli.get_llm_provider", Mock(return_value=mock_provider_instance_pro))

        # Second run with pro model
        result2 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result2.exit_code == 0
        assert "Reusing existing copy: test.pdf" in result2.output
        assert "Prompt or model changed, regenerating suggestions..." in result2.output
        assert "Generating LLM suggestions..." in result2.output

        # Verify pending operation was regenerated with new model
        session_gen = get_session()
        session = next(session_gen)
        try:
            # Still only one document and copy
            assert len(session.query(Document).all()) == 1
            assert len(session.query(DocumentCopy).all()) == 1

            # But pending operation was updated with new model and suggestions
            pending_ops = session.query(Operation).all()
            assert len(pending_ops) == 1
            assert pending_ops[0].model_name == "gemini-1.5-pro"
            assert pending_ops[0].suggested_directory_path == "pro/directory"
            assert pending_ops[0].reason == "Pro model reason"
            assert pending_ops[0].confidence == 0.90
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    @patch("docman.cli.extract_content")
    @patch("docman.cli.compute_content_hash")
    def test_plan_skips_file_on_llm_failure(
        self,
        mock_hash: Mock,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that plan skips files when LLM API fails and doesn't create pending operations."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create test documents (in alphabetical order: failure.pdf, success.pdf)
        (repo_dir / "failure.pdf").touch()
        (repo_dir / "success.pdf").touch()

        # Mock hash with explicit values (failure.pdf processed first, then success.pdf)
        mock_hash.side_effect = ["hash_failure", "hash_success"]
        mock_extract.return_value = "Test content"

        # Mock LLM provider to fail for failure.pdf
        mock_provider_instance = Mock()

        def generate_side_effect(system_prompt: str, user_prompt: str):
            if "failure.pdf" in user_prompt:
                raise Exception("LLM API error")
            return {
                "suggested_directory_path": "test/directory",
                "suggested_filename": "test_file.pdf",
                "reason": "Test reason",
                "confidence": 0.85,
            }

        mock_provider_instance.generate_suggestions.side_effect = generate_side_effect
        monkeypatch.setattr("docman.cli.get_llm_provider", Mock(return_value=mock_provider_instance))

        # Change to repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output shows LLM failure warning
        assert "Warning: LLM suggestion failed" in result.output
        assert "skipping file" in result.output

        # Verify summary shows skipped count
        assert "New documents processed: 2" in result.output
        assert "Skipped (LLM or content errors): 1" in result.output
        assert "Pending operations created: 1" in result.output  # Only for success.pdf

        # Verify database state
        session_gen = get_session()
        session = next(session_gen)
        try:
            # Both documents should exist
            docs = session.query(Document).all()
            assert len(docs) == 2

            # Both copies should exist
            copies = session.query(DocumentCopy).all()
            assert len(copies) == 2

            # Only one pending operation (for success.pdf)
            pending_ops = session.query(Operation).all()
            assert len(pending_ops) == 1

            # Find which copy has the pending operation
            copy_with_op = session.query(DocumentCopy).filter(
                DocumentCopy.id == pending_ops[0].document_copy_id
            ).first()
            assert copy_with_op.file_path == "success.pdf"
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    @patch("docman.cli.extract_content")
    @patch("docman.cli.compute_content_hash")
    def test_plan_extraction_failure_not_double_counted(
        self,
        mock_hash: Mock,
        mock_extract: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that extraction failures are only in failed_count, not skipped_count."""
        repo_dir = self.setup_isolated_env(tmp_path, monkeypatch)

        # Create test documents (in alphabetical order: failure.pdf, success.pdf)
        (repo_dir / "failure.pdf").touch()
        (repo_dir / "success.pdf").touch()

        # Mock hash with explicit values (failure.pdf processed first, then success.pdf)
        mock_hash.side_effect = ["hash_failure", "hash_success"]

        # Mock extraction with explicit values (failure.pdf fails, success.pdf succeeds)
        mock_extract.side_effect = [None, "Extracted content"]

        # Change to repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output
        assert "Processing: failure.pdf" in result.output
        assert "Content extraction failed" in result.output

        # Verify summary shows failed but NOT skipped
        assert "New documents processed: 1" in result.output
        assert "Failed (hash or extraction errors): 1" in result.output
        # Skipped count should be 0 (extraction failures don't count as skipped)
        assert "Skipped (LLM or content errors): 0" in result.output
        assert "Pending operations created: 1" in result.output  # Only for success.pdf

        # Verify database state
        session_gen = get_session()
        session = next(session_gen)
        try:
            # Both documents should exist (one with null content)
            docs = session.query(Document).all()
            assert len(docs) == 2

            # Both copies should exist
            copies = session.query(DocumentCopy).all()
            assert len(copies) == 2

            # Only one pending operation (for success.pdf)
            pending_ops = session.query(Operation).all()
            assert len(pending_ops) == 1

            # Verify it's for success.pdf
            copy_with_op = session.query(DocumentCopy).filter(
                DocumentCopy.id == pending_ops[0].document_copy_id
            ).first()
            assert copy_with_op.file_path == "success.pdf"
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass
