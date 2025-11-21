"""Unit tests for path alignment validation."""

import pytest

from docman.path_alignment import (
    _check_value_against_pattern,
    _extract_variable_name,
    _is_variable_pattern,
    check_path_alignment,
)
from docman.repo_config import FolderDefinition, PatternValue, VariablePattern


class TestIsVariablePattern:
    """Tests for _is_variable_pattern helper function."""

    def test_variable_pattern(self):
        """Variable patterns are correctly identified."""
        assert _is_variable_pattern("{year}") is True
        assert _is_variable_pattern("{category}") is True
        assert _is_variable_pattern("{company}") is True

    def test_literal_folder(self):
        """Literal folder names are not variable patterns."""
        assert _is_variable_pattern("Financial") is False
        assert _is_variable_pattern("invoices") is False
        assert _is_variable_pattern("2024") is False

    def test_partial_braces(self):
        """Partial braces are not variable patterns."""
        assert _is_variable_pattern("{year") is False
        assert _is_variable_pattern("year}") is False
        assert _is_variable_pattern("year") is False


class TestExtractVariableName:
    """Tests for _extract_variable_name helper function."""

    def test_extract_name(self):
        """Variable names are correctly extracted."""
        assert _extract_variable_name("{year}") == "year"
        assert _extract_variable_name("{category}") == "category"
        assert _extract_variable_name("{company_name}") == "company_name"


class TestCheckValueAgainstPattern:
    """Tests for _check_value_against_pattern helper function."""

    def test_pattern_not_defined(self):
        """Returns valid when pattern is not defined (can't validate)."""
        var_patterns: dict[str, VariablePattern] = {}
        is_valid, warning = _check_value_against_pattern("2024", "year", var_patterns)
        assert is_valid is True
        assert warning is None

    def test_pattern_without_values(self):
        """Returns valid when pattern has no predefined values (can't validate)."""
        var_patterns = {
            "year": VariablePattern(description="4-digit year")
        }
        is_valid, warning = _check_value_against_pattern("2024", "year", var_patterns)
        assert is_valid is True
        assert warning is None

    def test_value_matches_predefined(self):
        """Returns valid when value matches predefined value."""
        var_patterns = {
            "year": VariablePattern(
                description="4-digit year",
                values=[
                    PatternValue(value="2024"),
                    PatternValue(value="2023"),
                ]
            )
        }
        is_valid, warning = _check_value_against_pattern("2024", "year", var_patterns)
        assert is_valid is True
        assert warning is None

    def test_value_matches_alias(self):
        """Returns valid when value matches an alias."""
        var_patterns = {
            "company": VariablePattern(
                description="Company name",
                values=[
                    PatternValue(
                        value="Acme Corp.",
                        aliases=["Acme", "ACME Corporation"]
                    ),
                ]
            )
        }
        is_valid, warning = _check_value_against_pattern("Acme", "company", var_patterns)
        assert is_valid is True
        assert warning is None

    def test_value_not_in_predefined(self):
        """Returns warning when value is not in predefined list."""
        var_patterns = {
            "year": VariablePattern(
                description="4-digit year",
                values=[
                    PatternValue(value="2024"),
                    PatternValue(value="2023"),
                ]
            )
        }
        is_valid, warning = _check_value_against_pattern("2099", "year", var_patterns)
        assert is_valid is False
        assert warning is not None
        assert '"2099" is not a known value for {year}' in warning


