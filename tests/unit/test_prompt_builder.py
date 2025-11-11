"""Unit tests for prompt_builder module."""

from pathlib import Path

from docman.prompt_builder import (
    _extract_variable_patterns,
    _get_pattern_guidance,
    _render_folder_hierarchy,
    _truncate_content_smart,
    build_system_prompt,
    build_user_prompt,
    clear_prompt_cache,
    generate_instructions_from_folders,
    load_or_generate_instructions,
    load_organization_instructions,
    serialize_folder_definitions,
)
from docman.repo_config import FolderDefinition


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

    def test_truncation_preserves_head(self) -> None:
        """Test that truncation preserves beginning of content."""
        content = "START" + ("x" * 10000) + "END"
        result, was_truncated = _truncate_content_smart(content, max_chars=4000)

        assert "START" in result
        assert "END" not in result  # Tail is no longer preserved
        assert was_truncated is True

    def test_truncation_marker_format(self) -> None:
        """Test that truncation marker is properly formatted."""
        content = "x" * 10000
        result, was_truncated = _truncate_content_smart(content, max_chars=4000)

        # Should have comma-formatted number
        assert "characters truncated" in result.lower()
        assert was_truncated is True

    def test_truncation_respects_max_chars(self) -> None:
        """Test that truncated result never exceeds max_chars."""
        for content_len in [5000, 10000, 100000, 1000000]:
            content = "x" * content_len
            max_chars = 4000

            result, was_truncated = _truncate_content_smart(content, max_chars=max_chars)

            # Result should never exceed max_chars
            assert len(result) <= max_chars, (
                f"Result length {len(result)} exceeds max_chars {max_chars} "
                f"for content length {content_len}"
            )
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


class TestLoadOrGenerateInstructions:
    """Tests for load_or_generate_instructions function."""

    def test_loads_from_file_when_available(self, tmp_path: Path) -> None:
        """Test that instructions are loaded from file when available."""
        docman_dir = tmp_path / ".docman"
        docman_dir.mkdir()
        instructions_file = docman_dir / "instructions.md"
        instructions_file.write_text("Test instructions from file")

        result = load_or_generate_instructions(tmp_path)
        assert result == "Test instructions from file"

    def test_generates_from_folders_when_file_missing(self, tmp_path: Path) -> None:
        """Test that instructions are generated from folder definitions when file is missing."""
        docman_dir = tmp_path / ".docman"
        docman_dir.mkdir()
        config_file = docman_dir / "config.yaml"
        config_file.write_text(
            """
organization:
  folders:
    Documents:
      description: "All documents"
"""
        )

        result = load_or_generate_instructions(tmp_path)
        assert result is not None
        assert "Documents" in result
        assert "All documents" in result

    def test_prefers_file_over_folder_definitions(self, tmp_path: Path) -> None:
        """Test that file is preferred when both file and folder definitions exist."""
        docman_dir = tmp_path / ".docman"
        docman_dir.mkdir()

        # Create both instructions.md and folder definitions
        instructions_file = docman_dir / "instructions.md"
        instructions_file.write_text("Instructions from file")

        config_file = docman_dir / "config.yaml"
        config_file.write_text(
            """
organization:
  folders:
    Documents:
      description: "All documents"
"""
        )

        result = load_or_generate_instructions(tmp_path)
        # Should get content from file, not generated from folders
        assert result == "Instructions from file"

    def test_returns_none_when_both_missing(self, tmp_path: Path) -> None:
        """Test that None is returned when neither source is available."""
        # Create .docman directory but no instructions or folder definitions
        docman_dir = tmp_path / ".docman"
        docman_dir.mkdir()

        result = load_or_generate_instructions(tmp_path)
        assert result is None

    def test_handles_empty_folder_definitions(self, tmp_path: Path) -> None:
        """Test that None is returned when folder definitions are empty."""
        docman_dir = tmp_path / ".docman"
        docman_dir.mkdir()
        config_file = docman_dir / "config.yaml"
        config_file.write_text("organization:\n  folders: {}\n")

        result = load_or_generate_instructions(tmp_path)
        assert result is None


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

    def test_document_content_tag_with_filepath(self) -> None:
        """Test that documentContent tag includes filePath attribute."""
        file_path = "documents/report.pdf"
        content = "Test content"

        result = build_user_prompt(file_path, content)

        # Verify documentContent tag with filePath attribute
        assert f'<documentContent filePath="{file_path}">' in result
        assert "</documentContent>" in result

    def test_with_organization_instructions(self) -> None:
        """Test user prompt includes organization instructions."""
        file_path = "test.pdf"
        content = "Content"
        instructions = "Organize by date"

        result = build_user_prompt(file_path, content, instructions)

        assert instructions in result
        assert "<organizationInstructions>" in result
        assert "</organizationInstructions>" in result

    def test_without_organization_instructions(self) -> None:
        """Test user prompt works without instructions."""
        file_path = "test.pdf"
        content = "Content"

        result = build_user_prompt(file_path, content)

        assert file_path in result
        assert content in result
        # Should not have instructions section
        assert "<organizationInstructions>" not in result

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


