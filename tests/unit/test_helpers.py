"""Unit tests for helper functions in processor.py and models.py."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from docman.database import ensure_database, get_session
from docman.models import (
    Document,
    DocumentCopy,
    Operation,
    OperationStatus,
    OrganizationStatus,
    compute_content_hash,
    operation_needs_regeneration,
    query_documents_needing_suggestions,
)
from docman.processor import ProcessingResult, process_document_file


@pytest.mark.unit
class TestProcessDocumentFile:
    """Unit tests for process_document_file helper function."""

    @pytest.fixture(autouse=True)
    def _setup_isolated_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Automatically set up isolated environment for all tests in this class."""
        app_config_dir = tmp_path / "app_config"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(app_config_dir))

    def setup_repository(self, path: Path) -> None:
        """Set up a docman repository for testing."""
        docman_dir = path / ".docman"
        docman_dir.mkdir()
        config_file = docman_dir / "config.yaml"
        config_file.touch()

    @patch("docman.processor.extract_content")
    def test_process_new_document(
        self, mock_extract: Mock, tmp_path: Path
    ) -> None:
        """Test processing a new document creates Document and DocumentCopy."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        # Ensure database is initialized
        ensure_database()

        # Create a test file
        test_file = repo_dir / "test.pdf"
        test_file.write_text("test content")

        # Mock extract_content
        mock_extract.return_value = "Extracted content"

        # Process the document
        session_gen = get_session()
        session = next(session_gen)
        try:
            copy, result = process_document_file(
                session=session,
                repo_root=repo_dir,
                file_path=Path("test.pdf"),
                repository_path=str(repo_dir),
            )
            session.commit()

            # Verify result
            assert result == ProcessingResult.NEW_DOCUMENT
            assert copy is not None
            assert copy.file_path == "test.pdf"
            assert copy.document.content == "Extracted content"
            assert copy.stored_content_hash is not None
            assert copy.stored_size == test_file.stat().st_size
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    @patch("docman.processor.extract_content")
    def test_process_duplicate_document(
        self, mock_extract: Mock, tmp_path: Path
    ) -> None:
        """Test processing a duplicate document reuses existing Document."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        # Ensure database is initialized
        ensure_database()

        # Create test files with identical content
        file1 = repo_dir / "file1.pdf"
        file2 = repo_dir / "file2.pdf"
        file1.write_text("same content")
        file2.write_text("same content")

        # Mock extract_content
        mock_extract.return_value = "Extracted content"

        session_gen = get_session()
        session = next(session_gen)
        try:
            # Process first document
            copy1, result1 = process_document_file(
                session=session,
                repo_root=repo_dir,
                file_path=Path("file1.pdf"),
                repository_path=str(repo_dir),
            )
            session.commit()
            assert result1 == ProcessingResult.NEW_DOCUMENT

            # Process second document with same content
            copy2, result2 = process_document_file(
                session=session,
                repo_root=repo_dir,
                file_path=Path("file2.pdf"),
                repository_path=str(repo_dir),
            )
            session.commit()

            # Verify result
            assert result2 == ProcessingResult.DUPLICATE_DOCUMENT
            assert copy2 is not None
            assert copy2.document_id == copy1.document_id  # Same document
            assert copy2.file_path != copy1.file_path  # Different copies
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    @patch("docman.processor.extract_content")
    def test_process_reused_copy(
        self, mock_extract: Mock, tmp_path: Path
    ) -> None:
        """Test processing an unchanged file reuses existing copy."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        # Ensure database is initialized
        ensure_database()

        # Create a test file
        test_file = repo_dir / "test.pdf"
        test_file.write_text("test content")

        # Mock extract_content
        mock_extract.return_value = "Extracted content"

        session_gen = get_session()
        session = next(session_gen)
        try:
            # Process the document first time
            copy1, result1 = process_document_file(
                session=session,
                repo_root=repo_dir,
                file_path=Path("test.pdf"),
                repository_path=str(repo_dir),
            )
            session.commit()
            assert result1 == ProcessingResult.NEW_DOCUMENT

            # Process the same document again (unchanged)
            copy2, result2 = process_document_file(
                session=session,
                repo_root=repo_dir,
                file_path=Path("test.pdf"),
                repository_path=str(repo_dir),
            )
            session.commit()

            # Verify result
            assert result2 == ProcessingResult.REUSED_COPY
            assert copy2.id == copy1.id  # Same copy
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    @patch("docman.processor.extract_content")
    def test_process_content_updated(
        self, mock_extract: Mock, tmp_path: Path
    ) -> None:
        """Test processing a modified file updates the document."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        # Ensure database is initialized
        ensure_database()

        # Create a test file
        test_file = repo_dir / "test.pdf"
        test_file.write_text("original content")

        # Mock extract_content to return different values on subsequent calls
        mock_extract.side_effect = ["Original extracted content", "Modified extracted content"]

        session_gen = get_session()
        session = next(session_gen)
        try:
            # Process the document first time
            copy1, result1 = process_document_file(
                session=session,
                repo_root=repo_dir,
                file_path=Path("test.pdf"),
                repository_path=str(repo_dir),
            )
            session.commit()
            assert result1 == ProcessingResult.NEW_DOCUMENT
            doc_id1 = copy1.document_id

            # Modify the file
            test_file.write_text("modified content")

            # Process the document again
            copy2, result2 = process_document_file(
                session=session,
                repo_root=repo_dir,
                file_path=Path("test.pdf"),
                repository_path=str(repo_dir),
            )
            session.commit()

            # Verify result
            assert result2 == ProcessingResult.CONTENT_UPDATED
            assert copy2.id == copy1.id  # Same copy
            assert copy2.document_id != doc_id1  # Different document

            # Query the new document directly to verify its content
            new_doc = session.query(Document).filter(Document.id == copy2.document_id).first()
            assert new_doc is not None
            assert new_doc.content == "Modified extracted content"
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    @patch("docman.processor.extract_content")
    def test_process_extraction_failed(
        self, mock_extract: Mock, tmp_path: Path
    ) -> None:
        """Test processing a file with extraction failure."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        # Ensure database is initialized
        ensure_database()

        # Create a test file
        test_file = repo_dir / "test.pdf"
        test_file.write_text("test content")

        # Mock extract_content to return None (extraction failed)
        mock_extract.return_value = None

        session_gen = get_session()
        session = next(session_gen)
        try:
            # Process the document
            copy, result = process_document_file(
                session=session,
                repo_root=repo_dir,
                file_path=Path("test.pdf"),
                repository_path=str(repo_dir),
            )
            session.commit()

            # Verify result
            assert result == ProcessingResult.EXTRACTION_FAILED
            assert copy is not None
            assert copy.document.content is None  # No content extracted
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass


@pytest.mark.unit
class TestOperationNeedsRegeneration:
    """Unit tests for operation_needs_regeneration helper function."""

    def test_no_operation_needs_regeneration(self) -> None:
        """Test that missing operation needs regeneration."""
        needs_regen, reason = operation_needs_regeneration(
            operation=None,
            current_prompt_hash="hash1",
            document_content_hash="content_hash1",
            model_name="model1",
        )

        assert needs_regen is True
        assert reason is None

    def test_prompt_hash_changed_needs_regeneration(self) -> None:
        """Test that changed prompt hash needs regeneration."""
        operation = Mock(spec=Operation)
        operation.prompt_hash = "old_hash"
        operation.document_content_hash = "content_hash1"
        operation.model_name = "model1"

        needs_regen, reason = operation_needs_regeneration(
            operation=operation,
            current_prompt_hash="new_hash",
            document_content_hash="content_hash1",
            model_name="model1",
        )

        assert needs_regen is True
        assert reason == "Prompt or model changed"

    def test_content_hash_changed_needs_regeneration(self) -> None:
        """Test that changed content hash needs regeneration."""
        operation = Mock(spec=Operation)
        operation.prompt_hash = "hash1"
        operation.document_content_hash = "old_content"
        operation.model_name = "model1"

        needs_regen, reason = operation_needs_regeneration(
            operation=operation,
            current_prompt_hash="hash1",
            document_content_hash="new_content",
            model_name="model1",
        )

        assert needs_regen is True
        assert reason == "Document content changed"

    def test_model_name_changed_needs_regeneration(self) -> None:
        """Test that changed model name needs regeneration."""
        operation = Mock(spec=Operation)
        operation.prompt_hash = "hash1"
        operation.document_content_hash = "content_hash1"
        operation.model_name = "old_model"

        needs_regen, reason = operation_needs_regeneration(
            operation=operation,
            current_prompt_hash="hash1",
            document_content_hash="content_hash1",
            model_name="new_model",
        )

        assert needs_regen is True
        assert reason == "Model changed"

    def test_no_changes_no_regeneration(self) -> None:
        """Test that unchanged operation doesn't need regeneration."""
        operation = Mock(spec=Operation)
        operation.prompt_hash = "hash1"
        operation.document_content_hash = "content_hash1"
        operation.model_name = "model1"

        needs_regen, reason = operation_needs_regeneration(
            operation=operation,
            current_prompt_hash="hash1",
            document_content_hash="content_hash1",
            model_name="model1",
        )

        assert needs_regen is False
        assert reason is None


