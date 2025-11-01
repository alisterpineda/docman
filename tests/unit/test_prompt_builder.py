"""Unit tests for prompt_builder module."""

from pathlib import Path

import pytest

from docman.prompt_builder import (
    _truncate_content_smart,
    build_system_prompt,
    build_user_prompt,
    clear_prompt_cache,
    load_organization_instructions,
)


class TestTruncateContentSmart:
    """Tests for _truncate_content_smart function."""

    def test_short_content_not_truncated(self) -> None:
        """Test that short content is not truncated."""
        content = "Short content"
        result, was_truncated = _truncate_content_smart(content, max_chars=4000)

        assert result == content
        assert was_truncated is False

    def test_long_content_truncated(self) -> None:
        """Test that long content is truncated."""
        content = "x" * 10000
        result, was_truncated = _truncate_content_smart(content, max_chars=4000)

        assert len(result) < len(content)
        assert was_truncated is True
        assert "truncated" in result.lower()

    def test_truncation_preserves_head_and_tail(self) -> None:
        """Test that truncation preserves beginning and end."""
        content = "START" + ("x" * 10000) + "END"
        result, was_truncated = _truncate_content_smart(content, max_chars=4000)

        assert "START" in result
        assert "END" in result
        assert was_truncated is True

    def test_truncation_marker_format(self) -> None:
        """Test that truncation marker is properly formatted."""
        content = "x" * 10000
        result, was_truncated = _truncate_content_smart(content, max_chars=4000)

        # Should have comma-formatted number
        assert "characters truncated" in result.lower()
        assert was_truncated is True

    def test_custom_ratios(self) -> None:
        """Test that custom head/tail ratios work."""
        content = "x" * 10000
        result, was_truncated = _truncate_content_smart(
            content, max_chars=1000, head_ratio=0.8, tail_ratio=0.1
        )

        assert len(result) < len(content)
        assert was_truncated is True


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
        # Clear cache to ensure fresh result
        clear_prompt_cache()
        result = build_system_prompt()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_key_elements(self) -> None:
        """Test that system prompt contains expected elements."""
        clear_prompt_cache()
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

    def test_caching(self) -> None:
        """Test that system prompt is cached."""
        clear_prompt_cache()

        prompt1 = build_system_prompt()
        prompt2 = build_system_prompt()

        # Should return the same object (cached)
        assert prompt1 is prompt2

    def test_cache_clearing(self) -> None:
        """Test that cache can be cleared."""
        clear_prompt_cache()
        prompt1 = build_system_prompt()

        clear_prompt_cache()
        prompt2 = build_system_prompt()

        # Should be equal (content is the same)
        assert prompt1 == prompt2
        # Note: We can't reliably test object identity (is/is not) because
        # Python may intern identical strings, especially long template strings


class TestBuildUserPrompt:
    """Tests for build_user_prompt function."""

    def test_basic_prompt_structure(self) -> None:
        """Test basic user prompt structure."""
        file_path = "test.pdf"
        content = "This is test content"

        result = build_user_prompt(file_path, content)

        assert file_path in result
        assert content in result

    def test_with_organization_instructions(self) -> None:
        """Test user prompt includes organization instructions."""
        file_path = "test.pdf"
        content = "Content"
        instructions = "Organize by date"

        result = build_user_prompt(file_path, content, instructions)

        assert instructions in result
        assert "Document Organization Instructions" in result

    def test_without_organization_instructions(self) -> None:
        """Test user prompt works without instructions."""
        file_path = "test.pdf"
        content = "Content"

        result = build_user_prompt(file_path, content)

        assert file_path in result
        assert content in result
        # Should not have instructions section
        assert "Document Organization Instructions" not in result

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
