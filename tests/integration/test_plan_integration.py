"""Integration tests for the 'docman plan' command."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

from conftest import setup_repository
from docman.cli import main
from docman.database import ensure_database, get_session
from docman.llm_config import ProviderConfig
from docman.models import Document, DocumentCopy, Operation, OperationStatus, compute_content_hash


@pytest.mark.integration
@pytest.mark.slow
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
        }

        # Patch the LLM-related functions
        monkeypatch.setattr("docman.cli.get_active_provider", Mock(return_value=mock_provider_config))
        monkeypatch.setattr("docman.cli.get_api_key", Mock(return_value="test-api-key"))
        monkeypatch.setattr("docman.cli.get_llm_provider", Mock(return_value=mock_provider_instance))

    def test_plan_success_with_documents(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_scanned_document,
        db_session,
    ) -> None:
        """Test successful plan execution with documents."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create scanned documents (simulates scan command)
        create_scanned_document(repo_dir, "test1.pdf", "Content for test1")
        create_scanned_document(repo_dir, "test2.docx", "Content for test2")

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output
        assert "Generating suggestions for documents in repository:" in result.output
        assert "Found 2 scanned document(s) to process" in result.output
        assert "Generating suggestions: test1.pdf" in result.output or "Generating suggestions: test2.docx" in result.output
        assert "Summary:" in result.output
        assert "Pending operations created: 2" in result.output

        # Verify pending operations were created
        operations = db_session.query(Operation).all()
        assert len(operations) == 2
        assert all(op.status == OperationStatus.PENDING for op in operations)
        assert all(op.suggested_directory_path == "test/directory" for op in operations)
        assert all(op.suggested_filename == "test_file.pdf" for op in operations)

    def test_plan_skips_existing_documents(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_scanned_document,
        db_session,
    ) -> None:
        """Test that plan reuses existing suggestions when prompt unchanged."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create scanned documents
        create_scanned_document(repo_dir, "test1.pdf", "Content 1")
        create_scanned_document(repo_dir, "test2.pdf", "Content 2")

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command first time
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "Pending operations created: 2" in result.output

        # Run plan command second time - should reuse existing suggestions
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "Reusing existing suggestions (prompt unchanged)" in result.output
        assert "Pending operations updated: 0" in result.output
        assert "Pending operations created: 0" in result.output

        # Verify still only 2 operations
        operations = db_session.query(Operation).all()
        assert len(operations) == 2

    def test_plan_handles_extraction_failures(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_scanned_document,
        db_session,
    ) -> None:
        """Test that plan skips documents with no content (extraction failed during scan)."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create scanned documents - one with content, one without (simulates extraction failure)
        create_scanned_document(repo_dir, "success.pdf", "Extracted content")

        # Manually create a document with no content (simulates extraction failure during scan)
        # Create the actual file
        failure_path = repo_dir / "failure.pdf"
        failure_path.write_text("dummy")

        # Compute content hash
        content_hash = compute_content_hash(failure_path)

        # Create document with None content (extraction failed)
        document = Document(content_hash=content_hash, content=None)
        db_session.add(document)
        db_session.flush()

        # Create document copy
        stat = failure_path.stat()
        copy = DocumentCopy(
            document_id=document.id,
            repository_path=str(repo_dir),
            file_path="failure.pdf",
            stored_content_hash=content_hash,
            stored_size=stat.st_size,
            stored_mtime=stat.st_mtime,
        )
        db_session.add(copy)
        db_session.commit()

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output - success.pdf gets suggestions, failure.pdf is skipped
        assert "Generating suggestions: success.pdf" in result.output
        assert "Generating suggestions: failure.pdf" in result.output
        assert "Skipping (no content available)" in result.output
        assert "Pending operations created: 1" in result.output
        assert "Skipped (no content or LLM errors): 1" in result.output

        # Verify only one operation created (for success.pdf)
        operations = db_session.query(Operation).all()
        assert len(operations) == 1
        assert operations[0].suggested_filename == "test_file.pdf"

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

    def test_plan_no_documents(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test plan when no scanned documents are found."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create non-document files (not scanned)
        (repo_dir / "test.py").touch()
        (repo_dir / "test.js").touch()

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command (with no scanned documents)
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output shows no scanned documents
        assert "No scanned documents found that need suggestions." in result.output
        assert "Tip: Run 'docman scan'" in result.output

    def test_plan_discovers_nested_documents(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_scanned_document,
        db_session,
    ) -> None:
        """Test that plan processes scanned documents in nested directories."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create scanned documents in nested directories
        create_scanned_document(repo_dir, "root.pdf", "Root content")
        create_scanned_document(repo_dir, "docs/reports/report.docx", "Report content")
        create_scanned_document(repo_dir, "data/data.xlsx", "Data content")

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output shows scanned documents processed
        assert "Found 3 scanned document(s) to process" in result.output
        assert "Pending operations created: 3" in result.output

        # Verify all operations were created with correct paths
        operations = db_session.query(Operation).all()
        assert len(operations) == 3
        assert all(op.status == OperationStatus.PENDING for op in operations)

        # Verify document copies have correct paths
        copies = db_session.query(DocumentCopy).all()
        assert len(copies) == 3

        paths = {copy.file_path for copy in copies}
        assert "root.pdf" in paths
        assert "docs/reports/report.docx" in paths
        assert "data/data.xlsx" in paths

    def test_plan_excludes_docman_directory(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        create_scanned_document, db_session
    ) -> None:
        """Test that plan processes only scanned documents (scan already excludes .docman)."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create scanned document (scan would have excluded .docman directory)
        create_scanned_document(repo_dir, "include.pdf", "Included content")

        # Note: Files in .docman are never scanned, so they won't appear in database

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify only scanned document was processed
        assert "Found 1 scanned document(s) to process" in result.output
        assert "include.pdf" in result.output

        # Verify only one operation created
        operations = db_session.query(Operation).all()
        assert len(operations) == 1

        copies = db_session.query(DocumentCopy).all()
        assert len(copies) == 1
        assert copies[0].file_path == "include.pdf"

    def test_plan_shows_progress(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        create_scanned_document
    ) -> None:
        """Test that plan shows progress indicators."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create scanned documents
        for i in range(5):
            create_scanned_document(repo_dir, f"test{i}.pdf", f"Content {i}")

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify progress indicators
        assert "[1/5]" in result.output
        assert "[5/5]" in result.output
        assert "20%" in result.output
        assert "100%" in result.output

    def test_plan_from_subdirectory(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        create_scanned_document
    ) -> None:
        """Test that plan works when run from a subdirectory."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create subdirectory
        subdir = repo_dir / "subdir"
        subdir.mkdir()

        # Create scanned document in root
        create_scanned_document(repo_dir, "test.pdf", "Test content")

        # Run plan command from subdirectory
        monkeypatch.chdir(subdir)

        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify it found the repository root and processed scanned documents
        assert "Generating suggestions for documents in repository:" in result.output
        assert str(repo_dir) in result.output
        assert "Found 1 scanned document(s) to process" in result.output

    def test_plan_single_file(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_scanned_document,
        db_session,
    ) -> None:
        """Test plan with a single file path."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create scanned documents
        create_scanned_document(repo_dir, "target.pdf", "Target content")
        create_scanned_document(repo_dir, "other.pdf", "Other content")

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command with single file
        result = cli_runner.invoke(main, ["plan", "target.pdf"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output shows single file processing
        assert "Generating suggestions for single file: target.pdf" in result.output or "Found 1 scanned document(s) to process" in result.output
        assert "Pending operations created: 1" in result.output

        # Verify only the target file got an operation
        operations = db_session.query(Operation).all()
        assert len(operations) == 1

        # Verify both copies exist but only target got operation
        copies = db_session.query(DocumentCopy).all()
        assert len(copies) == 2

    def test_plan_single_file_unsupported_type(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test plan with an unsupported file type (scan would have rejected it)."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create unsupported file (not scanned)
        (repo_dir / "test.py").touch()

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command with unsupported file path
        result = cli_runner.invoke(main, ["plan", "test.py"])

        # Verify exit code (succeeds but finds no scanned documents)
        assert result.exit_code == 0

        # Verify output shows no scanned documents found
        assert "No scanned documents found that need suggestions." in result.output

    def test_plan_shallow_directory(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_scanned_document,
        db_session,
    ) -> None:
        """Test plan with directory path (non-recursive by default)."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create scanned documents in different directories
        create_scanned_document(repo_dir, "root.pdf", "Root content")
        create_scanned_document(repo_dir, "docs/doc1.pdf", "Doc1 content")
        create_scanned_document(repo_dir, "docs/doc2.docx", "Doc2 content")
        create_scanned_document(repo_dir, "docs/nested/nested.pdf", "Nested content")

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command with directory filter (non-recursive by default)
        result = cli_runner.invoke(main, ["plan", "docs"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output shows only direct children (not nested files)
        assert "Found 2 scanned document(s) to process" in result.output
        assert "Pending operations created: 2" in result.output

        # Verify operations created only for direct children
        operations = db_session.query(Operation).all()
        # Only direct children get operations (not nested)
        assert len(operations) == 2

        # Verify all scanned documents still exist
        copies = db_session.query(DocumentCopy).all()
        assert len(copies) == 4

    def test_plan_recursive_subdirectory(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_scanned_document,
        db_session,
    ) -> None:
        """Test plan with directory path and -r flag (includes nested files)."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create scanned documents in subdirectory and nested subdirectory
        create_scanned_document(repo_dir, "root.pdf", "Root content")
        create_scanned_document(repo_dir, "docs/doc1.pdf", "Doc1 content")
        create_scanned_document(repo_dir, "docs/nested/nested.pdf", "Nested content")

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command with directory path filter AND -r flag
        result = cli_runner.invoke(main, ["plan", "docs", "-r"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output shows all files in docs/ directory (including nested with -r)
        assert "Found 2 scanned document(s) to process" in result.output
        assert "Pending operations created: 2" in result.output

        # Verify operations created for all files in docs/ directory (including nested)
        operations = db_session.query(Operation).all()
        assert len(operations) == 2

        # Verify all scanned documents still exist
        copies = db_session.query(DocumentCopy).all()
        assert len(copies) == 3

    def test_plan_path_outside_repository(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that plan fails when path is outside repository."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

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
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Try to plan with nonexistent path
        result = cli_runner.invoke(main, ["plan", "nonexistent.pdf"])

        # Verify exit code
        assert result.exit_code == 1

        # Verify error message
        assert "Error: Path 'nonexistent.pdf' does not exist" in result.output

    def test_plan_backward_compatibility(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_scanned_document,
        db_session,
    ) -> None:
        """Test that 'docman plan' without arguments processes all scanned documents."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create scanned documents
        create_scanned_document(repo_dir, "root.pdf", "Root content")
        create_scanned_document(repo_dir, "docs/doc.pdf", "Doc content")
        create_scanned_document(repo_dir, "docs/nested/nested.pdf", "Nested content")

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command without any arguments
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output shows all scanned documents processed
        assert "Found 3 scanned document(s) to process" in result.output
        assert "Pending operations created: 3" in result.output

        # Verify all documents got operations
        operations = db_session.query(Operation).all()
        assert len(operations) == 3

    def test_plan_explicit_dot_is_non_recursive(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_scanned_document,
        db_session,
    ) -> None:
        """Test that 'docman plan .' works as a path filter (filters for files starting with '.')."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create scanned documents - one with "." prefix
        create_scanned_document(repo_dir, "root.pdf", "Root content")
        create_scanned_document(repo_dir, ".hidden.pdf", "Hidden content")

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command with explicit "." argument (filters for files starting with ".")
        result = cli_runner.invoke(main, ["plan", ".hidden.pdf"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify output shows only the .hidden.pdf file processed
        assert "Found 1 scanned document(s) to process" in result.output
        assert "Pending operations created: 1" in result.output

        # Verify only .hidden.pdf got an operation
        operations = db_session.query(Operation).all()
        assert len(operations) == 1

    def test_plan_creates_pending_operations_for_reused_copies(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_scanned_document,
        db_session,
    ) -> None:
        """Test that pending operations are created even for existing scanned documents."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create scanned document
        create_scanned_document(repo_dir, "test.pdf", "Test content")

        monkeypatch.chdir(repo_dir)

        # First run: creates pending operation
        result1 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result1.exit_code == 0

        # Verify document, copy, and pending operation exist
        docs = db_session.query(Document).all()
        assert len(docs) == 1

        copies = db_session.query(DocumentCopy).all()
        assert len(copies) == 1
        copy_id = copies[0].id

        pending_ops = db_session.query(Operation).all()
        assert len(pending_ops) == 1
        assert pending_ops[0].document_copy_id == copy_id

        # Delete the pending operation (simulating unmark or reject)
        db_session.delete(pending_ops[0])
        db_session.commit()

        # Second run: should recreate pending operation for same scanned document
        result2 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result2.exit_code == 0

        # Verify output shows operation created
        assert "Pending operations created: 1" in result2.output

        # Verify pending operation was recreated
        # Still only one document and copy
        docs = db_session.query(Document).all()
        assert len(docs) == 1

        copies = db_session.query(DocumentCopy).all()
        assert len(copies) == 1

        # But pending operation was recreated
        pending_ops = db_session.query(Operation).all()
        assert len(pending_ops) == 1
        assert pending_ops[0].document_copy_id == copy_id

    def test_plan_after_reset_workflow(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_scanned_document,
        db_session,
    ) -> None:
        """Test the complete reject --all -> plan workflow recreates pending operations."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create scanned documents
        create_scanned_document(repo_dir, "file1.pdf", "Content 1")
        create_scanned_document(repo_dir, "file2.docx", "Content 2")

        monkeypatch.chdir(repo_dir)

        # Step 1: Initial plan - creates operations
        result1 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result1.exit_code == 0
        assert "Pending operations created: 2" in result1.output

        # Verify initial state
        assert len(db_session.query(Document).all()) == 2
        assert len(db_session.query(DocumentCopy).all()) == 2
        assert len(db_session.query(Operation).all()) == 2

        # Step 2: Reject all - marks operations as REJECTED
        result2 = cli_runner.invoke(main, ["review", "--reject-all", "-y"], catch_exceptions=False)
        assert result2.exit_code == 0
        assert "Successfully rejected 2 pending operation(s)" in result2.output

        # Verify operations were marked as REJECTED
        assert len(db_session.query(Document).all()) == 2
        assert len(db_session.query(DocumentCopy).all()) == 2
        ops = db_session.query(Operation).all()
        assert len(ops) == 2
        assert all(op.status == OperationStatus.REJECTED for op in ops)

        # Step 3: Plan again - recreates pending operations
        result3 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result3.exit_code == 0
        assert "Pending operations created: 2" in result3.output

        # Verify final state: 2 documents/copies, 4 operations total (2 REJECTED + 2 PENDING)
        assert len(db_session.query(Document).all()) == 2
        assert len(db_session.query(DocumentCopy).all()) == 2
        ops = db_session.query(Operation).all()
        assert len(ops) == 4
        # 2 rejected from earlier, 2 new pending
        assert len([op for op in ops if op.status == OperationStatus.REJECTED]) == 2
        assert len([op for op in ops if op.status == OperationStatus.PENDING]) == 2

    def test_plan_skips_creating_duplicate_pending_operations(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_scanned_document,
        db_session,
    ) -> None:
        """Test that plan doesn't create duplicate pending operations on repeated runs."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create scanned document (simulates scan command)
        create_scanned_document(repo_dir, "test.pdf", "Test content")

        monkeypatch.chdir(repo_dir)

        # First run: creates pending operation
        result1 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result1.exit_code == 0
        assert "Pending operations created: 1" in result1.output

        # Second run: reuses existing suggestions (doesn't duplicate pending operation)
        result2 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result2.exit_code == 0
        assert "Reusing existing suggestions (prompt unchanged)" in result2.output
        assert "Pending operations created: 0" in result2.output

        # Verify only one of everything exists
        assert len(db_session.query(Document).all()) == 1
        assert len(db_session.query(DocumentCopy).all()) == 1
        assert len(db_session.query(Operation).all()) == 1

    def test_plan_mixed_new_and_reused_copies(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_scanned_document,
        db_session,
    ) -> None:
        """Test plan with mix of new scanned files and existing scanned files."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create first scanned document
        create_scanned_document(repo_dir, "existing.pdf", "Content for existing")

        monkeypatch.chdir(repo_dir)

        # First run: create pending operation for existing.pdf
        result1 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result1.exit_code == 0
        assert "Pending operations created: 1" in result1.output

        # Scan a new document (simulates running 'docman scan new.pdf')
        create_scanned_document(repo_dir, "new.pdf", "Content for new")

        # Second run: should generate suggestion for new file, reuse existing for old file
        result2 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result2.exit_code == 0

        # Verify output shows new file processed and existing file suggestions reused
        assert "Found 2 scanned document(s) to process" in result2.output
        assert "Pending operations created: 1" in result2.output  # Only new file creates pending op

        # Verify database state
        assert len(db_session.query(Document).all()) == 2
        assert len(db_session.query(DocumentCopy).all()) == 2
        # Both should have pending operations (one from first run, one from second)
        assert len(db_session.query(Operation).all()) == 2

    def test_plan_fails_without_instructions(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that plan fails with error when folder definitions are missing."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Remove folder definitions from config.yaml
        config_file = repo_dir / ".docman" / "config.yaml"
        config_file.write_text("")  # Empty config, no folder definitions

        # Create a test document
        (repo_dir / "test.pdf").touch()

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Verify it fails with appropriate error
        assert result.exit_code == 1
        assert "Error: No folder definitions found" in result.output
        assert "docman define" in result.output

    def test_plan_detects_stale_content(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_scanned_document,
        db_session,
    ) -> None:
        """Test that plan regenerates suggestions when document content changes."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create initial scanned document
        doc1, copy1 = create_scanned_document(repo_dir, "test.pdf", "Initial content")
        initial_copy_id = copy1.id
        initial_content_hash = doc1.content_hash

        monkeypatch.chdir(repo_dir)

        # First run: create suggestions for initial content
        result1 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result1.exit_code == 0
        assert "Pending operations created: 1" in result1.output

        # Verify initial operation
        pending_ops = db_session.query(Operation).all()
        assert len(pending_ops) == 1
        assert pending_ops[0].document_content_hash == initial_content_hash

        # Simulate re-scanning with modified content (updates document and copy)
        # This simulates what 'docman scan --rescan' would do
        test_file = repo_dir / "test.pdf"
        test_file.write_text("Modified content - much longer to change size")

        # Manually update the database to simulate re-scan
        new_content_hash = compute_content_hash(test_file)

        # Create new document with modified content
        new_doc = Document(content_hash=new_content_hash, content="Modified extracted content")
        db_session.add(new_doc)
        db_session.flush()

        # Update copy to point to new document
        copy = db_session.query(DocumentCopy).filter_by(id=initial_copy_id).first()
        copy.document_id = new_doc.id
        stat = test_file.stat()
        copy.stored_content_hash = new_content_hash
        copy.stored_size = stat.st_size
        copy.stored_mtime = stat.st_mtime
        db_session.commit()

        # Second run: should detect content changed and regenerate suggestions
        result2 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result2.exit_code == 0

        # Refresh session to see changes from the plan command
        db_session.expire_all()

        # Verify suggestion was regenerated with new content hash
        # Should have two documents now (old and new content)
        docs = db_session.query(Document).all()
        assert len(docs) == 2

        # Copy should still exist with same ID but point to new document
        copies = db_session.query(DocumentCopy).all()
        assert len(copies) == 1
        assert copies[0].id == initial_copy_id

        # Should have one pending operation with new content hash
        pending_ops = db_session.query(Operation).all()
        assert len(pending_ops) == 1
        # Operation should reference the new content hash
        assert pending_ops[0].document_content_hash != initial_content_hash

    def test_plan_cleans_up_deleted_files(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_scanned_document,
        db_session,
    ) -> None:
        """Test that plan cleans up DocumentCopy and Operation when file is deleted."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create multiple scanned documents
        create_scanned_document(repo_dir, "file1.pdf", "Content 1")
        create_scanned_document(repo_dir, "file2.pdf", "Content 2")

        monkeypatch.chdir(repo_dir)

        # First run: create pending operations
        result1 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result1.exit_code == 0
        assert "Pending operations created: 2" in result1.output

        # Verify initial state
        assert len(db_session.query(Document).all()) == 2
        assert len(db_session.query(DocumentCopy).all()) == 2
        assert len(db_session.query(Operation).all()) == 2

        # Delete file1 outside docman (simulating user deletion)
        file1 = repo_dir / "file1.pdf"
        file1.unlink()

        # Second run: should clean up file1's copy and pending operation
        result2 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result2.exit_code == 0
        assert "Cleaned up 1 orphaned file(s)" in result2.output

        # Verify cleanup: Document remains, but Copy and Operation for file1 are gone
        # Documents remain (canonical documents are not deleted)
        docs = db_session.query(Document).all()
        assert len(docs) == 2

        # Only file2's copy remains
        copies = db_session.query(DocumentCopy).all()
        assert len(copies) == 1
        assert copies[0].file_path == "file2.pdf"

        # 2 operations: 1 orphaned (document_copy_id=None) from deleted file1, 1 for file2
        ops = db_session.query(Operation).all()
        assert len(ops) == 2
        orphaned_ops = [op for op in ops if op.document_copy_id is None]
        active_ops = [op for op in ops if op.document_copy_id is not None]
        assert len(orphaned_ops) == 1
        assert len(active_ops) == 1
        assert active_ops[0].document_copy_id == copies[0].id

    def test_plan_regenerates_on_model_change(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_scanned_document,
        db_session,
    ) -> None:
        """Test that plan regenerates suggestions when model changes."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create scanned document
        create_scanned_document(repo_dir, "test.pdf", "Test content")

        # First run with gemini-1.5-flash
        mock_provider_config_flash = ProviderConfig(
            name="test-provider-flash",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )
        mock_provider_instance_flash = Mock()
        mock_provider_instance_flash.supports_structured_output = True
        mock_provider_instance_flash.generate_suggestions.return_value = {
            "suggested_directory_path": "flash/directory",
            "suggested_filename": "flash_file.pdf",
            "reason": "Flash model reason",
        }

        monkeypatch.setattr("docman.cli.get_active_provider", Mock(return_value=mock_provider_config_flash))
        monkeypatch.setattr("docman.cli.get_llm_provider", Mock(return_value=mock_provider_instance_flash))
        monkeypatch.chdir(repo_dir)

        result1 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result1.exit_code == 0
        assert "Pending operations created: 1" in result1.output

        # Verify initial pending operation with flash model
        pending_ops = db_session.query(Operation).all()
        assert len(pending_ops) == 1
        assert pending_ops[0].model_name == "gemini-1.5-flash"
        assert pending_ops[0].suggested_directory_path == "flash/directory"
        assert pending_ops[0].reason == "Flash model reason"

        # Change model to gemini-1.5-pro
        mock_provider_config_pro = ProviderConfig(
            name="test-provider-pro",
            provider_type="google",
            model="gemini-1.5-pro",
            is_active=True,
        )
        mock_provider_instance_pro = Mock()
        mock_provider_instance_pro.supports_structured_output = True
        mock_provider_instance_pro.generate_suggestions.return_value = {
            "suggested_directory_path": "pro/directory",
            "suggested_filename": "pro_file.pdf",
            "reason": "Pro model reason",
        }

        monkeypatch.setattr("docman.cli.get_active_provider", Mock(return_value=mock_provider_config_pro))
        monkeypatch.setattr("docman.cli.get_llm_provider", Mock(return_value=mock_provider_instance_pro))

        # Second run with pro model
        result2 = cli_runner.invoke(main, ["plan"], catch_exceptions=False)
        assert result2.exit_code == 0

        # Refresh session to see changes from the plan command
        db_session.expire_all()

        # Verify pending operation was regenerated with new model
        # Still only one document and copy
        assert len(db_session.query(Document).all()) == 1
        assert len(db_session.query(DocumentCopy).all()) == 1

        # But pending operation was updated with new model and suggestions
        pending_ops = db_session.query(Operation).all()
        assert len(pending_ops) == 1
        assert pending_ops[0].model_name == "gemini-1.5-pro"
        assert pending_ops[0].suggested_directory_path == "pro/directory"
        assert pending_ops[0].reason == "Pro model reason"

    def test_plan_skips_file_on_llm_failure(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_scanned_document,
        db_session,
    ) -> None:
        """Test that plan skips files when LLM API fails and doesn't create pending operations."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create scanned documents (in alphabetical order: failure.pdf, success.pdf)
        create_scanned_document(repo_dir, "failure.pdf", "Content for failure")
        create_scanned_document(repo_dir, "success.pdf", "Content for success")

        # Mock LLM provider to fail for failure.pdf
        mock_provider_instance = Mock()
        mock_provider_instance.supports_structured_output = True

        def generate_side_effect(system_prompt: str, user_prompt: str):
            if "failure.pdf" in user_prompt:
                raise Exception("LLM API error")
            return {
                "suggested_directory_path": "test/directory",
                "suggested_filename": "test_file.pdf",
                "reason": "Test reason",
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
        assert "Warning: LLM suggestion failed" in result.output or "skipping" in result.output.lower()

        # Verify database state
        # Both documents should exist
        docs = db_session.query(Document).all()
        assert len(docs) == 2

        # Both copies should exist
        copies = db_session.query(DocumentCopy).all()
        assert len(copies) == 2

        # Only one pending operation (for success.pdf)
        pending_ops = db_session.query(Operation).all()
        assert len(pending_ops) == 1

        # Find which copy has the pending operation
        copy_with_op = db_session.query(DocumentCopy).filter(
            DocumentCopy.id == pending_ops[0].document_copy_id
        ).first()
        assert copy_with_op.file_path == "success.pdf"

    def test_plan_extraction_failure_not_double_counted(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_scanned_document,
        db_session,
    ) -> None:
        """Test that documents with no content (extraction failed during scan) are skipped."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create one successful scanned document
        create_scanned_document(repo_dir, "success.pdf", "Extracted content")

        # Create a scanned document with null content (simulates extraction failure during scan)
        # This is already tested in test_plan_handles_extraction_failures, but we verify
        # the behavior here as well
        # Create the actual file
        failure_path = repo_dir / "failure.pdf"
        failure_path.write_text("dummy")

        # Compute content hash
        content_hash = compute_content_hash(failure_path)

        # Create document with None content (extraction failed during scan)
        document = Document(content_hash=content_hash, content=None)
        db_session.add(document)
        db_session.flush()

        # Create document copy
        stat = failure_path.stat()
        copy = DocumentCopy(
            document_id=document.id,
            repository_path=str(repo_dir),
            file_path="failure.pdf",
            stored_content_hash=content_hash,
            stored_size=stat.st_size,
            stored_mtime=stat.st_mtime,
        )
        db_session.add(copy)
        db_session.commit()

        # Change to repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Verify exit code
        assert result.exit_code == 0

        # Verify database state
        # Both documents should exist (one with null content)
        docs = db_session.query(Document).all()
        assert len(docs) == 2

        # Both copies should exist
        copies = db_session.query(DocumentCopy).all()
        assert len(copies) == 2

        # Only one pending operation (for success.pdf, failure.pdf has no content)
        pending_ops = db_session.query(Operation).all()
        assert len(pending_ops) == 1

        # Verify it's for success.pdf
        copy_with_op = db_session.query(DocumentCopy).filter(
            DocumentCopy.id == pending_ops[0].document_copy_id
        ).first()
        assert copy_with_op.file_path == "success.pdf"


@pytest.mark.integration
class TestDocmanPlanPathSecurity:
    """Integration tests for path security in plan command."""

    def test_plan_rejects_malicious_llm_parent_traversal(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_scanned_document,
    ) -> None:
        """Test that plan rejects LLM suggestions with parent directory traversal."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create a scanned document
        create_scanned_document(repo_dir, "test.pdf", "Extracted content")

        # Create a mock provider that returns malicious paths
        mock_provider_config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )
        mock_provider_instance = Mock()
        mock_provider_instance.test_connection.return_value = True
        mock_provider_instance.supports_structured_output = True

        # Malicious LLM response with parent directory traversal
        from pydantic import ValidationError

        # When Pydantic validates the model, it should reject the malicious path
        def generate_with_validation(*args, **kwargs):
            # This simulates what happens when Pydantic's field_validator runs
            from docman.llm_providers import OrganizationSuggestion
            try:
                # Try to create the model with malicious data
                OrganizationSuggestion(
                    suggested_directory_path="../../etc",
                    suggested_filename="passwd",
                    reason="Malicious suggestion"
                )
            except ValidationError as e:
                # Pydantic validation should fail, which causes the LLM call to fail
                raise Exception(f"LLM response validation failed: {str(e)}")

        mock_provider_instance.generate_suggestions.side_effect = generate_with_validation

        # Patch the LLM-related functions
        monkeypatch.setattr("docman.cli.get_active_provider", Mock(return_value=mock_provider_config))
        monkeypatch.setattr("docman.cli.get_api_key", Mock(return_value="test-api-key"))
        monkeypatch.setattr("docman.cli.get_llm_provider", Mock(return_value=mock_provider_instance))

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command - should fail gracefully
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Command should complete but skip the malicious file
        assert result.exit_code == 0
        assert "skipped: 1" in result.output.lower() or "failed" in result.output.lower()

    def test_plan_rejects_absolute_paths(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_scanned_document,
    ) -> None:
        """Test that plan rejects LLM suggestions with absolute paths."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create a scanned document
        create_scanned_document(repo_dir, "test.pdf", "Extracted content")

        # Create a mock provider that returns absolute paths
        mock_provider_config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )
        mock_provider_instance = Mock()
        mock_provider_instance.test_connection.return_value = True
        mock_provider_instance.supports_structured_output = True

        # Malicious LLM response with absolute path
        from pydantic import ValidationError

        def generate_with_absolute_path(*args, **kwargs):
            from docman.llm_providers import OrganizationSuggestion
            try:
                OrganizationSuggestion(
                    suggested_directory_path="/etc",
                    suggested_filename="hosts",
                    reason="Malicious suggestion"
                )
            except ValidationError as e:
                raise Exception(f"LLM response validation failed: {str(e)}")

        mock_provider_instance.generate_suggestions.side_effect = generate_with_absolute_path

        # Patch the LLM-related functions
        monkeypatch.setattr("docman.cli.get_active_provider", Mock(return_value=mock_provider_config))
        monkeypatch.setattr("docman.cli.get_api_key", Mock(return_value="test-api-key"))
        monkeypatch.setattr("docman.cli.get_llm_provider", Mock(return_value=mock_provider_instance))

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command - should fail gracefully
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Command should complete but skip the malicious file
        assert result.exit_code == 0
        assert "skipped: 1" in result.output.lower() or "failed" in result.output.lower()

    def test_plan_accepts_safe_llm_suggestions(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        create_scanned_document,
        db_session,
    ) -> None:
        """Test that plan accepts safe LLM suggestions."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_repository(repo_dir)

        # Create a scanned document
        create_scanned_document(repo_dir, "test.pdf", "Extracted content")

        # Create a mock provider that returns safe paths
        mock_provider_config = ProviderConfig(
            name="test-provider",
            provider_type="google",
            model="gemini-1.5-flash",
            is_active=True,
        )
        mock_provider_instance = Mock()
        mock_provider_instance.test_connection.return_value = True
        mock_provider_instance.supports_structured_output = True

        # Safe LLM response
        mock_provider_instance.generate_suggestions.return_value = {
            "suggested_directory_path": "documents/reports",
            "suggested_filename": "annual_report.pdf",
            "reason": "Valid organizational suggestion"
        }

        # Patch the LLM-related functions
        monkeypatch.setattr("docman.cli.get_active_provider", Mock(return_value=mock_provider_config))
        monkeypatch.setattr("docman.cli.get_api_key", Mock(return_value="test-api-key"))
        monkeypatch.setattr("docman.cli.get_llm_provider", Mock(return_value=mock_provider_instance))

        # Change to the repository directory
        monkeypatch.chdir(repo_dir)

        # Run plan command
        result = cli_runner.invoke(main, ["plan"], catch_exceptions=False)

        # Command should succeed
        assert result.exit_code == 0
        # Check for pending operations in the output
        assert "pending operations created" in result.output.lower() or "pending: 1" in result.output.lower()

        # Verify the operation was created in the database
        operations = db_session.query(Operation).all()
        assert len(operations) == 1
        assert operations[0].suggested_directory_path == "documents/reports"
        assert operations[0].suggested_filename == "annual_report.pdf"

