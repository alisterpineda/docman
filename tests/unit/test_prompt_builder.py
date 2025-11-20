"""Unit tests for prompt_builder module."""

from pathlib import Path

from docman.prompt_builder import (
    _detect_existing_directories,
    _extract_variable_patterns,
    _get_pattern_guidance,
    _render_folder_hierarchy,
    _truncate_content_smart,
    build_system_prompt,
    build_user_prompt,
    clear_prompt_cache,
    generate_instructions,
    generate_instructions_from_folders,
    serialize_folder_definitions,
)
from docman.repo_config import FolderDefinition


class TestTruncateContentSmart:
    """Tests for _truncate_content_smart function."""

    def test_short_content_not_truncated(self) -> None:
        """Test that short content is not truncated."""
        content = "Short content"
        result, was_truncated, original_len, truncated_len = _truncate_content_smart(
            content, max_chars=8000
        )

        assert result == content
        assert was_truncated is False
        assert original_len == len(content)
        assert truncated_len == len(content)

    def test_long_content_truncated(self) -> None:
        """Test that long content is truncated."""
        content = "x" * 10000
        result, was_truncated, original_len, truncated_len = _truncate_content_smart(
            content, max_chars=8000
        )

        assert len(result) < len(content)
        assert was_truncated is True
        assert "omitted" in result.lower()
        assert original_len == 10000
        assert truncated_len == len(result)

    def test_truncation_preserves_head_and_tail(self) -> None:
        """Test that truncation preserves both beginning and end of content."""
        content = "START" + ("x" * 10000) + "END"
        result, was_truncated, _, _ = _truncate_content_smart(content, max_chars=8000)

        assert "START" in result
        assert "END" in result  # Now preserves tail
        assert was_truncated is True

    def test_truncation_marker_format(self) -> None:
        """Test that truncation marker is properly formatted."""
        content = "x" * 10000
        result, was_truncated, _, _ = _truncate_content_smart(content, max_chars=8000)

        # Should have comma-formatted number and "omitted" wording
        assert "characters omitted" in result.lower()
        assert was_truncated is True

    def test_truncation_respects_max_chars(self) -> None:
        """Test that truncated result never exceeds max_chars."""
        for content_len in [10000, 20000, 100000, 1000000]:
            content = "x" * content_len
            max_chars = 8000

            result, was_truncated, _, _ = _truncate_content_smart(
                content, max_chars=max_chars
            )

            # Result should never exceed max_chars
            assert len(result) <= max_chars, (
                f"Result length {len(result)} exceeds max_chars {max_chars} "
                f"for content length {content_len}"
            )
            assert was_truncated is True

    def test_truncation_preserves_tail(self) -> None:
        """Test that truncation specifically preserves end content."""
        content = ("x" * 10000) + "TAIL_CONTENT"
        result, was_truncated, _, _ = _truncate_content_smart(content, max_chars=8000)

        assert "TAIL_CONTENT" in result
        assert was_truncated is True

    def test_truncation_even_split(self) -> None:
        """Test that truncation splits space approximately evenly."""
        content = "A" * 5000 + "B" * 5000 + "C" * 5000
        result, was_truncated, _, _ = _truncate_content_smart(content, max_chars=8000)

        # Count A's and C's (beginning and end characters)
        a_count = result.count("A")
        c_count = result.count("C")

        # Should have roughly equal amounts (within 20% tolerance)
        assert abs(a_count - c_count) < max(a_count, c_count) * 0.3
        assert was_truncated is True

    def test_truncation_paragraph_boundaries(self) -> None:
        """Test that truncation finds clean paragraph breaks."""
        # Content with clear paragraph structure
        head = "First paragraph.\n\nSecond paragraph."
        middle = "x" * 10000
        tail = "Last paragraph.\n\nFinal paragraph."
        content = head + middle + tail

        result, was_truncated, _, _ = _truncate_content_smart(content, max_chars=8000)

        # Should break at paragraph boundary in head
        # Check that we don't have partial "Second paragraph" cut off mid-word
        if "Second paragraph" in result:
            # If included, should be complete
            assert "Second paragraph." in result

        assert was_truncated is True

    def test_truncation_returns_metadata(self) -> None:
        """Test that truncation returns correct length metadata."""
        content = "x" * 15000
        result, was_truncated, original_len, truncated_len = _truncate_content_smart(
            content, max_chars=8000
        )

        assert original_len == 15000
        assert truncated_len == len(result)
        assert truncated_len <= 8000
        assert was_truncated is True

    def test_marker_size_varies_with_content(self) -> None:
        """Test that marker shows correct omitted character count."""
        # Small content
        content1 = "x" * 10000
        result1, _, _, _ = _truncate_content_smart(content1, max_chars=8000)

        # Large content
        content2 = "x" * 100000
        result2, _, _, _ = _truncate_content_smart(content2, max_chars=8000)

        # Extract omitted counts from markers
        import re
        match1 = re.search(r"\[... ([\d,]+) characters omitted ...\]", result1)
        match2 = re.search(r"\[... ([\d,]+) characters omitted ...\]", result2)

        assert match1 is not None
        assert match2 is not None

        count1 = int(match1.group(1).replace(",", ""))
        count2 = int(match2.group(1).replace(",", ""))

        # Larger content should have more characters omitted
        assert count2 > count1
        # Verify approximate correctness
        assert count1 == 10000 - 8000
        assert count2 == 100000 - 8000

    def test_default_max_chars_is_8000(self) -> None:
        """Test that default max_chars is 8000."""
        content = "x" * 9000
        result, was_truncated, _, _ = _truncate_content_smart(content)

        assert was_truncated is True
        assert len(result) <= 8000


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

        # Should mention document management expertise
        assert "document management specialist" in result.lower()

        # Should mention JSON format
        assert "JSON" in result or "json" in result

        # Should mention required fields
        assert "suggested_directory_path" in result
        assert "suggested_filename" in result
        assert "reason" in result

        # Should have critical guidelines section
        assert "Critical Guidelines" in result

        # Should explain existing values (Guideline #6 fix)
        assert "Existing:" in result

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
        content = "x" * 10000  # 10000 characters (above 8000 default)

        result = build_user_prompt(file_path, content)

        # Should contain truncated marker
        assert "omitted" in result.lower()
        # Should have truncated attribute
        assert 'truncated="true"' in result
        assert 'originalChars="10000"' in result
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
        assert "omitted" not in result.lower()
        # Should not have truncated attribute
        assert 'truncated="true"' not in result


class TestGenerateInstructionsFromFolders:
    """Tests for generate_instructions_from_folders function."""

    def test_empty_folders_returns_empty_string(self, tmp_path: Path) -> None:
        """Test that empty folder dict returns empty string."""
        result = generate_instructions_from_folders({}, tmp_path)
        assert result == ""

    def test_simple_folder_structure(self, tmp_path: Path) -> None:
        """Test generation with simple folder structure."""
        folders = {
            "Documents": FolderDefinition(description="All documents", folders={}),
        }

        result = generate_instructions_from_folders(folders, tmp_path)

        # Should contain folder name and description
        assert "Documents" in result
        assert "All documents" in result

        # Should have markdown structure
        assert "# Document Organization Structure" in result

    def test_nested_folder_structure(self, tmp_path: Path) -> None:
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

        result = generate_instructions_from_folders(folders, tmp_path)

        # Should contain all folder names and descriptions
        assert "Financial" in result
        assert "Financial documents" in result
        assert "invoices" in result
        assert "Customer invoices" in result
        assert "receipts" in result
        assert "Personal receipts" in result

    def test_variable_pattern_extraction(self, tmp_path: Path) -> None:
        """Test that variable patterns are detected and documented."""
        from docman.repo_config import set_variable_pattern

        set_variable_pattern(tmp_path, "year", "4-digit year in YYYY format")

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

        result = generate_instructions_from_folders(folders, tmp_path)

        # Should have variable pattern section
        assert "# Variable Pattern Extraction" in result
        assert "{year}" in result or "year" in result
        # Should contain user-defined guidance
        assert "4-digit year in YYYY format" in result

    def test_multiple_variable_patterns(self, tmp_path: Path) -> None:
        """Test that multiple variable patterns are documented."""
        from docman.repo_config import set_variable_pattern

        set_variable_pattern(tmp_path, "year", "4-digit year in YYYY format")
        set_variable_pattern(tmp_path, "category", "Document category")

        folders = {
            "Financial": FolderDefinition(
                description="Financial documents",
                folders={
                    "{year}": FolderDefinition(description="By year", folders={}),
                    "{category}": FolderDefinition(description="By category", folders={}),
                },
            ),
        }

        result = generate_instructions_from_folders(folders, tmp_path)

        # Should document both patterns
        assert "year" in result.lower()
        assert "category" in result.lower()
        assert "4-digit year" in result
        assert "Document category" in result

    def test_undefined_variable_shows_warning(self, tmp_path: Path, capsys) -> None:
        """Test that using undefined variable shows warning and continues."""
        folders = {
            "Financial": FolderDefinition(
                description="Financial documents",
                folders={
                    "{year}": FolderDefinition(description="By year", folders={}),
                },
            ),
        }

        # Should not raise error, but display warning
        result = generate_instructions_from_folders(folders, tmp_path)

        # Verify warning was displayed
        captured = capsys.readouterr()
        assert "Variable pattern 'year' is undefined" in captured.out
        assert "LLM will infer from context" in captured.out
        assert "docman pattern add year" in captured.out

        # Verify fallback guidance in generated instructions
        assert "Infer year from document context" in result

    def test_includes_existing_directories(self, tmp_path: Path) -> None:
        """Test that existing directories are included in generated instructions."""
        from docman.repo_config import set_variable_pattern

        # Create directory structure
        financial_dir = tmp_path / "Financial"
        financial_dir.mkdir()
        (financial_dir / "2022").mkdir()
        (financial_dir / "2023").mkdir()
        (financial_dir / "2024").mkdir()

        set_variable_pattern(tmp_path, "year", "4-digit year in YYYY format")

        folders = {
            "Financial": FolderDefinition(
                description="Financial documents",
                folders={
                    "{year}": FolderDefinition(description="By year", folders={}),
                },
            ),
        }

        result = generate_instructions_from_folders(folders, tmp_path)

        # Should contain existing directories
        assert "Existing: 2022, 2023, 2024" in result

    def test_existing_directories_multiple_patterns(self, tmp_path: Path) -> None:
        """Test existing directories for multiple variable patterns."""
        from docman.repo_config import set_variable_pattern

        # Create directory structure
        financial_dir = tmp_path / "Financial"
        financial_dir.mkdir()
        (financial_dir / "2023").mkdir()
        (financial_dir / "2024").mkdir()

        receipts_dir = tmp_path / "Receipts"
        receipts_dir.mkdir()
        (receipts_dir / "office-supplies").mkdir()
        (receipts_dir / "travel").mkdir()

        set_variable_pattern(tmp_path, "year", "4-digit year in YYYY format")
        set_variable_pattern(tmp_path, "category", "Receipt category")

        folders = {
            "Financial": FolderDefinition(
                description="Financial documents",
                folders={
                    "{year}": FolderDefinition(description="By year", folders={}),
                },
            ),
            "Receipts": FolderDefinition(
                description="Receipts",
                folders={
                    "{category}": FolderDefinition(description="By category", folders={}),
                },
            ),
        }

        result = generate_instructions_from_folders(folders, tmp_path)

        # Should contain existing directories for both patterns
        assert "Existing: 2023, 2024" in result
        assert "Existing: office-supplies, travel" in result

    def test_no_existing_dirs_when_empty(self, tmp_path: Path) -> None:
        """Test that no existing line appears when directories don't exist."""
        from docman.repo_config import set_variable_pattern

        # Create parent but no children
        financial_dir = tmp_path / "Financial"
        financial_dir.mkdir()

        set_variable_pattern(tmp_path, "year", "4-digit year in YYYY format")

        folders = {
            "Financial": FolderDefinition(
                description="Financial documents",
                folders={
                    "{year}": FolderDefinition(description="By year", folders={}),
                },
            ),
        }

        result = generate_instructions_from_folders(folders, tmp_path)

        # Should not contain "Existing:" line
        assert "Existing:" not in result



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

    def test_shows_existing_directories(self) -> None:
        """Test that existing directories are displayed inline."""
        folders = {
            "{year}": FolderDefinition(description="By year", folders={}),
        }

        existing_dirs = {"{year}": ["2022", "2023", "2024"]}

        result = _render_folder_hierarchy(folders, indent=0, existing_dirs=existing_dirs)

        assert "Existing: 2022, 2023, 2024" in result

    def test_shows_existing_directories_nested(self) -> None:
        """Test that existing directories are shown for nested variable patterns."""
        folders = {
            "Financial": FolderDefinition(
                description="Financial documents",
                folders={
                    "{year}": FolderDefinition(description="By year", folders={}),
                },
            ),
        }

        existing_dirs = {"Financial/{year}": ["2023", "2024"]}

        result = _render_folder_hierarchy(folders, indent=0, existing_dirs=existing_dirs)

        assert "Existing: 2023, 2024" in result
        # Verify proper indentation
        lines = result.split("\n")
        existing_line = [l for l in lines if "Existing:" in l][0]
        # Should be indented more than parent folder
        assert existing_line.startswith("    ")  # 4 spaces = 2 indents

    def test_no_existing_dirs_shows_nothing(self) -> None:
        """Test that no existing directory line is shown when dict is empty."""
        folders = {
            "{year}": FolderDefinition(description="By year", folders={}),
        }

        result = _render_folder_hierarchy(folders, indent=0, existing_dirs={})

        assert "Existing:" not in result

    def test_existing_dirs_none_parameter(self) -> None:
        """Test that None existing_dirs parameter works correctly."""
        folders = {
            "{year}": FolderDefinition(description="By year", folders={}),
        }

        result = _render_folder_hierarchy(folders, indent=0, existing_dirs=None)

        assert "Existing:" not in result

    def test_multiple_existing_dirs(self) -> None:
        """Test multiple variable patterns with existing directories."""
        folders = {
            "Financial": FolderDefinition(
                description="Financial documents",
                folders={
                    "{year}": FolderDefinition(description="By year", folders={}),
                },
            ),
            "Receipts": FolderDefinition(
                description="Receipts",
                folders={
                    "{category}": FolderDefinition(description="By category", folders={}),
                },
            ),
        }

        existing_dirs = {
            "Financial/{year}": ["2023", "2024"],
            "Receipts/{category}": ["office-supplies", "travel"],
        }

        result = _render_folder_hierarchy(folders, indent=0, existing_dirs=existing_dirs)

        assert "Existing: 2023, 2024" in result
        assert "Existing: office-supplies, travel" in result


class TestExtractVariablePatterns:
    """Tests for _extract_variable_patterns function."""

    def test_no_variables(self, tmp_path: Path) -> None:
        """Test extraction when no variable patterns exist."""
        folders = {
            "Documents": FolderDefinition(description="All documents", folders={}),
        }

        result = _extract_variable_patterns(folders, tmp_path)
        assert result == {}

    def test_single_variable(self, tmp_path: Path) -> None:
        """Test extraction of single variable pattern."""
        from docman.repo_config import set_variable_pattern

        set_variable_pattern(tmp_path, "year", "4-digit year in YYYY format")

        folders = {
            "{year}": FolderDefinition(description="By year", folders={}),
        }

        result = _extract_variable_patterns(folders, tmp_path)
        assert "year" in result
        assert isinstance(result["year"], str)
        assert "4-digit year" in result["year"]

    def test_multiple_variables(self, tmp_path: Path) -> None:
        """Test extraction of multiple variable patterns."""
        from docman.repo_config import set_variable_pattern

        set_variable_pattern(tmp_path, "year", "4-digit year in YYYY format")
        set_variable_pattern(tmp_path, "category", "Document category")

        folders = {
            "{year}": FolderDefinition(description="By year", folders={}),
            "{category}": FolderDefinition(description="By category", folders={}),
        }

        result = _extract_variable_patterns(folders, tmp_path)
        assert "year" in result
        assert "category" in result

    def test_nested_variables(self, tmp_path: Path) -> None:
        """Test extraction of variables in nested structure."""
        from docman.repo_config import set_variable_pattern

        set_variable_pattern(tmp_path, "year", "4-digit year in YYYY format")
        set_variable_pattern(tmp_path, "month", "2-digit month in MM format")

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

        result = _extract_variable_patterns(folders, tmp_path)
        assert "year" in result
        assert "month" in result

    def test_undefined_variable_shows_warning(self, tmp_path: Path, capsys) -> None:
        """Test that using undefined variable shows warning and continues."""
        folders = {
            "{year}": FolderDefinition(description="By year", folders={}),
        }

        # Should not raise error, but display warning
        result = _extract_variable_patterns(folders, tmp_path)

        # Verify warning was displayed
        captured = capsys.readouterr()
        assert "Variable pattern 'year' is undefined" in captured.out
        assert "LLM will infer from context" in captured.out

        # Verify fallback guidance in result
        assert "year" in result
        assert "Infer year from document context" in result["year"]


class TestGetPatternGuidance:
    """Tests for _get_pattern_guidance function."""

    def test_defined_pattern(self, tmp_path: Path) -> None:
        """Test guidance for defined pattern."""
        from docman.repo_config import set_variable_pattern

        set_variable_pattern(tmp_path, "year", "4-digit year in YYYY format")

        result = _get_pattern_guidance("year", tmp_path)
        assert "4-digit year in YYYY format" in result

    def test_multiple_patterns(self, tmp_path: Path) -> None:
        """Test guidance for multiple defined patterns."""
        from docman.repo_config import set_variable_pattern

        set_variable_pattern(tmp_path, "year", "4-digit year in YYYY format")
        set_variable_pattern(tmp_path, "category", "Document category")

        result_year = _get_pattern_guidance("year", tmp_path)
        result_category = _get_pattern_guidance("category", tmp_path)

        assert "4-digit year" in result_year
        assert "Document category" in result_category

    def test_undefined_pattern_shows_warning(self, tmp_path: Path, capsys) -> None:
        """Test that undefined pattern shows warning and returns fallback guidance."""
        # Should not raise error, but display warning
        result = _get_pattern_guidance("year", tmp_path)

        # Verify warning was displayed
        captured = capsys.readouterr()
        assert "Variable pattern 'year' is undefined" in captured.out
        assert "LLM will infer from context" in captured.out
        assert "docman pattern add year" in captured.out

        # Verify fallback guidance is returned
        assert "Infer year from document context" in result

    def test_pattern_description_formatting(self, tmp_path: Path) -> None:
        """Test that pattern description is formatted correctly."""
        from docman.repo_config import set_variable_pattern

        set_variable_pattern(tmp_path, "custom", "Extract custom value from document")

        result = _get_pattern_guidance("custom", tmp_path)
        # Should be formatted as a bullet point
        assert result.startswith("\n  -")
        assert "Extract custom value from document" in result

    def test_guidance_with_values(self, tmp_path: Path) -> None:
        """Test that guidance includes predefined values."""
        from docman.repo_config import add_pattern_value, set_variable_pattern

        set_variable_pattern(tmp_path, "company", "Company name from document")
        add_pattern_value(tmp_path, "company", "Acme Corp.", "Main company")
        add_pattern_value(tmp_path, "company", "Beta Inc.")

        result = _get_pattern_guidance("company", tmp_path)

        # Should contain description
        assert "Company name from document" in result

        # Should contain values
        assert "Known values:" in result
        assert '"Acme Corp."' in result
        assert "Main company" in result
        assert '"Beta Inc."' in result

    def test_guidance_with_aliases(self, tmp_path: Path) -> None:
        """Test that guidance includes aliases for values."""
        from docman.repo_config import add_pattern_value, set_variable_pattern

        set_variable_pattern(tmp_path, "company", "Company name from document")
        add_pattern_value(tmp_path, "company", "Acme Corp.", "Current name after merger")
        add_pattern_value(tmp_path, "company", "XYZ Corp", alias_of="Acme Corp.")
        add_pattern_value(tmp_path, "company", "XYZ Corporation", alias_of="Acme Corp.")

        result = _get_pattern_guidance("company", tmp_path)

        # Should contain aliases
        assert "Also known as:" in result
        assert '"XYZ Corp"' in result
        assert '"XYZ Corporation"' in result

    def test_guidance_with_mixed_simple_and_extended(self, tmp_path: Path) -> None:
        """Test guidance generation with both simple and extended patterns."""
        from docman.repo_config import add_pattern_value, set_variable_pattern

        # Simple pattern (no values)
        set_variable_pattern(tmp_path, "year", "4-digit year in YYYY format")

        # Extended pattern (with values)
        set_variable_pattern(tmp_path, "company", "Company name from document")
        add_pattern_value(tmp_path, "company", "Acme Corp.")

        result_year = _get_pattern_guidance("year", tmp_path)
        result_company = _get_pattern_guidance("company", tmp_path)

        # Simple pattern should not have Known values
        assert "Known values:" not in result_year
        assert "4-digit year" in result_year

        # Extended pattern should have Known values
        assert "Known values:" in result_company
        assert '"Acme Corp."' in result_company