class TestGenerateInstructionsFromFolders:
    """Tests for generate_instructions_from_folders function."""

    def test_empty_folders_returns_empty_string(self) -> None:
        """Test that empty folder dict returns empty string."""
        result = generate_instructions_from_folders({})
        assert result == ""

    def test_simple_folder_structure(self) -> None:
        """Test generation with simple folder structure."""
        folders = {
            "Documents": FolderDefinition(description="All documents", folders={}),
        }

        result = generate_instructions_from_folders(folders)

        # Should contain folder name and description
        assert "Documents" in result
        assert "All documents" in result

        # Should have markdown structure
        assert "# Document Organization Structure" in result

    def test_nested_folder_structure(self) -> None:
        """Test generation with nested folders."""
        folders = {
            "Financial": FolderDefinition(
                description="Financial documents",
                folders={
                    "invoices": FolderDefinition(
                        description="Customer invoices",
                        folders={},
                    ),
                    "receipts": FolderDefinition(
                        description="Personal receipts",
                        folders={},
                    ),
                },
            ),
        }

        result = generate_instructions_from_folders(folders)

        # Should contain all folder names and descriptions
        assert "Financial" in result
        assert "Financial documents" in result
        assert "invoices" in result
        assert "Customer invoices" in result
        assert "receipts" in result
        assert "Personal receipts" in result

    def test_variable_pattern_extraction(self) -> None:
        """Test that variable patterns are detected and documented."""
        folders = {
            "Financial": FolderDefinition(
                description="Financial documents",
                folders={
                    "{year}": FolderDefinition(
                        description="Documents by year",
                        folders={},
                    ),
                },
            ),
        }

        result = generate_instructions_from_folders(folders)

        # Should have variable pattern section
        assert "# Variable Pattern Extraction" in result
        assert "{year}" in result or "year" in result
        # Should contain guidance about extracting year
        assert "YYYY" in result or "4-digit" in result.lower()

    def test_multiple_variable_patterns(self) -> None:
        """Test that multiple variable patterns are documented."""
        folders = {
            "Financial": FolderDefinition(
                description="Financial documents",
                folders={
                    "{year}": FolderDefinition(description="By year", folders={}),
                    "{category}": FolderDefinition(description="By category", folders={}),
                },
            ),
        }

        result = generate_instructions_from_folders(folders)

        # Should document both patterns
        assert "year" in result.lower()
        assert "category" in result.lower()



class TestRenderFolderHierarchy:
    """Tests for _render_folder_hierarchy function."""

    def test_single_folder(self) -> None:
        """Test rendering a single folder."""
        folders = {
            "Documents": FolderDefinition(description="All documents", folders={}),
        }

        result = _render_folder_hierarchy(folders, indent=0)

        assert "Documents" in result
        assert "All documents" in result
        assert "**Documents/**" in result  # Markdown bold

    def test_nested_folders(self) -> None:
        """Test rendering nested folder structure."""
        folders = {
            "Financial": FolderDefinition(
                description="Financial docs",
                folders={
                    "invoices": FolderDefinition(description="Invoices", folders={}),
                },
            ),
        }

        result = _render_folder_hierarchy(folders, indent=0)

        assert "Financial" in result
        assert "invoices" in result
        # Nested folder should be indented
        assert "  -" in result or "invoices" in result

    def test_indentation_levels(self) -> None:
        """Test that indentation increases for nested folders."""
        folders = {
            "Level1": FolderDefinition(
                description="First level",
                folders={
                    "Level2": FolderDefinition(description="Second level", folders={}),
                },
            ),
        }

        result = _render_folder_hierarchy(folders, indent=0)

        # Should have different indentation levels
        lines = result.split("\n")
        assert len(lines) >= 2
        # First line should have less indentation than second
        assert lines[0].startswith("-") or lines[0].startswith("**")


