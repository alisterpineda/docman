"""Unit tests for variable pattern management in repo_config module."""

from pathlib import Path

import pytest

from docman.repo_config import (
    get_variable_patterns,
    remove_variable_pattern,
    set_variable_pattern,
)


@pytest.mark.unit
class TestGetVariablePatterns:
    """Tests for get_variable_patterns function."""

    def test_no_patterns_defined(self, tmp_path: Path) -> None:
        """Test when no variable patterns are defined."""
        result = get_variable_patterns(tmp_path)
        assert result == {}

    def test_patterns_defined(self, tmp_path: Path) -> None:
        """Test when variable patterns are defined."""
        # Set up config with patterns
        set_variable_pattern(tmp_path, "year", "4-digit year in YYYY format")
        set_variable_pattern(tmp_path, "category", "Document category")

        result = get_variable_patterns(tmp_path)
        assert result == {
            "year": "4-digit year in YYYY format",
            "category": "Document category",
        }

    def test_empty_config_file(self, tmp_path: Path) -> None:
        """Test when config file exists but is empty."""
        config_path = tmp_path / ".docman" / "config.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("")

        result = get_variable_patterns(tmp_path)
        assert result == {}


@pytest.mark.unit
class TestSetVariablePattern:
    """Tests for set_variable_pattern function."""

    def test_creates_config_if_not_exists(self, tmp_path: Path) -> None:
        """Test that config directory and file are created if they don't exist."""
        set_variable_pattern(tmp_path, "year", "4-digit year")

        config_path = tmp_path / ".docman" / "config.yaml"
        assert config_path.exists()
        assert config_path.parent.exists()

    def test_adds_new_pattern(self, tmp_path: Path) -> None:
        """Test adding a new variable pattern."""
        set_variable_pattern(tmp_path, "year", "4-digit year in YYYY format")

        patterns = get_variable_patterns(tmp_path)
        assert "year" in patterns
        assert patterns["year"] == "4-digit year in YYYY format"

    def test_updates_existing_pattern(self, tmp_path: Path) -> None:
        """Test updating an existing variable pattern."""
        set_variable_pattern(tmp_path, "year", "4-digit year")
        set_variable_pattern(tmp_path, "year", "4-digit year in YYYY format")

        patterns = get_variable_patterns(tmp_path)
        assert patterns["year"] == "4-digit year in YYYY format"

    def test_multiple_patterns(self, tmp_path: Path) -> None:
        """Test adding multiple variable patterns."""
        set_variable_pattern(tmp_path, "year", "4-digit year")
        set_variable_pattern(tmp_path, "month", "2-digit month")
        set_variable_pattern(tmp_path, "category", "Document category")

        patterns = get_variable_patterns(tmp_path)
        assert len(patterns) == 3
        assert patterns["year"] == "4-digit year"
        assert patterns["month"] == "2-digit month"
        assert patterns["category"] == "Document category"

    def test_strips_whitespace(self, tmp_path: Path) -> None:
        """Test that leading/trailing whitespace is stripped."""
        set_variable_pattern(tmp_path, "  year  ", "  4-digit year  ")

        patterns = get_variable_patterns(tmp_path)
        assert "year" in patterns
        assert patterns["year"] == "4-digit year"

    @pytest.mark.parametrize("empty_value", ["", "   "])
    def test_empty_name_raises_error(self, tmp_path: Path, empty_value: str) -> None:
        """Test that empty variable name raises ValueError."""
        with pytest.raises(ValueError, match="Variable name cannot be empty"):
            set_variable_pattern(tmp_path, empty_value, "Description")

    @pytest.mark.parametrize("empty_value", ["", "   "])
    def test_empty_description_raises_error(self, tmp_path: Path, empty_value: str) -> None:
        """Test that empty description raises ValueError."""
        with pytest.raises(ValueError, match="Variable description cannot be empty"):
            set_variable_pattern(tmp_path, "year", empty_value)


@pytest.mark.unit
class TestRemoveVariablePattern:
    """Tests for remove_variable_pattern function."""

    def test_removes_existing_pattern(self, tmp_path: Path) -> None:
        """Test removing an existing variable pattern."""
        set_variable_pattern(tmp_path, "year", "4-digit year")
        set_variable_pattern(tmp_path, "month", "2-digit month")

        remove_variable_pattern(tmp_path, "year")

        patterns = get_variable_patterns(tmp_path)
        assert "year" not in patterns
        assert "month" in patterns

    def test_pattern_not_found_raises_error(self, tmp_path: Path) -> None:
        """Test that removing non-existent pattern raises ValueError."""
        with pytest.raises(ValueError, match="Variable pattern 'year' not found"):
            remove_variable_pattern(tmp_path, "year")

    @pytest.mark.parametrize("empty_value", ["", "   "])
    def test_empty_name_raises_error(self, tmp_path: Path, empty_value: str) -> None:
        """Test that empty variable name raises ValueError."""
        with pytest.raises(ValueError, match="Variable name cannot be empty"):
            remove_variable_pattern(tmp_path, empty_value)

    def test_removes_from_existing_config(self, tmp_path: Path) -> None:
        """Test removing pattern from config with other data."""
        # Set up config with folder definitions and patterns
        set_variable_pattern(tmp_path, "year", "4-digit year")
        set_variable_pattern(tmp_path, "month", "2-digit month")

        # Add some other config data (like folder definitions)
        from docman.repo_config import add_folder_definition

        add_folder_definition(tmp_path, "Financial", "Financial documents")

        # Remove pattern
        remove_variable_pattern(tmp_path, "year")

        # Verify pattern removed but other data preserved
        patterns = get_variable_patterns(tmp_path)
        assert "year" not in patterns
        assert "month" in patterns

        from docman.repo_config import get_folder_definitions

        folders = get_folder_definitions(tmp_path)
        assert "Financial" in folders


@pytest.mark.unit
class TestVariablePatternYAMLSerialization:
    """Tests for YAML serialization of variable patterns."""

    def test_patterns_stored_in_correct_location(self, tmp_path: Path) -> None:
        """Test that patterns are stored in organization.variable_patterns."""
        set_variable_pattern(tmp_path, "year", "4-digit year")

        config_path = tmp_path / ".docman" / "config.yaml"
        content = config_path.read_text()

        assert "organization:" in content
        assert "variable_patterns:" in content
        assert "year:" in content

    def test_yaml_format_is_readable(self, tmp_path: Path) -> None:
        """Test that generated YAML is human-readable."""
        set_variable_pattern(tmp_path, "year", "4-digit year in YYYY format")
        set_variable_pattern(tmp_path, "category", "Document category")

        config_path = tmp_path / ".docman" / "config.yaml"
        content = config_path.read_text()

        # Should be in dictionary format, not flow style
        assert "variable_patterns:" in content
        assert "  year:" in content or "  category:" in content
        assert "4-digit year in YYYY format" in content
        assert "Document category" in content