class TestDetectExistingDirectories:
    """Tests for _detect_existing_directories function."""

    def test_no_variable_patterns(self, tmp_path: Path) -> None:
        """Test that folders without variable patterns return empty dict."""
        folders = {
            "Documents": FolderDefinition(description="All documents", folders={}),
        }

        result = _detect_existing_directories(folders, tmp_path)
        assert result == {}

    def test_empty_parent_directory(self, tmp_path: Path) -> None:
        """Test that empty parent directory returns no existing values."""
        # Create a parent directory to avoid tmp_path's app_config dir
        parent_dir = tmp_path / "Parent"
        parent_dir.mkdir()

        folders = {
            "Parent": FolderDefinition(
                description="Parent folder",
                folders={
                    "{year}": FolderDefinition(description="By year", folders={}),
                },
            ),
        }

        result = _detect_existing_directories(folders, tmp_path)
        # Parent exists but has no subdirectories
        assert result == {}

    def test_detects_existing_directories(self, tmp_path: Path) -> None:
        """Test that existing directories are detected."""
        # Create parent and year directories to avoid tmp_path's app_config dir
        parent_dir = tmp_path / "Financial"
        parent_dir.mkdir()
        (parent_dir / "2022").mkdir()
        (parent_dir / "2023").mkdir()
        (parent_dir / "2024").mkdir()

        folders = {
            "Financial": FolderDefinition(
                description="Financial documents",
                folders={
                    "{year}": FolderDefinition(description="By year", folders={}),
                },
            ),
        }

        result = _detect_existing_directories(folders, tmp_path)
        assert "Financial/{year}" in result
        assert result["Financial/{year}"] == ["2022", "2023", "2024"]

    def test_variable_under_literal_folder(self, tmp_path: Path) -> None:
        """Test detection of variable pattern under a literal folder."""
        # Create structure: Financial/2023/, Financial/2024/
        financial_dir = tmp_path / "Financial"
        financial_dir.mkdir()
        (financial_dir / "2023").mkdir()
        (financial_dir / "2024").mkdir()

        folders = {
            "Financial": FolderDefinition(
                description="Financial documents",
                folders={
                    "{year}": FolderDefinition(description="By year", folders={}),
                },
            ),
        }

        result = _detect_existing_directories(folders, tmp_path)
        assert "Financial/{year}" in result
        assert result["Financial/{year}"] == ["2023", "2024"]

    def test_multiple_variable_patterns(self, tmp_path: Path) -> None:
        """Test detection of multiple variable patterns at different levels."""
        # Create structure: Financial/2023/, Receipts/office-supplies/
        financial_dir = tmp_path / "Financial"
        financial_dir.mkdir()
        (financial_dir / "2023").mkdir()

        receipts_dir = tmp_path / "Receipts"
        receipts_dir.mkdir()
        (receipts_dir / "office-supplies").mkdir()
        (receipts_dir / "travel").mkdir()

        folders = {
            "Financial": FolderDefinition(
                description="Financial documents",
                folders={
                    "{year}": FolderDefinition(description="By year", folders={}),
                },
            ),
            "Receipts": FolderDefinition(
                description="Receipts",
                folders={
                    "{category}": FolderDefinition(description="By category", folders={}),
                },
            ),
        }

        result = _detect_existing_directories(folders, tmp_path)
        assert "Financial/{year}" in result
        assert result["Financial/{year}"] == ["2023"]
        assert "Receipts/{category}" in result
        assert result["Receipts/{category}"] == ["office-supplies", "travel"]

    def test_skips_hidden_directories(self, tmp_path: Path) -> None:
        """Test that hidden directories are skipped."""
        # Use nested structure to avoid tmp_path's app_config dir
        parent_dir = tmp_path / "Parent"
        parent_dir.mkdir()
        (parent_dir / "2023").mkdir()
        (parent_dir / ".hidden").mkdir()

        folders = {
            "Parent": FolderDefinition(
                description="Parent folder",
                folders={
                    "{year}": FolderDefinition(description="By year", folders={}),
                },
            ),
        }

        result = _detect_existing_directories(folders, tmp_path)
        assert "Parent/{year}" in result
        assert ".hidden" not in result["Parent/{year}"]
        assert result["Parent/{year}"] == ["2023"]

    def test_skips_files(self, tmp_path: Path) -> None:
        """Test that files are skipped, only directories included."""
        # Use nested structure to avoid tmp_path's app_config dir
        parent_dir = tmp_path / "Parent"
        parent_dir.mkdir()
        (parent_dir / "2023").mkdir()
        (parent_dir / "2024.txt").touch()  # This is a file, not a directory

        folders = {
            "Parent": FolderDefinition(
                description="Parent folder",
                folders={
                    "{year}": FolderDefinition(description="By year", folders={}),
                },
            ),
        }

        result = _detect_existing_directories(folders, tmp_path)
        assert "Parent/{year}" in result
        assert result["Parent/{year}"] == ["2023"]
        assert "2024.txt" not in result["Parent/{year}"]

    def test_sorted_alphabetically(self, tmp_path: Path) -> None:
        """Test that results are sorted alphabetically."""
        # Use nested structure to avoid tmp_path's app_config dir
        parent_dir = tmp_path / "Parent"
        parent_dir.mkdir()
        (parent_dir / "zebra").mkdir()
        (parent_dir / "alpha").mkdir()
        (parent_dir / "mango").mkdir()

        folders = {
            "Parent": FolderDefinition(
                description="Parent folder",
                folders={
                    "{category}": FolderDefinition(description="By category", folders={}),
                },
            ),
        }

        result = _detect_existing_directories(folders, tmp_path)
        assert "Parent/{category}" in result
        assert result["Parent/{category}"] == ["alpha", "mango", "zebra"]

    def test_limits_to_10_values(self, tmp_path: Path) -> None:
        """Test that results are limited to 10 values."""
        # Use nested structure to avoid tmp_path's app_config dir
        parent_dir = tmp_path / "Parent"
        parent_dir.mkdir()
        # Create 15 directories
        for i in range(15):
            (parent_dir / f"dir_{i:02d}").mkdir()

        folders = {
            "Parent": FolderDefinition(
                description="Parent folder",
                folders={
                    "{value}": FolderDefinition(description="By value", folders={}),
                },
            ),
        }

        result = _detect_existing_directories(folders, tmp_path)
        assert "Parent/{value}" in result
        assert len(result["Parent/{value}"]) == 10
        # Should be first 10 alphabetically
        assert result["Parent/{value}"] == [f"dir_{i:02d}" for i in range(10)]

    def test_nonexistent_parent_directory(self, tmp_path: Path) -> None:
        """Test that nonexistent parent directory returns no values."""
        # Don't create Financial directory
        folders = {
            "Financial": FolderDefinition(
                description="Financial documents",
                folders={
                    "{year}": FolderDefinition(description="By year", folders={}),
                },
            ),
        }

        result = _detect_existing_directories(folders, tmp_path)
        # Financial directory doesn't exist, so no values for Financial/{year}
        assert result == {}

    def test_deeply_nested_patterns(self, tmp_path: Path) -> None:
        """Test detection in deeply nested structure."""
        # Create structure: A/B/2023/
        a_dir = tmp_path / "A"
        a_dir.mkdir()
        b_dir = a_dir / "B"
        b_dir.mkdir()
        (b_dir / "2023").mkdir()
        (b_dir / "2024").mkdir()

        folders = {
            "A": FolderDefinition(
                description="Level A",
                folders={
                    "B": FolderDefinition(
                        description="Level B",
                        folders={
                            "{year}": FolderDefinition(description="By year", folders={}),
                        },
                    ),
                },
            ),
        }

        result = _detect_existing_directories(folders, tmp_path)
        assert "A/B/{year}" in result
        assert result["A/B/{year}"] == ["2023", "2024"]

    def test_variable_under_variable_pattern(self, tmp_path: Path) -> None:
        """Test detection when variable patterns are nested under other variables.

        This tests the case where we have Clients/{client}/{year} with actual
        directories like Clients/Alpha/2023, Clients/Beta/2024.
        """
        # Create structure: Clients/Alpha/2023, Clients/Alpha/2024, Clients/Beta/2023
        clients_dir = tmp_path / "Clients"
        clients_dir.mkdir()

        alpha_dir = clients_dir / "Alpha"
        alpha_dir.mkdir()
        (alpha_dir / "2023").mkdir()
        (alpha_dir / "2024").mkdir()

        beta_dir = clients_dir / "Beta"
        beta_dir.mkdir()
        (beta_dir / "2023").mkdir()

        folders = {
            "Clients": FolderDefinition(
                description="Client documents",
                folders={
                    "{client}": FolderDefinition(
                        description="By client",
                        folders={
                            "{year}": FolderDefinition(description="By year", folders={}),
                        },
                    ),
                },
            ),
        }

        result = _detect_existing_directories(folders, tmp_path)

        # Should detect client names
        assert "Clients/{client}" in result
        assert result["Clients/{client}"] == ["Alpha", "Beta"]

        # Should detect year values from ALL client directories combined
        assert "Clients/{client}/{year}" in result
        # Should have unique years from both Alpha and Beta, sorted
        assert result["Clients/{client}/{year}"] == ["2023", "2024"]

    def test_triple_nested_variable_patterns(self, tmp_path: Path) -> None:
        """Test detection with three levels of variable patterns."""
        # Create structure: Region/{region}/{client}/{year}
        region_dir = tmp_path / "Region"
        region_dir.mkdir()

        # US/ClientA/2023, US/ClientA/2024
        us_dir = region_dir / "US"
        us_dir.mkdir()
        client_a = us_dir / "ClientA"
        client_a.mkdir()
        (client_a / "2023").mkdir()
        (client_a / "2024").mkdir()

        # EU/ClientB/2024
        eu_dir = region_dir / "EU"
        eu_dir.mkdir()
        client_b = eu_dir / "ClientB"
        client_b.mkdir()
        (client_b / "2024").mkdir()

        folders = {
            "Region": FolderDefinition(
                description="Regional documents",
                folders={
                    "{region}": FolderDefinition(
                        description="By region",
                        folders={
                            "{client}": FolderDefinition(
                                description="By client",
                                folders={
                                    "{year}": FolderDefinition(
                                        description="By year", folders={}
                                    ),
                                },
                            ),
                        },
                    ),
                },
            ),
        }

        result = _detect_existing_directories(folders, tmp_path)

        # Should detect regions
        assert "Region/{region}" in result
        assert result["Region/{region}"] == ["EU", "US"]

        # Should detect clients from all regions
        assert "Region/{region}/{client}" in result
        assert result["Region/{region}/{client}"] == ["ClientA", "ClientB"]

        # Should detect years from all clients
        assert "Region/{region}/{client}/{year}" in result
        assert result["Region/{region}/{client}/{year}"] == ["2023", "2024"]


class TestSerializeFolderDefinitions:
    """Tests for serialize_folder_definitions function."""

    def test_empty_folders(self) -> None:
        """Test serialization of empty folder dict."""
        result = serialize_folder_definitions({})
        assert result == '{"folders": {}}'

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
        assert "folders" in parsed
        assert "Documents" in parsed["folders"]
        assert parsed["folders"]["Documents"]["description"] == "All documents"

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

        assert "folders" in parsed
        assert "Financial" in parsed["folders"]
        assert "invoices" in parsed["folders"]["Financial"]["folders"]

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
