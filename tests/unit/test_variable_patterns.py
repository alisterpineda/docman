"""Unit tests for variable pattern management in repo_config module."""

from pathlib import Path

import pytest

from docman.repo_config import (
    PatternValue,
    VariablePattern,
    add_pattern_value,
    get_pattern_values,
    get_variable_pattern_descriptions,
    get_variable_patterns,
    remove_pattern_value,
    remove_variable_pattern,
    set_variable_pattern,
)


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
        assert "year" in result
        assert "category" in result
        assert result["year"].description == "4-digit year in YYYY format"
        assert result["category"].description == "Document category"

    def test_empty_config_file(self, tmp_path: Path) -> None:
        """Test when config file exists but is empty."""
        config_path = tmp_path / ".docman" / "config.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("")

        result = get_variable_patterns(tmp_path)
        assert result == {}

    def test_returns_variable_pattern_objects(self, tmp_path: Path) -> None:
        """Test that get_variable_patterns returns VariablePattern objects."""
        set_variable_pattern(tmp_path, "year", "4-digit year")

        result = get_variable_patterns(tmp_path)
        assert isinstance(result["year"], VariablePattern)
        assert result["year"].description == "4-digit year"
        assert result["year"].values == []


class TestGetVariablePatternDescriptions:
    """Tests for get_variable_pattern_descriptions backward compatibility function."""

    def test_returns_string_descriptions(self, tmp_path: Path) -> None:
        """Test that function returns simple dict[str, str]."""
        set_variable_pattern(tmp_path, "year", "4-digit year in YYYY format")
        set_variable_pattern(tmp_path, "category", "Document category")

        result = get_variable_pattern_descriptions(tmp_path)
        assert result == {
            "year": "4-digit year in YYYY format",
            "category": "Document category",
        }

    def test_empty_patterns(self, tmp_path: Path) -> None:
        """Test with no patterns defined."""
        result = get_variable_pattern_descriptions(tmp_path)
        assert result == {}


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
        assert patterns["year"].description == "4-digit year in YYYY format"

    def test_updates_existing_pattern(self, tmp_path: Path) -> None:
        """Test updating an existing variable pattern."""
        set_variable_pattern(tmp_path, "year", "4-digit year")
        set_variable_pattern(tmp_path, "year", "4-digit year in YYYY format")

        patterns = get_variable_patterns(tmp_path)
        assert patterns["year"].description == "4-digit year in YYYY format"

    def test_multiple_patterns(self, tmp_path: Path) -> None:
        """Test adding multiple variable patterns."""
        set_variable_pattern(tmp_path, "year", "4-digit year")
        set_variable_pattern(tmp_path, "month", "2-digit month")
        set_variable_pattern(tmp_path, "category", "Document category")

        patterns = get_variable_patterns(tmp_path)
        assert len(patterns) == 3
        assert patterns["year"].description == "4-digit year"
        assert patterns["month"].description == "2-digit month"
        assert patterns["category"].description == "Document category"

    def test_strips_whitespace(self, tmp_path: Path) -> None:
        """Test that leading/trailing whitespace is stripped."""
        set_variable_pattern(tmp_path, "  year  ", "  4-digit year  ")

        patterns = get_variable_patterns(tmp_path)
        assert "year" in patterns
        assert patterns["year"].description == "4-digit year"

    def test_preserves_values_when_updating_description(self, tmp_path: Path) -> None:
        """Test that updating description preserves existing values."""
        set_variable_pattern(tmp_path, "company", "Company name")
        add_pattern_value(tmp_path, "company", "Acme Corp.", "Main company")

        # Update description
        set_variable_pattern(tmp_path, "company", "Updated company description")

        patterns = get_variable_patterns(tmp_path)
        assert patterns["company"].description == "Updated company description"
        assert len(patterns["company"].values) == 1
        assert patterns["company"].values[0].value == "Acme Corp."

    def test_empty_name_raises_error(self, tmp_path: Path) -> None:
        """Test that empty variable name raises ValueError."""
        with pytest.raises(ValueError, match="Variable name cannot be empty"):
            set_variable_pattern(tmp_path, "", "Description")

        with pytest.raises(ValueError, match="Variable name cannot be empty"):
            set_variable_pattern(tmp_path, "   ", "Description")

    def test_empty_description_raises_error(self, tmp_path: Path) -> None:
        """Test that empty description raises ValueError."""
        with pytest.raises(ValueError, match="Variable description cannot be empty"):
            set_variable_pattern(tmp_path, "year", "")

        with pytest.raises(ValueError, match="Variable description cannot be empty"):
            set_variable_pattern(tmp_path, "year", "   ")


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

    def test_empty_name_raises_error(self, tmp_path: Path) -> None:
        """Test that empty variable name raises ValueError."""
        with pytest.raises(ValueError, match="Variable name cannot be empty"):
            remove_variable_pattern(tmp_path, "")

        with pytest.raises(ValueError, match="Variable name cannot be empty"):
            remove_variable_pattern(tmp_path, "   ")

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