@pytest.mark.unit
class TestQueryDocumentsNeedingSuggestions:
    """Unit tests for query_documents_needing_suggestions helper function."""

    @pytest.fixture(autouse=True)
    def _setup_isolated_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Automatically set up isolated environment for all tests in this class."""
        app_config_dir = tmp_path / "app_config"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(app_config_dir))

    def setup_repository(self, path: Path) -> None:
        """Set up a docman repository for testing."""
        docman_dir = path / ".docman"
        docman_dir.mkdir()
        config_file = docman_dir / "config.yaml"
        config_file.touch()

    def test_query_unorganized_documents(self, tmp_path: Path) -> None:
        """Test querying only unorganized documents."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        # Ensure database is initialized
        ensure_database()

        session_gen = get_session()
        session = next(session_gen)
        try:
            # Create documents with different organization statuses
            doc1 = Document(content_hash="hash1", content="Content 1")
            doc2 = Document(content_hash="hash2", content="Content 2")
            doc3 = Document(content_hash="hash3", content="Content 3")
            session.add_all([doc1, doc2, doc3])
            session.flush()

            copy1 = DocumentCopy(
                document_id=doc1.id,
                repository_path=str(repo_dir),
                file_path="unorganized.pdf",
                organization_status=OrganizationStatus.UNORGANIZED,
            )
            copy2 = DocumentCopy(
                document_id=doc2.id,
                repository_path=str(repo_dir),
                file_path="organized.pdf",
                organization_status=OrganizationStatus.ORGANIZED,
            )
            copy3 = DocumentCopy(
                document_id=doc3.id,
                repository_path=str(repo_dir),
                file_path="ignored.pdf",
                organization_status=OrganizationStatus.IGNORED,
            )
            session.add_all([copy1, copy2, copy3])
            session.commit()

            # Query documents needing suggestions (default: reprocess=False)
            results = query_documents_needing_suggestions(
                session=session,
                repo_root=repo_dir,
                path_filter=None,
                reprocess=False,
            )

            # Verify only unorganized document is returned
            assert len(results) == 1
            assert results[0][0].file_path == "unorganized.pdf"
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_query_with_reprocess_flag(self, tmp_path: Path) -> None:
        """Test querying all documents with reprocess=True."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        # Ensure database is initialized
        ensure_database()

        session_gen = get_session()
        session = next(session_gen)
        try:
            # Create documents with different organization statuses
            doc1 = Document(content_hash="hash1", content="Content 1")
            doc2 = Document(content_hash="hash2", content="Content 2")
            session.add_all([doc1, doc2])
            session.flush()

            copy1 = DocumentCopy(
                document_id=doc1.id,
                repository_path=str(repo_dir),
                file_path="unorganized.pdf",
                organization_status=OrganizationStatus.UNORGANIZED,
            )
            copy2 = DocumentCopy(
                document_id=doc2.id,
                repository_path=str(repo_dir),
                file_path="organized.pdf",
                organization_status=OrganizationStatus.ORGANIZED,
            )
            session.add_all([copy1, copy2])
            session.commit()

            # Query with reprocess=True
            results = query_documents_needing_suggestions(
                session=session,
                repo_root=repo_dir,
                path_filter=None,
                reprocess=True,
            )

            # Verify all documents are returned
            assert len(results) == 2
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_query_with_path_filter(self, tmp_path: Path) -> None:
        """Test querying documents with path filter."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        # Ensure database is initialized
        ensure_database()

        session_gen = get_session()
        session = next(session_gen)
        try:
            # Create documents in different paths
            doc1 = Document(content_hash="hash1", content="Content 1")
            doc2 = Document(content_hash="hash2", content="Content 2")
            session.add_all([doc1, doc2])
            session.flush()

            copy1 = DocumentCopy(
                document_id=doc1.id,
                repository_path=str(repo_dir),
                file_path="docs/file1.pdf",
                organization_status=OrganizationStatus.UNORGANIZED,
            )
            copy2 = DocumentCopy(
                document_id=doc2.id,
                repository_path=str(repo_dir),
                file_path="other/file2.pdf",
                organization_status=OrganizationStatus.UNORGANIZED,
            )
            session.add_all([copy1, copy2])
            session.commit()

            # Query with path filter for "docs" directory
            results = query_documents_needing_suggestions(
                session=session,
                repo_root=repo_dir,
                path_filter="docs",
                reprocess=False,
            )

            # Verify only docs directory file is returned
            assert len(results) == 1
            assert results[0][0].file_path == "docs/file1.pdf"
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_query_with_recursive_flag(self, tmp_path: Path) -> None:
        """Test querying documents with recursive flag."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        # Ensure database is initialized
        ensure_database()

        session_gen = get_session()
        session = next(session_gen)
        try:
            # Create documents at different nesting levels
            doc1 = Document(content_hash="hash1", content="Content 1")
            doc2 = Document(content_hash="hash2", content="Content 2")
            doc3 = Document(content_hash="hash3", content="Content 3")
            session.add_all([doc1, doc2, doc3])
            session.flush()

            # Direct child in docs/
            copy1 = DocumentCopy(
                document_id=doc1.id,
                repository_path=str(repo_dir),
                file_path="docs/file1.pdf",
                organization_status=OrganizationStatus.UNORGANIZED,
            )
            # Nested child in docs/nested/
            copy2 = DocumentCopy(
                document_id=doc2.id,
                repository_path=str(repo_dir),
                file_path="docs/nested/file2.pdf",
                organization_status=OrganizationStatus.UNORGANIZED,
            )
            # File in different directory
            copy3 = DocumentCopy(
                document_id=doc3.id,
                repository_path=str(repo_dir),
                file_path="other/file3.pdf",
                organization_status=OrganizationStatus.UNORGANIZED,
            )
            session.add_all([copy1, copy2, copy3])
            session.commit()

            # Query with recursive=True (should include nested files)
            results_recursive = query_documents_needing_suggestions(
                session=session,
                repo_root=repo_dir,
                path_filter="docs",
                reprocess=False,
                recursive=True,
            )

            # Verify both docs/ files are returned (including nested)
            assert len(results_recursive) == 2
            file_paths = {r[0].file_path for r in results_recursive}
            assert "docs/file1.pdf" in file_paths
            assert "docs/nested/file2.pdf" in file_paths

            # Query with recursive=False (should only include direct children)
            results_non_recursive = query_documents_needing_suggestions(
                session=session,
                repo_root=repo_dir,
                path_filter="docs",
                reprocess=False,
                recursive=False,
            )

            # Verify only direct child is returned (not nested)
            assert len(results_non_recursive) == 1
            assert results_non_recursive[0][0].file_path == "docs/file1.pdf"
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass
