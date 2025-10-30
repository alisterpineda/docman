"""Unit tests for the repository module."""

from pathlib import Path

import pytest

from docman.repository import (
    EXCLUDED_DIRS,
    SUPPORTED_EXTENSIONS,
    RepositoryError,
    discover_document_files,
    find_repository_root,
    get_repository_root,
    validate_repository,
)


class TestFindRepositoryRoot:
    """Tests for find_repository_root function."""

    def test_finds_repository_in_current_dir(self, tmp_path: Path) -> None:
        """Test finding .docman in the current directory."""
        docman_dir = tmp_path / ".docman"
        docman_dir.mkdir()

        result = find_repository_root(tmp_path)
        assert result == tmp_path

    def test_finds_repository_in_parent_dir(self, tmp_path: Path) -> None:
        """Test finding .docman in a parent directory."""
        docman_dir = tmp_path / ".docman"
        docman_dir.mkdir()

        subdir = tmp_path / "subdir" / "nested"
        subdir.mkdir(parents=True)

        result = find_repository_root(subdir)
        assert result == tmp_path

    def test_returns_none_when_not_found(self, tmp_path: Path) -> None:
        """Test that None is returned when .docman is not found."""
        result = find_repository_root(tmp_path)
        assert result is None

    def test_uses_cwd_when_start_path_is_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that current directory is used when start_path is None."""
        docman_dir = tmp_path / ".docman"
        docman_dir.mkdir()

        monkeypatch.chdir(tmp_path)
        result = find_repository_root(None)
        assert result == tmp_path

    def test_ignores_docman_file(self, tmp_path: Path) -> None:
        """Test that .docman as a file (not directory) is ignored."""
        docman_file = tmp_path / ".docman"
        docman_file.touch()

        result = find_repository_root(tmp_path)
        assert result is None


class TestValidateRepository:
    """Tests for validate_repository function."""

    def test_valid_repository(self, tmp_path: Path) -> None:
        """Test that a valid repository passes validation."""
        docman_dir = tmp_path / ".docman"
        docman_dir.mkdir()
        config_file = docman_dir / "config.yaml"
        config_file.touch()

        result = validate_repository(tmp_path)
        assert result is True

    def test_invalid_when_docman_dir_missing(self, tmp_path: Path) -> None:
        """Test that validation fails when .docman directory is missing."""
        result = validate_repository(tmp_path)
        assert result is False

    def test_invalid_when_config_missing(self, tmp_path: Path) -> None:
        """Test that validation fails when config.yaml is missing."""
        docman_dir = tmp_path / ".docman"
        docman_dir.mkdir()

        result = validate_repository(tmp_path)
        assert result is False

    def test_invalid_when_docman_is_file(self, tmp_path: Path) -> None:
        """Test that validation fails when .docman is a file instead of directory."""
        docman_file = tmp_path / ".docman"
        docman_file.touch()

        result = validate_repository(tmp_path)
        assert result is False


class TestGetRepositoryRoot:
    """Tests for get_repository_root function."""

    def test_returns_repository_root(self, tmp_path: Path) -> None:
        """Test that repository root is returned for valid repository."""
        docman_dir = tmp_path / ".docman"
        docman_dir.mkdir()
        config_file = docman_dir / "config.yaml"
        config_file.touch()

        result = get_repository_root(tmp_path)
        assert result == tmp_path

    def test_raises_error_when_not_in_repository(self, tmp_path: Path) -> None:
        """Test that RepositoryError is raised when not in a repository."""
        with pytest.raises(RepositoryError, match="Not in a docman repository"):
            get_repository_root(tmp_path)

    def test_raises_error_when_repository_invalid(self, tmp_path: Path) -> None:
        """Test that RepositoryError is raised when repository is invalid."""
        docman_dir = tmp_path / ".docman"
        docman_dir.mkdir()
        # No config.yaml

        with pytest.raises(RepositoryError, match="Invalid docman repository"):
            get_repository_root(tmp_path)


class TestDiscoverDocumentFiles:
    """Tests for discover_document_files function."""

    def test_discovers_supported_document_types(self, tmp_path: Path) -> None:
        """Test that all supported document types are discovered."""
        # Create test files with supported extensions
        (tmp_path / "test.pdf").touch()
        (tmp_path / "test.docx").touch()
        (tmp_path / "test.txt").touch()

        result = discover_document_files(tmp_path)

        assert len(result) == 3
        assert Path("test.pdf") in result
        assert Path("test.docx") in result
        assert Path("test.txt") in result

    def test_excludes_unsupported_file_types(self, tmp_path: Path) -> None:
        """Test that unsupported file types are excluded."""
        (tmp_path / "test.pdf").touch()
        (tmp_path / "test.py").touch()
        (tmp_path / "test.js").touch()

        result = discover_document_files(tmp_path)

        assert len(result) == 1
        assert Path("test.pdf") in result

    def test_discovers_files_in_subdirectories(self, tmp_path: Path) -> None:
        """Test that files in subdirectories are discovered."""
        subdir = tmp_path / "docs" / "reports"
        subdir.mkdir(parents=True)

        (tmp_path / "test.pdf").touch()
        (subdir / "report.docx").touch()

        result = discover_document_files(tmp_path)

        assert len(result) == 2
        assert Path("test.pdf") in result
        assert Path("docs/reports/report.docx") in result

    def test_excludes_excluded_directories(self, tmp_path: Path) -> None:
        """Test that files in excluded directories are not discovered."""
        # Create excluded directories
        for excluded_dir in [".docman", ".git", "node_modules"]:
            dir_path = tmp_path / excluded_dir
            dir_path.mkdir()
            (dir_path / "test.pdf").touch()

        # Create a file in a non-excluded directory
        (tmp_path / "test.pdf").touch()

        result = discover_document_files(tmp_path)

        assert len(result) == 1
        assert Path("test.pdf") in result

    def test_returns_empty_list_when_no_documents(self, tmp_path: Path) -> None:
        """Test that empty list is returned when no documents found."""
        (tmp_path / "test.py").touch()

        result = discover_document_files(tmp_path)

        assert result == []

    def test_returns_sorted_list(self, tmp_path: Path) -> None:
        """Test that files are returned in sorted order."""
        (tmp_path / "z.pdf").touch()
        (tmp_path / "a.pdf").touch()
        (tmp_path / "m.pdf").touch()

        result = discover_document_files(tmp_path)

        assert result == [Path("a.pdf"), Path("m.pdf"), Path("z.pdf")]

    def test_handles_permission_errors_gracefully(self, tmp_path: Path) -> None:
        """Test that permission errors are handled gracefully."""
        # Create a subdirectory with a file
        subdir = tmp_path / "restricted"
        subdir.mkdir()
        (subdir / "test.pdf").touch()

        # Create a file in the main directory
        (tmp_path / "accessible.pdf").touch()

        # Make subdirectory unreadable
        subdir.chmod(0o000)

        try:
            result = discover_document_files(tmp_path)

            # Should still find the accessible file
            assert Path("accessible.pdf") in result
            # Should not crash due to permission error
        finally:
            # Restore permissions for cleanup
            subdir.chmod(0o755)

    def test_case_insensitive_extension_matching(self, tmp_path: Path) -> None:
        """Test that file extensions are matched case-insensitively."""
        (tmp_path / "test.PDF").touch()
        (tmp_path / "test.Docx").touch()
        (tmp_path / "test.TXT").touch()

        result = discover_document_files(tmp_path)

        assert len(result) == 3


class TestSupportedExtensions:
    """Tests for SUPPORTED_EXTENSIONS constant."""

    def test_includes_common_document_types(self) -> None:
        """Test that common document types are supported."""
        assert ".pdf" in SUPPORTED_EXTENSIONS
        assert ".docx" in SUPPORTED_EXTENSIONS
        assert ".doc" in SUPPORTED_EXTENSIONS
        assert ".pptx" in SUPPORTED_EXTENSIONS
        assert ".xlsx" in SUPPORTED_EXTENSIONS

    def test_includes_image_types(self) -> None:
        """Test that image types are supported."""
        assert ".png" in SUPPORTED_EXTENSIONS
        assert ".jpg" in SUPPORTED_EXTENSIONS
        assert ".jpeg" in SUPPORTED_EXTENSIONS

    def test_includes_text_formats(self) -> None:
        """Test that text formats are supported."""
        assert ".txt" in SUPPORTED_EXTENSIONS
        assert ".md" in SUPPORTED_EXTENSIONS
        assert ".html" in SUPPORTED_EXTENSIONS


class TestExcludedDirs:
    """Tests for EXCLUDED_DIRS constant."""

    def test_includes_version_control_dirs(self) -> None:
        """Test that version control directories are excluded."""
        assert ".git" in EXCLUDED_DIRS
        assert ".svn" in EXCLUDED_DIRS
        assert ".hg" in EXCLUDED_DIRS

    def test_includes_build_dirs(self) -> None:
        """Test that build directories are excluded."""
        assert "dist" in EXCLUDED_DIRS
        assert "build" in EXCLUDED_DIRS
        assert "__pycache__" in EXCLUDED_DIRS

    def test_includes_dependency_dirs(self) -> None:
        """Test that dependency directories are excluded."""
        assert "node_modules" in EXCLUDED_DIRS
        assert ".venv" in EXCLUDED_DIRS
        assert "venv" in EXCLUDED_DIRS