class TestPatternValueDataclass:
    """Tests for PatternValue dataclass."""

    def test_to_dict_simple(self) -> None:
        """Test to_dict with simple value."""
        pv = PatternValue(value="Acme Corp.")
        result = pv.to_dict()
        assert result == {"value": "Acme Corp."}

    def test_to_dict_with_description(self) -> None:
        """Test to_dict with description."""
        pv = PatternValue(value="Acme Corp.", description="Main company")
        result = pv.to_dict()
        assert result == {"value": "Acme Corp.", "description": "Main company"}

    def test_to_dict_with_aliases(self) -> None:
        """Test to_dict with aliases."""
        pv = PatternValue(value="Acme Corp.", aliases=["XYZ Corp", "XYZ Corporation"])
        result = pv.to_dict()
        assert result == {
            "value": "Acme Corp.",
            "aliases": ["XYZ Corp", "XYZ Corporation"],
        }

    def test_from_dict_simple(self) -> None:
        """Test from_dict with simple value."""
        data = {"value": "Acme Corp."}
        pv = PatternValue.from_dict(data)
        assert pv.value == "Acme Corp."
        assert pv.description is None
        assert pv.aliases == []

    def test_from_dict_full(self) -> None:
        """Test from_dict with all fields."""
        data = {
            "value": "Acme Corp.",
            "description": "Main company",
            "aliases": ["XYZ Corp"],
        }
        pv = PatternValue.from_dict(data)
        assert pv.value == "Acme Corp."
        assert pv.description == "Main company"
        assert pv.aliases == ["XYZ Corp"]


class TestVariablePatternDataclass:
    """Tests for VariablePattern dataclass."""

    def test_to_dict_simple_format(self) -> None:
        """Test to_dict returns string for simple patterns (no values)."""
        vp = VariablePattern(description="4-digit year")
        result = vp.to_dict()
        assert result == "4-digit year"

    def test_to_dict_extended_format(self) -> None:
        """Test to_dict returns dict for patterns with values."""
        vp = VariablePattern(
            description="Company name",
            values=[PatternValue(value="Acme Corp.")]
        )
        result = vp.to_dict()
        assert result == {
            "description": "Company name",
            "values": [{"value": "Acme Corp."}],
        }

    def test_from_dict_string_format(self) -> None:
        """Test from_dict with simple string format."""
        vp = VariablePattern.from_dict("4-digit year")
        assert vp.description == "4-digit year"
        assert vp.values == []

    def test_from_dict_extended_format(self) -> None:
        """Test from_dict with extended dict format."""
        data = {
            "description": "Company name",
            "values": [{"value": "Acme Corp.", "description": "Main company"}],
        }
        vp = VariablePattern.from_dict(data)
        assert vp.description == "Company name"
        assert len(vp.values) == 1
        assert vp.values[0].value == "Acme Corp."
        assert vp.values[0].description == "Main company"


