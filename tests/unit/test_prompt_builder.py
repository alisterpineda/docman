"""Unit tests for prompt_builder module."""

from pathlib import Path

import pytest

from docman.prompt_builder import (
    build_system_prompt,
    build_user_prompt,
    get_directory_structure,
    load_organization_instructions,
)


class TestGetDirectoryStructure:
    """Tests for get_directory_structure function."""

    def test_empty_repository(self, tmp_path: Path) -> None:
        """Test with empty repository (no subdirectories)."""
        result = get_directory_structure(tmp_path)
        assert result == ""

    def test_single_directory(self, tmp_path: Path) -> None:
        """Test with single subdirectory."""
        (tmp_path / "docs").mkdir()
        result = get_directory_structure(tmp_path)
        assert result == "- /docs"

    def test_nested_directories(self, tmp_path: Path) -> None:
        """Test with nested directory structure."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "reports").mkdir()
        (tmp_path / "data").mkdir()

        result = get_directory_structure(tmp_path)

        # Should be sorted
        lines = result.split("\n")
        assert len(lines) == 3
        assert "- /data" in lines
        assert "- /docs" in lines
        assert "- /docs/reports" in lines

    def test_excludes_docman_directory(self, tmp_path: Path) -> None:
        """Test that .docman directory is excluded."""
        (tmp_path / ".docman").mkdir()
        (tmp_path / "docs").mkdir()

        result = get_directory_structure(tmp_path)

        assert ".docman" not in result
        assert "- /docs" in result

    def test_excludes_git_directory(self, tmp_path: Path) -> None:
        """Test that .git directory is excluded."""
        (tmp_path / ".git").mkdir()
        (tmp_path / "src").mkdir()

        result = get_directory_structure(tmp_path)

        assert ".git" not in result
        assert "- /src" in result

    def test_files_not_included(self, tmp_path: Path) -> None:
        """Test that files are not included in directory structure."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "file.txt").touch()
        (tmp_path / "docs" / "report.pdf").touch()

        result = get_directory_structure(tmp_path)

        assert "file.txt" not in result
        assert "report.pdf" not in result
        assert result == "- /docs"


class TestLoadOrganizationInstructions:
    """Tests for load_organization_instructions function."""

    def test_no_instructions_file(self, tmp_path: Path) -> None:
        """Test when instructions file doesn't exist."""
        result = load_organization_instructions(tmp_path)
        assert result is None

    def test_empty_instructions_file(self, tmp_path: Path) -> None:
        """Test when instructions file is empty."""
        docman_dir = tmp_path / ".docman"
        docman_dir.mkdir()
        instructions_file = docman_dir / "instructions.md"
        instructions_file.write_text("")

        result = load_organization_instructions(tmp_path)
        assert result is None

    def test_whitespace_only_instructions(self, tmp_path: Path) -> None:
        """Test when instructions file contains only whitespace."""
        docman_dir = tmp_path / ".docman"
        docman_dir.mkdir()
        instructions_file = docman_dir / "instructions.md"
        instructions_file.write_text("   \n\t\n   ")

        result = load_organization_instructions(tmp_path)
        assert result is None

    def test_valid_instructions(self, tmp_path: Path) -> None:
        """Test when instructions file has valid content."""
        docman_dir = tmp_path / ".docman"
        docman_dir.mkdir()
        instructions_file = docman_dir / "instructions.md"
        content = "Organize by date and category"
        instructions_file.write_text(content)

        result = load_organization_instructions(tmp_path)
        assert result == content

    def test_instructions_with_whitespace(self, tmp_path: Path) -> None:
        """Test that leading/trailing whitespace is stripped."""
        docman_dir = tmp_path / ".docman"
        docman_dir.mkdir()
        instructions_file = docman_dir / "instructions.md"
        instructions_file.write_text("\n  Some instructions  \n")

        result = load_organization_instructions(tmp_path)
        assert result == "Some instructions"


class TestBuildSystemPrompt:
    """Tests for build_system_prompt function."""

    def test_returns_non_empty_string(self) -> None:
        """Test that system prompt is not empty."""
        result = build_system_prompt()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_key_elements(self) -> None:
        """Test that system prompt contains expected elements."""
        result = build_system_prompt()

        # Should mention document organization
        assert "document organization" in result.lower()

        # Should mention JSON format
        assert "JSON" in result or "json" in result

        # Should mention required fields
        assert "suggested_directory_path" in result
        assert "suggested_filename" in result
        assert "reason" in result
        assert "confidence" in result


class TestBuildUserPrompt:
    """Tests for build_user_prompt function."""

    def test_basic_prompt_structure(self) -> None:
        """Test basic user prompt structure."""
        file_path = "test.pdf"
        content = "This is test content"

        result = build_user_prompt(file_path, content)

        assert file_path in result
        assert content in result

    def test_with_directory_structure(self) -> None:
        """Test user prompt includes directory structure."""
        file_path = "test.pdf"
        content = "Content"
        dir_structure = "- /docs\n- /reports"

        result = build_user_prompt(file_path, content, dir_structure)

        assert dir_structure in result
        assert "Directory Structure" in result or "directory structure" in result

    def test_with_organization_instructions(self) -> None:
        """Test user prompt includes organization instructions."""
        file_path = "test.pdf"
        content = "Content"
        instructions = "Organize by date"

        result = build_user_prompt(file_path, content, None, instructions)

        assert instructions in result
        assert "Document Organization Instructions" in result

    def test_with_all_optional_fields(self) -> None:
        """Test user prompt with all optional fields."""
        file_path = "test.pdf"
        content = "Content"
        dir_structure = "- /docs"
        instructions = "Organize by date"

        result = build_user_prompt(file_path, content, dir_structure, instructions)

        assert file_path in result
        assert content in result
        assert dir_structure in result
        assert instructions in result

    def test_content_truncation(self) -> None:
        """Test that long content is truncated."""
        file_path = "test.pdf"
        content = "x" * 5000  # 5000 characters

        result = build_user_prompt(file_path, content)

        # Should contain truncated marker
        assert "truncated" in result.lower()
        # Should not contain full content
        assert len(result) < len(content) + 1000

    def test_short_content_not_truncated(self) -> None:
        """Test that short content is not truncated."""
        file_path = "test.pdf"
        content = "Short content"

        result = build_user_prompt(file_path, content)

        # Should contain full content
        assert content in result
        # Should not have truncation marker
        assert "truncated" not in result.lower()
