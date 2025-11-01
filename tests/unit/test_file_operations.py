"""Unit tests for file operations module."""

from pathlib import Path

import pytest

from docman.file_operations import (
    ConflictResolution,
    FileConflictError,
    FileNotFoundError,
    FileOperationError,
    move_file,
)


class TestMoveFile:
    """Tests for move_file function."""

    def test_move_file_basic(self, tmp_path: Path) -> None:
        """Test basic file move operation."""
        # Create source file
        source = tmp_path / "source.txt"
        source.write_text("test content")

        # Define target
        target_dir = tmp_path / "target"
        target = target_dir / "dest.txt"

        # Move file
        result = move_file(source, target, create_dirs=True)

        # Verify move was successful
        assert result == target
        assert not source.exists()
        assert target.exists()
        assert target.read_text() == "test content"

    def test_move_file_source_not_found(self, tmp_path: Path) -> None:
        """Test that FileNotFoundError is raised when source doesn't exist."""
        source = tmp_path / "nonexistent.txt"
        target = tmp_path / "target.txt"

        with pytest.raises(FileNotFoundError) as exc_info:
            move_file(source, target)

        assert exc_info.value.source == source

    def test_move_file_source_is_directory(self, tmp_path: Path) -> None:
        """Test that FileOperationError is raised when source is a directory."""
        source = tmp_path / "source_dir"
        source.mkdir()
        target = tmp_path / "target"

        with pytest.raises(FileOperationError, match="Source is not a file"):
            move_file(source, target)

    def test_move_file_target_exists_skip(self, tmp_path: Path) -> None:
        """Test that FileConflictError is raised when target exists and resolution is SKIP."""
        # Create source and target files
        source = tmp_path / "source.txt"
        source.write_text("source content")

        target = tmp_path / "target.txt"
        target.write_text("target content")

        # Attempt to move with SKIP resolution
        with pytest.raises(FileConflictError) as exc_info:
            move_file(source, target, conflict_resolution=ConflictResolution.SKIP)

        # Verify both files still exist
        assert source.exists()
        assert target.exists()
        assert target.read_text() == "target content"
        assert exc_info.value.source == source
        assert exc_info.value.target == target

    def test_move_file_target_exists_overwrite(self, tmp_path: Path) -> None:
        """Test that file is overwritten when target exists and resolution is OVERWRITE."""
        # Create source and target files
        source = tmp_path / "source.txt"
        source.write_text("source content")

        target = tmp_path / "target.txt"
        target.write_text("target content")

        # Move with OVERWRITE resolution
        result = move_file(source, target, conflict_resolution=ConflictResolution.OVERWRITE)

        # Verify overwrite was successful
        assert result == target
        assert not source.exists()
        assert target.exists()
        assert target.read_text() == "source content"

    def test_move_file_target_exists_rename(self, tmp_path: Path) -> None:
        """Test that file is renamed when target exists and resolution is RENAME."""
        # Create source and target files
        source = tmp_path / "source.txt"
        source.write_text("source content")

        target = tmp_path / "target.txt"
        target.write_text("target content")

        # Move with RENAME resolution
        result = move_file(source, target, conflict_resolution=ConflictResolution.RENAME)

        # Verify rename was successful
        assert result != target
        assert result.name == "target_1.txt"
        assert not source.exists()
        assert target.exists()  # Original target still exists
        assert result.exists()  # Renamed file exists
        assert target.read_text() == "target content"
        assert result.read_text() == "source content"

    def test_move_file_target_exists_rename_multiple(self, tmp_path: Path) -> None:
        """Test that file is renamed with incremented suffix when multiple conflicts exist."""
        # Create source and multiple target files
        source = tmp_path / "source.txt"
        source.write_text("source content")

        (tmp_path / "target.txt").write_text("target content")
        (tmp_path / "target_1.txt").write_text("target_1 content")
        (tmp_path / "target_2.txt").write_text("target_2 content")

        target = tmp_path / "target.txt"

        # Move with RENAME resolution
        result = move_file(source, target, conflict_resolution=ConflictResolution.RENAME)

        # Verify rename was successful with _3 suffix
        assert result.name == "target_3.txt"
        assert not source.exists()
        assert result.exists()
        assert result.read_text() == "source content"

    def test_move_file_create_dirs_true(self, tmp_path: Path) -> None:
        """Test that target directories are created when create_dirs is True."""
        source = tmp_path / "source.txt"
        source.write_text("test content")

        target = tmp_path / "a" / "b" / "c" / "target.txt"

        result = move_file(source, target, create_dirs=True)

        assert result == target
        assert not source.exists()
        assert target.exists()
        assert target.read_text() == "test content"

    def test_move_file_create_dirs_false(self, tmp_path: Path) -> None:
        """Test that FileOperationError is raised when target directory doesn't exist and create_dirs is False."""
        source = tmp_path / "source.txt"
        source.write_text("test content")

        target = tmp_path / "nonexistent" / "target.txt"

        with pytest.raises(FileOperationError, match="Target directory does not exist"):
            move_file(source, target, create_dirs=False)

    def test_move_file_same_location(self, tmp_path: Path) -> None:
        """Test that moving a file to its current location is a no-op."""
        source = tmp_path / "file.txt"
        source.write_text("test content")

        # Move to same location
        result = move_file(source, source)

        # File should still exist at original location
        assert result == source
        assert source.exists()
        assert source.read_text() == "test content"

    def test_move_file_cross_filesystem_simulation(self, tmp_path: Path) -> None:
        """Test that shutil.move handles cross-filesystem moves correctly."""
        # This tests that we're using shutil.move which handles cross-filesystem moves
        # In practice, this is handled by shutil internally (copy + delete)
        source = tmp_path / "source.txt"
        source.write_text("test content")

        target = tmp_path / "subdir" / "target.txt"

        result = move_file(source, target, create_dirs=True)

        assert result == target
        assert not source.exists()
        assert target.exists()
        assert target.read_text() == "test content"

    def test_move_file_preserves_extension(self, tmp_path: Path) -> None:
        """Test that file extension is preserved in rename conflicts."""
        source = tmp_path / "source.pdf"
        source.write_text("pdf content")

        target = tmp_path / "target.pdf"
        target.write_text("existing target")

        result = move_file(source, target, conflict_resolution=ConflictResolution.RENAME)

        assert result.suffix == ".pdf"
        assert result.name == "target_1.pdf"