class TestAddPatternValue:
    """Tests for add_pattern_value function."""

    def test_adds_value_to_pattern(self, tmp_path: Path) -> None:
        """Test adding a value to an existing pattern."""
        set_variable_pattern(tmp_path, "company", "Company name")
        add_pattern_value(tmp_path, "company", "Acme Corp.")

        values = get_pattern_values(tmp_path, "company")
        assert len(values) == 1
        assert values[0].value == "Acme Corp."

    def test_adds_value_with_description(self, tmp_path: Path) -> None:
        """Test adding a value with description."""
        set_variable_pattern(tmp_path, "company", "Company name")
        add_pattern_value(tmp_path, "company", "Acme Corp.", "Main company")

        values = get_pattern_values(tmp_path, "company")
        assert values[0].description == "Main company"

    def test_adds_alias_to_existing_value(self, tmp_path: Path) -> None:
        """Test adding an alias to an existing value."""
        set_variable_pattern(tmp_path, "company", "Company name")
        add_pattern_value(tmp_path, "company", "Acme Corp.", "Main company")
        add_pattern_value(tmp_path, "company", "XYZ Corp", alias_of="Acme Corp.")

        values = get_pattern_values(tmp_path, "company")
        assert len(values) == 1
        assert "XYZ Corp" in values[0].aliases

    def test_adds_multiple_aliases(self, tmp_path: Path) -> None:
        """Test adding multiple aliases to a value."""
        set_variable_pattern(tmp_path, "company", "Company name")
        add_pattern_value(tmp_path, "company", "Acme Corp.")
        add_pattern_value(tmp_path, "company", "XYZ Corp", alias_of="Acme Corp.")
        add_pattern_value(tmp_path, "company", "XYZ Corporation", alias_of="Acme Corp.")

        values = get_pattern_values(tmp_path, "company")
        assert len(values[0].aliases) == 2
        assert "XYZ Corp" in values[0].aliases
        assert "XYZ Corporation" in values[0].aliases

    def test_pattern_not_found_raises_error(self, tmp_path: Path) -> None:
        """Test that adding to non-existent pattern raises error."""
        with pytest.raises(ValueError, match="Variable pattern 'company' not found"):
            add_pattern_value(tmp_path, "company", "Acme Corp.")

    def test_duplicate_value_raises_error(self, tmp_path: Path) -> None:
        """Test that adding duplicate value raises error."""
        set_variable_pattern(tmp_path, "company", "Company name")
        add_pattern_value(tmp_path, "company", "Acme Corp.")

        with pytest.raises(ValueError, match="already exists"):
            add_pattern_value(tmp_path, "company", "Acme Corp.")

    def test_duplicate_alias_raises_error(self, tmp_path: Path) -> None:
        """Test that adding value that's already an alias raises error."""
        set_variable_pattern(tmp_path, "company", "Company name")
        add_pattern_value(tmp_path, "company", "Acme Corp.")
        add_pattern_value(tmp_path, "company", "XYZ Corp", alias_of="Acme Corp.")

        with pytest.raises(ValueError, match="already exists as an alias"):
            add_pattern_value(tmp_path, "company", "XYZ Corp")

    def test_alias_of_not_found_raises_error(self, tmp_path: Path) -> None:
        """Test that adding alias of non-existent value raises error."""
        set_variable_pattern(tmp_path, "company", "Company name")

        with pytest.raises(ValueError, match="Canonical value 'Acme Corp.' not found"):
            add_pattern_value(tmp_path, "company", "XYZ Corp", alias_of="Acme Corp.")

    def test_empty_value_raises_error(self, tmp_path: Path) -> None:
        """Test that empty value raises error."""
        set_variable_pattern(tmp_path, "company", "Company name")

        with pytest.raises(ValueError, match="Value cannot be empty"):
            add_pattern_value(tmp_path, "company", "")


class TestRemovePatternValue:
    """Tests for remove_pattern_value function."""

    def test_removes_canonical_value(self, tmp_path: Path) -> None:
        """Test removing a canonical value (and its aliases)."""
        set_variable_pattern(tmp_path, "company", "Company name")
        add_pattern_value(tmp_path, "company", "Acme Corp.")
        add_pattern_value(tmp_path, "company", "XYZ Corp", alias_of="Acme Corp.")

        remove_pattern_value(tmp_path, "company", "Acme Corp.")

        values = get_pattern_values(tmp_path, "company")
        assert len(values) == 0

    def test_removes_only_alias(self, tmp_path: Path) -> None:
        """Test removing only an alias (keeps canonical value)."""
        set_variable_pattern(tmp_path, "company", "Company name")
        add_pattern_value(tmp_path, "company", "Acme Corp.")
        add_pattern_value(tmp_path, "company", "XYZ Corp", alias_of="Acme Corp.")
        add_pattern_value(tmp_path, "company", "XYZ Corporation", alias_of="Acme Corp.")

        remove_pattern_value(tmp_path, "company", "XYZ Corp")

        values = get_pattern_values(tmp_path, "company")
        assert len(values) == 1
        assert values[0].value == "Acme Corp."
        assert "XYZ Corp" not in values[0].aliases
        assert "XYZ Corporation" in values[0].aliases

    def test_reverts_to_simple_format_when_empty(self, tmp_path: Path) -> None:
        """Test that pattern reverts to simple format when all values removed."""
        set_variable_pattern(tmp_path, "company", "Company name")
        add_pattern_value(tmp_path, "company", "Acme Corp.")

        remove_pattern_value(tmp_path, "company", "Acme Corp.")

        # Verify still works and has no values
        values = get_pattern_values(tmp_path, "company")
        assert len(values) == 0

        # Pattern should still exist
        patterns = get_variable_patterns(tmp_path)
        assert "company" in patterns
        assert patterns["company"].description == "Company name"

    def test_value_not_found_raises_error(self, tmp_path: Path) -> None:
        """Test that removing non-existent value raises error."""
        set_variable_pattern(tmp_path, "company", "Company name")

        with pytest.raises(ValueError, match="Value 'Acme Corp.' not found"):
            remove_pattern_value(tmp_path, "company", "Acme Corp.")

    def test_pattern_not_found_raises_error(self, tmp_path: Path) -> None:
        """Test that removing from non-existent pattern raises error."""
        with pytest.raises(ValueError, match="Variable pattern 'company' not found"):
            remove_pattern_value(tmp_path, "company", "Acme Corp.")