class TestCheckPathAlignment:
    """Tests for check_path_alignment main function."""

    def test_no_folder_definitions(self):
        """Returns aligned when no folder definitions exist."""
        folder_defs: dict[str, FolderDefinition] = {}
        var_patterns: dict[str, VariablePattern] = {}

        is_aligned, warning = check_path_alignment(
            "Financial/invoices/2024", folder_defs, var_patterns
        )
        assert is_aligned is True
        assert warning is None

    def test_empty_path(self):
        """Returns aligned for empty path (root level)."""
        folder_defs = {
            "Financial": FolderDefinition(description="Financial docs")
        }
        var_patterns: dict[str, VariablePattern] = {}

        is_aligned, warning = check_path_alignment("", folder_defs, var_patterns)
        assert is_aligned is True
        assert warning is None

        is_aligned, warning = check_path_alignment("  ", folder_defs, var_patterns)
        assert is_aligned is True
        assert warning is None

    def test_exact_match_single_level(self):
        """Path matches single-level literal folder."""
        folder_defs = {
            "Financial": FolderDefinition(description="Financial docs"),
            "Personal": FolderDefinition(description="Personal docs"),
        }
        var_patterns: dict[str, VariablePattern] = {}

        is_aligned, warning = check_path_alignment(
            "Financial", folder_defs, var_patterns
        )
        assert is_aligned is True
        assert warning is None

    def test_exact_match_nested(self):
        """Path matches nested literal folders."""
        folder_defs = {
            "Financial": FolderDefinition(
                description="Financial docs",
                folders={
                    "invoices": FolderDefinition(description="Invoices"),
                    "receipts": FolderDefinition(description="Receipts"),
                }
            )
        }
        var_patterns: dict[str, VariablePattern] = {}

        is_aligned, warning = check_path_alignment(
            "Financial/invoices", folder_defs, var_patterns
        )
        assert is_aligned is True
        assert warning is None

    def test_variable_pattern_match(self):
        """Path matches variable pattern placeholder."""
        folder_defs = {
            "Financial": FolderDefinition(
                description="Financial docs",
                folders={
                    "invoices": FolderDefinition(
                        description="Invoices",
                        folders={
                            "{year}": FolderDefinition(description="Invoices by year")
                        }
                    )
                }
            )
        }
        var_patterns: dict[str, VariablePattern] = {}

        # Any value matches when pattern has no predefined values
        is_aligned, warning = check_path_alignment(
            "Financial/invoices/2024", folder_defs, var_patterns
        )
        # Pattern without values is treated as valid (can't validate)
        assert is_aligned is True
        assert warning is None

    def test_variable_pattern_with_valid_value(self):
        """Path matches variable pattern with valid predefined value."""
        folder_defs = {
            "Financial": FolderDefinition(
                description="Financial docs",
                folders={
                    "invoices": FolderDefinition(
                        description="Invoices",
                        folders={
                            "{year}": FolderDefinition(description="Invoices by year")
                        }
                    )
                }
            )
        }
        var_patterns = {
            "year": VariablePattern(
                description="4-digit year",
                values=[
                    PatternValue(value="2024"),
                    PatternValue(value="2023"),
                ]
            )
        }

        is_aligned, warning = check_path_alignment(
            "Financial/invoices/2024", folder_defs, var_patterns
        )
        assert is_aligned is True
        assert warning is None

    def test_variable_pattern_with_invalid_value(self):
        """Returns warning when value doesn't match predefined list."""
        folder_defs = {
            "Financial": FolderDefinition(
                description="Financial docs",
                folders={
                    "invoices": FolderDefinition(
                        description="Invoices",
                        folders={
                            "{year}": FolderDefinition(description="Invoices by year")
                        }
                    )
                }
            )
        }
        var_patterns = {
            "year": VariablePattern(
                description="4-digit year",
                values=[
                    PatternValue(value="2024"),
                    PatternValue(value="2023"),
                ]
            )
        }

        is_aligned, warning = check_path_alignment(
            "Financial/invoices/2099", folder_defs, var_patterns
        )
        assert is_aligned is False
        assert warning is not None
        assert '"2099" is not a known value for {year}' in warning

    def test_folder_not_defined(self):
        """Returns warning when folder is not defined."""
        folder_defs = {
            "Financial": FolderDefinition(description="Financial docs")
        }
        var_patterns: dict[str, VariablePattern] = {}

        is_aligned, warning = check_path_alignment(
            "Unknown", folder_defs, var_patterns
        )
        assert is_aligned is False
        assert warning is not None
        assert '"Unknown" is not a defined folder' in warning

    def test_nested_folder_not_defined(self):
        """Returns warning when nested folder is not defined."""
        folder_defs = {
            "Financial": FolderDefinition(
                description="Financial docs",
                folders={
                    "invoices": FolderDefinition(description="Invoices")
                }
            )
        }
        var_patterns: dict[str, VariablePattern] = {}

        is_aligned, warning = check_path_alignment(
            "Financial/unknown", folder_defs, var_patterns
        )
        assert is_aligned is False
        assert warning is not None
        assert '"unknown" is not a defined folder under "Financial"' in warning

    def test_path_deeper_than_definition(self):
        """Path extends beyond defined hierarchy - this is allowed."""
        folder_defs = {
            "Financial": FolderDefinition(description="Financial docs")
        }
        var_patterns: dict[str, VariablePattern] = {}

        # Path goes deeper than definition - should be allowed (shallow paths are valid)
        is_aligned, warning = check_path_alignment(
            "Financial/invoices/2024", folder_defs, var_patterns
        )
        assert is_aligned is True
        assert warning is None

    def test_path_with_slashes(self):
        """Handles paths with leading/trailing slashes."""
        folder_defs = {
            "Financial": FolderDefinition(description="Financial docs")
        }
        var_patterns: dict[str, VariablePattern] = {}

        # Leading/trailing slashes should be handled
        is_aligned, warning = check_path_alignment(
            "/Financial/", folder_defs, var_patterns
        )
        assert is_aligned is True
        assert warning is None

    def test_path_with_spaces(self):
        """Handles path components with spaces."""
        folder_defs = {
            "Financial": FolderDefinition(
                description="Financial docs",
                folders={
                    " invoices ": FolderDefinition(description="Invoices with spaces")
                }
            )
        }
        var_patterns: dict[str, VariablePattern] = {}

        # Spaces in path components are stripped
        is_aligned, warning = check_path_alignment(
            "Financial/invoices", folder_defs, var_patterns
        )
        # This won't match because the folder is literally " invoices " with spaces
        assert is_aligned is False

    def test_multiple_variable_patterns_at_same_level(self):
        """Tests behavior when multiple components need matching."""
        folder_defs = {
            "Archive": FolderDefinition(
                description="Archives",
                folders={
                    "{year}": FolderDefinition(
                        description="Year",
                        folders={
                            "{month}": FolderDefinition(description="Month")
                        }
                    )
                }
            )
        }
        var_patterns = {
            "year": VariablePattern(
                description="4-digit year",
                values=[PatternValue(value="2024")]
            ),
            "month": VariablePattern(
                description="2-digit month",
                values=[PatternValue(value="01"), PatternValue(value="12")]
            )
        }

        # Valid year and month
        is_aligned, warning = check_path_alignment(
            "Archive/2024/01", folder_defs, var_patterns
        )
        assert is_aligned is True
        assert warning is None

        # Invalid month
        is_aligned, warning = check_path_alignment(
            "Archive/2024/13", folder_defs, var_patterns
        )
        assert is_aligned is False
        assert "13" in warning

    def test_alias_in_variable_pattern(self):
        """Tests that aliases are recognized as valid values."""
        folder_defs = {
            "Companies": FolderDefinition(
                description="Company documents",
                folders={
                    "{company}": FolderDefinition(description="Company folder")
                }
            )
        }
        var_patterns = {
            "company": VariablePattern(
                description="Company name",
                values=[
                    PatternValue(
                        value="Acme Corp.",
                        aliases=["Acme", "ACME"]
                    )
                ]
            )
        }

        # Canonical value
        is_aligned, warning = check_path_alignment(
            "Companies/Acme Corp.", folder_defs, var_patterns
        )
        assert is_aligned is True
        assert warning is None

        # Alias value
        is_aligned, warning = check_path_alignment(
            "Companies/Acme", folder_defs, var_patterns
        )
        assert is_aligned is True
        assert warning is None

    def test_mixed_literal_and_variable(self):
        """Tests path with both literal folders and variable patterns."""
        folder_defs = {
            "Documents": FolderDefinition(
                description="All documents",
                folders={
                    "Financial": FolderDefinition(
                        description="Financial",
                        folders={
                            "{year}": FolderDefinition(description="By year")
                        }
                    )
                }
            )
        }
        var_patterns = {
            "year": VariablePattern(
                description="Year",
                values=[PatternValue(value="2024")]
            )
        }

        is_aligned, warning = check_path_alignment(
            "Documents/Financial/2024", folder_defs, var_patterns
        )
        assert is_aligned is True
        assert warning is None