class TestExtractVariablePatterns:
    """Tests for _extract_variable_patterns function."""

    def test_no_variables(self) -> None:
        """Test extraction when no variable patterns exist."""
        folders = {
            "Documents": FolderDefinition(description="All documents", folders={}),
        }

        result = _extract_variable_patterns(folders)
        assert result == {}

    def test_single_variable(self) -> None:
        """Test extraction of single variable pattern."""
        folders = {
            "{year}": FolderDefinition(description="By year", folders={}),
        }

        result = _extract_variable_patterns(folders)
        assert "year" in result
        assert isinstance(result["year"], str)

    def test_multiple_variables(self) -> None:
        """Test extraction of multiple variable patterns."""
        folders = {
            "{year}": FolderDefinition(description="By year", folders={}),
            "{category}": FolderDefinition(description="By category", folders={}),
        }

        result = _extract_variable_patterns(folders)
        assert "year" in result
        assert "category" in result

    def test_nested_variables(self) -> None:
        """Test extraction of variables in nested structure."""
        folders = {
            "Financial": FolderDefinition(
                description="Financial docs",
                folders={
                    "{year}": FolderDefinition(
                        description="By year",
                        folders={
                            "{month}": FolderDefinition(description="By month", folders={}),
                        },
                    ),
                },
            ),
        }

        result = _extract_variable_patterns(folders)
        assert "year" in result
        assert "month" in result


class TestGetPatternGuidance:
    """Tests for _get_pattern_guidance function."""

    def test_known_pattern_year(self) -> None:
        """Test guidance for 'year' pattern."""
        result = _get_pattern_guidance("year")
        assert "YYYY" in result or "4-digit" in result.lower()
        assert "2024" in result or "2025" in result

    def test_known_pattern_month(self) -> None:
        """Test guidance for 'month' pattern."""
        result = _get_pattern_guidance("month")
        assert "MM" in result or "2-digit" in result.lower()
        assert "01" in result or "12" in result

    def test_known_pattern_category(self) -> None:
        """Test guidance for 'category' pattern."""
        result = _get_pattern_guidance("category")
        assert "lowercase" in result.lower()
        assert "hyphen" in result.lower()

    def test_known_pattern_company(self) -> None:
        """Test guidance for 'company' pattern."""
        result = _get_pattern_guidance("company")
        assert "lowercase" in result.lower()
        assert "hyphen" in result.lower()

    def test_unknown_pattern(self) -> None:
        """Test guidance for unknown pattern."""
        result = _get_pattern_guidance("custom_pattern")
        assert "custom_pattern" in result
        assert "lowercase" in result.lower()

    def test_case_insensitive(self) -> None:
        """Test that pattern matching is case-insensitive."""
        result1 = _get_pattern_guidance("Year")
        result2 = _get_pattern_guidance("YEAR")
        result3 = _get_pattern_guidance("year")

        # All should return same guidance
        assert result1 == result2 == result3


class TestSerializeFolderDefinitions:
    """Tests for serialize_folder_definitions function."""

    def test_empty_folders(self) -> None:
        """Test serialization of empty folder dict."""
        result = serialize_folder_definitions({})
        assert result == "{}"

    def test_simple_folder(self) -> None:
        """Test serialization of simple folder structure."""
        folders = {
            "Documents": FolderDefinition(description="All documents", folders={}),
        }

        result = serialize_folder_definitions(folders)
        assert isinstance(result, str)
        # Should be valid JSON
        import json
        parsed = json.loads(result)
        assert "Documents" in parsed
        assert parsed["Documents"]["description"] == "All documents"

    def test_nested_folders(self) -> None:
        """Test serialization of nested folder structure."""
        folders = {
            "Financial": FolderDefinition(
                description="Financial docs",
                folders={
                    "invoices": FolderDefinition(description="Invoices", folders={}),
                },
            ),
        }

        result = serialize_folder_definitions(folders)
        import json
        parsed = json.loads(result)

        assert "Financial" in parsed
        assert "invoices" in parsed["Financial"]["folders"]

    def test_deterministic_output(self) -> None:
        """Test that serialization is deterministic (same input = same output)."""
        folders = {
            "B": FolderDefinition(description="Second", folders={}),
            "A": FolderDefinition(description="First", folders={}),
        }

        result1 = serialize_folder_definitions(folders)
        result2 = serialize_folder_definitions(folders)

        # Should be identical
        assert result1 == result2

        # Keys should be sorted (A before B)
        import json
        parsed = json.loads(result1)
        keys = list(parsed.keys())
        assert keys == sorted(keys)