class TestGetPatternValues:
    """Tests for get_pattern_values function."""

    def test_returns_empty_list_for_simple_pattern(self, tmp_path: Path) -> None:
        """Test that simple pattern returns empty list."""
        set_variable_pattern(tmp_path, "year", "4-digit year")

        values = get_pattern_values(tmp_path, "year")
        assert values == []

    def test_returns_values_list(self, tmp_path: Path) -> None:
        """Test that pattern with values returns list."""
        set_variable_pattern(tmp_path, "company", "Company name")
        add_pattern_value(tmp_path, "company", "Acme Corp.", "Main company")
        add_pattern_value(tmp_path, "company", "Beta Inc.")

        values = get_pattern_values(tmp_path, "company")
        assert len(values) == 2
        assert values[0].value == "Acme Corp."
        assert values[0].description == "Main company"
        assert values[1].value == "Beta Inc."

    def test_pattern_not_found_raises_error(self, tmp_path: Path) -> None:
        """Test that non-existent pattern raises error."""
        with pytest.raises(ValueError, match="Variable pattern 'company' not found"):
            get_pattern_values(tmp_path, "company")


class TestBackwardCompatibility:
    """Tests for backward compatibility with simple string format."""

    def test_loads_simple_string_format(self, tmp_path: Path) -> None:
        """Test that simple string format from YAML is loaded correctly."""
        # Manually write simple format
        from docman.repo_config import save_repo_config

        config = {
            "organization": {
                "variable_patterns": {
                    "year": "4-digit year in YYYY format",
                    "month": "2-digit month",
                }
            }
        }
        save_repo_config(tmp_path, config)

        # Load and verify
        patterns = get_variable_patterns(tmp_path)
        assert patterns["year"].description == "4-digit year in YYYY format"
        assert patterns["year"].values == []
        assert patterns["month"].description == "2-digit month"

    def test_loads_mixed_formats(self, tmp_path: Path) -> None:
        """Test that mixed simple and extended formats are loaded correctly."""
        from docman.repo_config import save_repo_config

        config = {
            "organization": {
                "variable_patterns": {
                    "year": "4-digit year",  # Simple format
                    "company": {  # Extended format
                        "description": "Company name",
                        "values": [
                            {"value": "Acme Corp.", "description": "Main company"},
                        ],
                    },
                }
            }
        }
        save_repo_config(tmp_path, config)

        # Load and verify
        patterns = get_variable_patterns(tmp_path)
        assert patterns["year"].description == "4-digit year"
        assert patterns["year"].values == []
        assert patterns["company"].description == "Company name"
        assert len(patterns["company"].values) == 1
        assert patterns["company"].values[0].value == "Acme Corp."

    def test_saves_simple_format_when_no_values(self, tmp_path: Path) -> None:
        """Test that simple format is used when pattern has no values."""
        set_variable_pattern(tmp_path, "year", "4-digit year")

        # Verify YAML format
        config_path = tmp_path / ".docman" / "config.yaml"
        content = config_path.read_text()

        # Should be simple format, not extended
        assert "year: 4-digit year" in content or "year: '4-digit year'" in content
        assert "values:" not in content
