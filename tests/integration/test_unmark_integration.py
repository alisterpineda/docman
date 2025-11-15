"""Integration tests for unmark command."""

from pathlib import Path
from click.testing import CliRunner
import pytest

from docman.cli import main
from docman.database import get_session
from docman.models import DocumentCopy, OrganizationStatus


class TestUnmarkCommand:
    """Integration tests for docman unmark command."""

    def setup_repository(self, path: Path) -> None:
        """Set up a docman repository for testing."""
        docman_dir = path / ".docman"
        docman_dir.mkdir()
        config_file = docman_dir / "config.yaml"
        config_file.touch()

    def create_document_copy(
        self, repo_root: Path, file_path: str, status: OrganizationStatus
    ) -> None:
        """Create a document copy in the database with specified status."""
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
                organization_status=status,
            )
            session.add(copy)
            session.commit()
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass

    def test_unmark_single_file(self, tmp_path, cli_runner):
        """Test unmarking a single file."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        test_file = repo_dir / "test.pdf"
        test_file.touch()
        self.create_document_copy(repo_dir, "test.pdf", OrganizationStatus.ORGANIZED)

        result = cli_runner.invoke(
            main, ["unmark", "test.pdf", "-y"], cwd=str(repo_dir)
        )

        assert result.exit_code == 0
        assert "unmarked" in result.output.lower() or "unorganized" in result.output.lower()

    def test_unmark_all_files(self, tmp_path, cli_runner):
        """Test unmarking all files in repository."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        # Create multiple files with different statuses
        (repo_dir / "file1.pdf").touch()
        (repo_dir / "file2.pdf").touch()
        self.create_document_copy(repo_dir, "file1.pdf", OrganizationStatus.ORGANIZED)
        self.create_document_copy(repo_dir, "file2.pdf", OrganizationStatus.IGNORED)

        result = cli_runner.invoke(main, ["unmark", "--all", "-y"], cwd=str(repo_dir))

        assert result.exit_code == 0

    def test_unmark_directory_non_recursive(self, tmp_path, cli_runner):
        """Test unmarking files in a directory (non-recursive)."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        docs_dir = repo_dir / "docs"
        docs_dir.mkdir()
        (docs_dir / "file1.pdf").touch()
        self.create_document_copy(repo_dir, "docs/file1.pdf", OrganizationStatus.ORGANIZED)

        result = cli_runner.invoke(main, ["unmark", "docs/", "-y"], cwd=str(repo_dir))

        assert result.exit_code == 0

    def test_unmark_directory_recursive(self, tmp_path, cli_runner):
        """Test unmarking files in a directory recursively."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        docs_dir = repo_dir / "docs"
        docs_dir.mkdir()
        subdir = docs_dir / "subdir"
        subdir.mkdir()
        (docs_dir / "file1.pdf").touch()
        (subdir / "file2.pdf").touch()

        self.create_document_copy(repo_dir, "docs/file1.pdf", OrganizationStatus.ORGANIZED)
        self.create_document_copy(repo_dir, "docs/subdir/file2.pdf", OrganizationStatus.IGNORED)

        result = cli_runner.invoke(
            main, ["unmark", "docs/", "-r", "-y"], cwd=str(repo_dir)
        )

        assert result.exit_code == 0

    def test_unmark_requires_path_or_all_flag(self, tmp_path, cli_runner):
        """Test that unmark command requires either --all or a path."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        result = cli_runner.invoke(main, ["unmark"], cwd=str(repo_dir))

        assert result.exit_code != 0
        assert "must specify either --all or a path" in result.output.lower()

    def test_unmark_outside_repository_fails(self, tmp_path, cli_runner):
        """Test that unmark command fails outside a repository."""
        non_repo_dir = tmp_path / "non_repo"
        non_repo_dir.mkdir()

        result = cli_runner.invoke(
            main, ["unmark", "--all", "-y"], cwd=str(non_repo_dir)
        )

        assert result.exit_code != 0
        assert "not in a docman repository" in result.output.lower()

    def test_unmark_verifies_status_change(self, tmp_path, cli_runner):
        """Test that unmark command actually changes organization status."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        self.setup_repository(repo_dir)

        test_file = repo_dir / "test.pdf"
        test_file.touch()
        self.create_document_copy(repo_dir, "test.pdf", OrganizationStatus.ORGANIZED)

        cli_runner.invoke(main, ["unmark", "test.pdf", "-y"], cwd=str(repo_dir))

        # Verify status changed in database
        session_gen = get_session()
        session = next(session_gen)
        try:
            copy = session.query(DocumentCopy).filter_by(file_path="test.pdf").first()
            assert copy is not None
            assert copy.organization_status == OrganizationStatus.UNORGANIZED
        finally:
            try:
                next(session_gen)
            except StopIteration:
                pass


@pytest.fixture
def cli_runner():
    """Provide a CLI runner for testing."""
    return CliRunner()
