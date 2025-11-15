"""Integration tests for ignore command."""

from pathlib import Path
from click.testing import CliRunner
import pytest

from docman.cli import main
from docman.database import get_session
from docman.models import DocumentCopy, OrganizationStatus


class TestIgnoreCommand:
    """Integration tests for docman ignore command."""

    def setup_repository(self, path: Path) -> None:
        """Set up a docman repository for testing."""
        docman_dir = path / ".docman"
        docman_dir.mkdir()
        config_file = docman_dir / "config.yaml"
        config_file.touch()

    def create_document_copy(self, repo_root: Path, file_path: str) -> None:
        """Create a document copy in the database."""
        from docman.models import Document

        session_gen = get_session()
        session = next(session_gen)
        try:
            # Create document
            doc = Document(content_hash="test_hash_" + file_path, content="Test content")
            session.add(doc)
            session.flush()

            # Create copy
            copy = DocumentCopy(
                document_id=doc.id,
                repository_path=str(repo_root),
                file_path=file_path,
                stored_content_hash="test_hash_" + file_path,
                stored_size=100,
                stored_mtime=1234567890,
                organization_status=OrganizationStatus.UNORGANIZED,
            )
            session.add(copy)
            session.commit()
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_ignore_single_file(self, tmp_path, cli_runner):
        """Test ignoring a single file."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        # Create a test file and document copy
        test_file = repo_dir / "test.pdf"
        test_file.touch()
        self.create_document_copy(repo_dir, "test.pdf")

        result = cli_runner.invoke(
            main, ["ignore", "test.pdf", "-y"], cwd=str(repo_dir)
        )

        assert result.exit_code == 0
        assert "ignored" in result.output.lower()

    def test_ignore_directory_non_recursive(self, tmp_path, cli_runner):
        """Test ignoring files in a directory (non-recursive)."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        # Create test files
        docs_dir = repo_dir / "docs"
        docs_dir.mkdir()
        (docs_dir / "file1.pdf").touch()
        (docs_dir / "file2.pdf").touch()

        self.create_document_copy(repo_dir, "docs/file1.pdf")
        self.create_document_copy(repo_dir, "docs/file2.pdf")

        result = cli_runner.invoke(main, ["ignore", "docs/", "-y"], cwd=str(repo_dir))

        assert result.exit_code == 0

    def test_ignore_directory_recursive(self, tmp_path, cli_runner):
        """Test ignoring files in a directory recursively."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        # Create nested structure
        docs_dir = repo_dir / "docs"
        docs_dir.mkdir()
        subdir = docs_dir / "subdir"
        subdir.mkdir()
        (docs_dir / "file1.pdf").touch()
        (subdir / "file2.pdf").touch()

        self.create_document_copy(repo_dir, "docs/file1.pdf")
        self.create_document_copy(repo_dir, "docs/subdir/file2.pdf")

        result = cli_runner.invoke(
            main, ["ignore", "docs/", "-r", "-y"], cwd=str(repo_dir)
        )

        assert result.exit_code == 0

    def test_ignore_requires_path_argument(self, tmp_path, cli_runner):
        """Test that ignore command requires a path argument."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        result = cli_runner.invoke(main, ["ignore"], cwd=str(repo_dir))

        assert result.exit_code != 0
        assert "must specify a path" in result.output.lower()

    def test_ignore_outside_repository_fails(self, tmp_path, cli_runner):
        """Test that ignore command fails outside a repository."""
        non_repo_dir = tmp_path / "non_repo"
        non_repo_dir.mkdir()

        result = cli_runner.invoke(
            main, ["ignore", "test.pdf"], cwd=str(non_repo_dir)
        )

        assert result.exit_code != 0
        assert "not in a docman repository" in result.output.lower()

    def test_ignore_verifies_status_change(self, tmp_path, cli_runner):
        """Test that ignore command actually changes organization status."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        test_file = repo_dir / "test.pdf"
        test_file.touch()
        self.create_document_copy(repo_dir, "test.pdf")

        cli_runner.invoke(main, ["ignore", "test.pdf", "-y"], cwd=str(repo_dir))

        # Verify status changed in database
        session_gen = get_session()
        session = next(session_gen)
        try:
            copy = session.query(DocumentCopy).filter_by(file_path="test.pdf").first()
            assert copy is not None
            assert copy.organization_status == OrganizationStatus.IGNORED
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass


@pytest.fixture
def cli_runner():
    """Provide a CLI runner for testing."""
    return CliRunner()
