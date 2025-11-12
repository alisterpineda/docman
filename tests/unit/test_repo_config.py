"""Unit tests for repo_config module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docman.repo_config import (
    FolderDefinition,
    add_folder_definition,
    edit_instructions_interactive,
    get_default_filename_convention,
    get_folder_definitions,
    get_instructions_path,
    get_repo_config_path,
    load_instructions,
    load_repo_config,
    save_instructions,
    save_repo_config,
    set_default_filename_convention,
)


class TestGetInstructionsPath:
    """Tests for get_instructions_path function."""

    def test_returns_correct_path(self, tmp_path: Path) -> None:
        """Test that function returns correct path."""
        result = get_instructions_path(tmp_path)
        expected = tmp_path / ".docman" / "instructions.md"
        assert result == expected


class TestLoadInstructions:
    """Tests for load_instructions function."""

    def test_file_does_not_exist(self, tmp_path: Path) -> None:
        """Test when instructions file doesn't exist."""
        result = load_instructions(tmp_path)
        assert result is None

    def test_empty_file(self, tmp_path: Path) -> None:
        """Test when instructions file is empty."""
        instructions_path = get_instructions_path(tmp_path)
        instructions_path.parent.mkdir(parents=True)
        instructions_path.write_text("")

        result = load_instructions(tmp_path)
        assert result is None

    def test_whitespace_only(self, tmp_path: Path) -> None:
        """Test when instructions file contains only whitespace."""
        instructions_path = get_instructions_path(tmp_path)
        instructions_path.parent.mkdir(parents=True)
        instructions_path.write_text("   \n\t  ")

        result = load_instructions(tmp_path)
        assert result is None

    def test_valid_content(self, tmp_path: Path) -> None:
        """Test when instructions file has valid content."""
        instructions_path = get_instructions_path(tmp_path)
        instructions_path.parent.mkdir(parents=True)
        content = "Test instructions"
        instructions_path.write_text(content)

        result = load_instructions(tmp_path)
        assert result == content

    def test_strips_whitespace(self, tmp_path: Path) -> None:
        """Test that leading/trailing whitespace is stripped."""
        instructions_path = get_instructions_path(tmp_path)
        instructions_path.parent.mkdir(parents=True)
        instructions_path.write_text("  Test instructions  \n")

        result = load_instructions(tmp_path)
        assert result == "Test instructions"


class TestSaveInstructions:
    """Tests for save_instructions function."""

    def test_creates_directory_if_not_exists(self, tmp_path: Path) -> None:
        """Test that .docman directory is created if it doesn't exist."""
        content = "Test instructions"
        save_instructions(tmp_path, content)

        instructions_path = get_instructions_path(tmp_path)
        assert instructions_path.parent.exists()
        assert instructions_path.parent.is_dir()

    def test_saves_content(self, tmp_path: Path) -> None:
        """Test that content is saved correctly."""
        content = "Test instructions"
        save_instructions(tmp_path, content)

        instructions_path = get_instructions_path(tmp_path)
        assert instructions_path.exists()
        assert instructions_path.read_text() == content

    def test_overwrites_existing_content(self, tmp_path: Path) -> None:
        """Test that existing content is overwritten."""
        instructions_path = get_instructions_path(tmp_path)
        instructions_path.parent.mkdir(parents=True)
        instructions_path.write_text("Old content")

        new_content = "New content"
        save_instructions(tmp_path, new_content)

        assert instructions_path.read_text() == new_content


class TestEditInstructionsInteractive:
    """Tests for edit_instructions_interactive function."""

    @patch("docman.repo_config.subprocess.run")
    @patch.dict("os.environ", {"EDITOR": "nano"})
    def test_uses_editor_from_environment(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Test that EDITOR environment variable is used."""
        mock_run.return_value = MagicMock(returncode=0)

        result = edit_instructions_interactive(tmp_path)

        assert result is True
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0][0] == "nano"

    @patch("docman.repo_config.subprocess.run")
    @patch.dict("os.environ", {}, clear=True)
    def test_falls_back_to_default_editor_unix(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Test fallback to default editor on Unix."""
        # Mock successful `which` command for nano
        def run_side_effect(cmd: list[str], **kwargs):  # type: ignore[no-untyped-def]
            if cmd[0] == "which":
                return MagicMock(returncode=0)
            return MagicMock(returncode=0)

        mock_run.side_effect = run_side_effect

        with patch("os.name", "posix"):
            result = edit_instructions_interactive(tmp_path)

        assert result is True

    @patch("docman.repo_config.subprocess.run")
    def test_creates_template_if_not_exists(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Test that template is created if instructions file doesn't exist."""
        mock_run.return_value = MagicMock(returncode=0)

        with patch.dict("os.environ", {"EDITOR": "nano"}):
            edit_instructions_interactive(tmp_path)

        instructions_path = get_instructions_path(tmp_path)
        assert instructions_path.exists()

        content = instructions_path.read_text()
        assert "Document Organization Instructions" in content
        assert "Examples:" in content

    @patch("docman.repo_config.subprocess.run")
    def test_does_not_overwrite_existing_file(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Test that existing instructions file is not overwritten."""
        instructions_path = get_instructions_path(tmp_path)
        instructions_path.parent.mkdir(parents=True)
        existing_content = "Existing instructions"
        instructions_path.write_text(existing_content)

        mock_run.return_value = MagicMock(returncode=0)

        with patch.dict("os.environ", {"EDITOR": "nano"}):
            edit_instructions_interactive(tmp_path)

        # Content should remain unchanged
        assert instructions_path.read_text() == existing_content

    @patch("docman.repo_config.subprocess.run")
    def test_returns_false_on_editor_failure(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Test that function returns False if editor fails."""
        mock_run.side_effect = FileNotFoundError()

        with patch.dict("os.environ", {"EDITOR": "nonexistent-editor"}):
            result = edit_instructions_interactive(tmp_path)

        assert result is False

    @patch("docman.repo_config.subprocess.run")
    @patch.dict("os.environ", {}, clear=True)
    def test_returns_false_when_no_editor_found(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Test that function returns False when no editor is found."""
        # Mock failed `which` commands for all editors
        mock_run.return_value = MagicMock(returncode=1)

        with patch("os.name", "posix"):
            result = edit_instructions_interactive(tmp_path)

        assert result is False


class TestFolderDefinition:
    """Tests for FolderDefinition dataclass."""

    def test_to_dict_simple(self) -> None:
        """Test to_dict with simple folder (no subfolders)."""
        folder = FolderDefinition(description="Test folder")
        result = folder.to_dict()

        assert result == {"description": "Test folder"}

    def test_to_dict_with_subfolders(self) -> None:
        """Test to_dict with nested subfolders."""
        subfolder = FolderDefinition(description="Subfolder")
        folder = FolderDefinition(description="Main folder", folders={"sub": subfolder})
        result = folder.to_dict()

        assert result == {
            "description": "Main folder",
            "folders": {"sub": {"description": "Subfolder"}},
        }

    def test_from_dict_simple(self) -> None:
        """Test from_dict with simple folder data."""
        data = {"description": "Test folder"}
        folder = FolderDefinition.from_dict(data)

        assert folder.description == "Test folder"
        assert folder.folders == {}

    def test_from_dict_with_subfolders(self) -> None:
        """Test from_dict with nested subfolders."""
        data = {
            "description": "Main folder",
            "folders": {"sub": {"description": "Subfolder"}},
        }
        folder = FolderDefinition.from_dict(data)

        assert folder.description == "Main folder"
        assert "sub" in folder.folders
        assert folder.folders["sub"].description == "Subfolder"

    def test_from_dict_missing_description(self) -> None:
        """Test from_dict with missing description (should default to empty)."""
        data: dict = {"folders": {}}
        folder = FolderDefinition.from_dict(data)

        assert folder.description == ""

    def test_from_dict_missing_folders(self) -> None:
        """Test from_dict with missing folders (should default to empty dict)."""
        data = {"description": "Test"}
        folder = FolderDefinition.from_dict(data)

        assert folder.folders == {}

    def test_to_dict_with_filename_convention(self) -> None:
        """Test to_dict with filename_convention field."""
        folder = FolderDefinition(
            description="Test folder",
            filename_convention="{year}-{month}-invoice"
        )
        result = folder.to_dict()

        assert result == {
            "description": "Test folder",
            "filename_convention": "{year}-{month}-invoice",
        }

    def test_to_dict_without_filename_convention(self) -> None:
        """Test to_dict without filename_convention (should not include field)."""
        folder = FolderDefinition(description="Test folder")
        result = folder.to_dict()

        assert result == {"description": "Test folder"}
        assert "filename_convention" not in result

    def test_from_dict_with_filename_convention(self) -> None:
        """Test from_dict with filename_convention field."""
        data = {
            "description": "Test folder",
            "filename_convention": "{company}-{date}",
        }
        folder = FolderDefinition.from_dict(data)

        assert folder.description == "Test folder"
        assert folder.filename_convention == "{company}-{date}"

    def test_from_dict_missing_filename_convention(self) -> None:
        """Test from_dict without filename_convention (should default to None)."""
        data = {"description": "Test folder"}
        folder = FolderDefinition.from_dict(data)

        assert folder.filename_convention is None

    def test_roundtrip_with_filename_convention(self) -> None:
        """Test serialization round-trip with filename_convention."""
        original = FolderDefinition(
            description="Financial",
            filename_convention="{year}-{month}-{description}",
            folders={
                "invoices": FolderDefinition(
                    description="Invoices",
                    filename_convention="{company}-invoice",
                )
            },
        )

        # Convert to dict and back
        data = original.to_dict()
        restored = FolderDefinition.from_dict(data)

        assert restored.description == original.description
        assert restored.filename_convention == original.filename_convention
        assert "invoices" in restored.folders
        assert restored.folders["invoices"].filename_convention == "{company}-invoice"


class TestGetRepoConfigPath:
    """Tests for get_repo_config_path function."""

    def test_returns_correct_path(self, tmp_path: Path) -> None:
        """Test that function returns correct path."""
        result = get_repo_config_path(tmp_path)
        expected = tmp_path / ".docman" / "config.yaml"
        assert result == expected


class TestLoadRepoConfig:
    """Tests for load_repo_config function."""

    def test_file_does_not_exist(self, tmp_path: Path) -> None:
        """Test when config file doesn't exist."""
        result = load_repo_config(tmp_path)
        assert result == {}

    def test_empty_file(self, tmp_path: Path) -> None:
        """Test when config file is empty."""
        config_path = get_repo_config_path(tmp_path)
        config_path.parent.mkdir(parents=True)
        config_path.write_text("")

        result = load_repo_config(tmp_path)
        assert result == {}

    def test_valid_yaml(self, tmp_path: Path) -> None:
        """Test when config file has valid YAML."""
        config_path = get_repo_config_path(tmp_path)
        config_path.parent.mkdir(parents=True)
        config_path.write_text("organization:\n  folders: {}")

        result = load_repo_config(tmp_path)
        assert result == {"organization": {"folders": {}}}

    def test_invalid_yaml_raises_error(self, tmp_path: Path) -> None:
        """Test when config file contains invalid YAML syntax."""
        config_path = get_repo_config_path(tmp_path)
        config_path.parent.mkdir(parents=True)
        # Invalid YAML: unbalanced brackets
        config_path.write_text("organization:\n  folders: {\n    invalid")

        with pytest.raises(ValueError) as exc_info:
            load_repo_config(tmp_path)

        assert "invalid YAML syntax" in str(exc_info.value)
        assert "config.yaml" in str(exc_info.value)

    def test_malformed_yaml_from_merge_conflict(self, tmp_path: Path) -> None:
        """Test when config file has merge conflict markers."""
        config_path = get_repo_config_path(tmp_path)
        config_path.parent.mkdir(parents=True)
        # Simulate merge conflict markers
        config_path.write_text(
            "organization:\n"
            "<<<<<<< HEAD\n"
            "  folders:\n"
            "    Financial:\n"
            "=======\n"
            "  folders:\n"
            "    Personal:\n"
            ">>>>>>> branch\n"
        )

        with pytest.raises(ValueError) as exc_info:
            load_repo_config(tmp_path)

        assert "invalid YAML syntax" in str(exc_info.value)


class TestSaveRepoConfig:
    """Tests for save_repo_config function."""

    def test_creates_directory_if_not_exists(self, tmp_path: Path) -> None:
        """Test that .docman directory is created if it doesn't exist."""
        config = {"test": "value"}
        save_repo_config(tmp_path, config)

        config_path = get_repo_config_path(tmp_path)
        assert config_path.parent.exists()
        assert config_path.parent.is_dir()

    def test_saves_config(self, tmp_path: Path) -> None:
        """Test that config is saved correctly."""
        config = {"organization": {"folders": {}}}
        save_repo_config(tmp_path, config)

        config_path = get_repo_config_path(tmp_path)
        assert config_path.exists()

        # Reload and verify
        loaded = load_repo_config(tmp_path)
        assert loaded == config


class TestGetFolderDefinitions:
    """Tests for get_folder_definitions function."""

    def test_empty_config(self, tmp_path: Path) -> None:
        """Test with empty config."""
        result = get_folder_definitions(tmp_path)
        assert result == {}

    def test_no_organization_key(self, tmp_path: Path) -> None:
        """Test with config but no organization key."""
        save_repo_config(tmp_path, {"other": "data"})
        result = get_folder_definitions(tmp_path)
        assert result == {}

    def test_with_folder_definitions(self, tmp_path: Path) -> None:
        """Test with folder definitions."""
        config = {
            "organization": {
                "folders": {
                    "Financial": {
                        "description": "Financial documents",
                        "folders": {
                            "invoices": {"description": "Customer invoices"}
                        },
                    }
                }
            }
        }
        save_repo_config(tmp_path, config)

        result = get_folder_definitions(tmp_path)

        assert "Financial" in result
        assert result["Financial"].description == "Financial documents"
        assert "invoices" in result["Financial"].folders
        assert result["Financial"].folders["invoices"].description == "Customer invoices"


class TestAddFolderDefinition:
    """Tests for add_folder_definition function."""

    def test_empty_path_raises_error(self, tmp_path: Path) -> None:
        """Test that empty path raises ValueError."""
        with pytest.raises(ValueError, match="Folder path cannot be empty"):
            add_folder_definition(tmp_path, "", "Description")

    def test_whitespace_only_path_raises_error(self, tmp_path: Path) -> None:
        """Test that whitespace-only path raises ValueError."""
        with pytest.raises(ValueError, match="Folder path cannot be empty"):
            add_folder_definition(tmp_path, "   ", "Description")

    def test_add_single_folder(self, tmp_path: Path) -> None:
        """Test adding a single top-level folder."""
        add_folder_definition(tmp_path, "Financial", "Financial documents")

        folders = get_folder_definitions(tmp_path)
        assert "Financial" in folders
        assert folders["Financial"].description == "Financial documents"
        assert folders["Financial"].folders == {}

    def test_add_nested_folder(self, tmp_path: Path) -> None:
        """Test adding a nested folder path."""
        add_folder_definition(
            tmp_path, "Financial/invoices/{year}", "Invoices by year"
        )

        folders = get_folder_definitions(tmp_path)
        assert "Financial" in folders
        assert "invoices" in folders["Financial"].folders
        assert "{year}" in folders["Financial"].folders["invoices"].folders
        assert (
            folders["Financial"].folders["invoices"].folders["{year}"].description
            == "Invoices by year"
        )

    def test_update_existing_folder_description(self, tmp_path: Path) -> None:
        """Test updating an existing folder's description."""
        add_folder_definition(tmp_path, "Financial", "Old description")
        add_folder_definition(tmp_path, "Financial", "New description")

        folders = get_folder_definitions(tmp_path)
        assert folders["Financial"].description == "New description"

    def test_add_sibling_folders(self, tmp_path: Path) -> None:
        """Test adding multiple folders at same level."""
        add_folder_definition(tmp_path, "Financial", "Financial documents")
        add_folder_definition(tmp_path, "Personal", "Personal documents")

        folders = get_folder_definitions(tmp_path)
        assert "Financial" in folders
        assert "Personal" in folders
        assert folders["Financial"].description == "Financial documents"
        assert folders["Personal"].description == "Personal documents"

    def test_add_child_to_existing_parent(self, tmp_path: Path) -> None:
        """Test adding a child folder to an existing parent."""
        add_folder_definition(tmp_path, "Financial", "Financial documents")
        add_folder_definition(tmp_path, "Financial/invoices", "Customer invoices")

        folders = get_folder_definitions(tmp_path)
        assert folders["Financial"].description == "Financial documents"
        assert "invoices" in folders["Financial"].folders
        assert folders["Financial"].folders["invoices"].description == "Customer invoices"

    def test_preserves_existing_structure(self, tmp_path: Path) -> None:
        """Test that adding new folders preserves existing structure."""
        add_folder_definition(tmp_path, "Financial/invoices", "Invoices")
        add_folder_definition(tmp_path, "Financial/receipts", "Receipts")

        folders = get_folder_definitions(tmp_path)
        assert "invoices" in folders["Financial"].folders
        assert "receipts" in folders["Financial"].folders
        assert folders["Financial"].folders["invoices"].description == "Invoices"
        assert folders["Financial"].folders["receipts"].description == "Receipts"

    def test_add_with_filename_convention(self, tmp_path: Path) -> None:
        """Test adding folder with filename convention."""
        add_folder_definition(
            tmp_path,
            "Financial/invoices",
            "Customer invoices",
            filename_convention="{year}-{month}-invoice"
        )

        folders = get_folder_definitions(tmp_path)
        assert folders["Financial"].folders["invoices"].filename_convention == "{year}-{month}-invoice"

    def test_update_filename_convention(self, tmp_path: Path) -> None:
        """Test updating filename convention for existing folder."""
        add_folder_definition(tmp_path, "Financial", "Financial documents")
        add_folder_definition(
            tmp_path,
            "Financial",
            "Financial documents",
            filename_convention="{year}-{category}"
        )

        folders = get_folder_definitions(tmp_path)
        assert folders["Financial"].filename_convention == "{year}-{category}"


class TestGetDefaultFilenameConvention:
    """Tests for get_default_filename_convention function."""

    def test_returns_none_when_not_set(self, tmp_path: Path) -> None:
        """Test that function returns None when default convention not set."""
        result = get_default_filename_convention(tmp_path)
        assert result is None

    def test_returns_none_with_empty_config(self, tmp_path: Path) -> None:
        """Test that function returns None with empty config file."""
        config_path = get_repo_config_path(tmp_path)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("")

        result = get_default_filename_convention(tmp_path)
        assert result is None

    def test_returns_convention_when_set(self, tmp_path: Path) -> None:
        """Test that function returns convention when set."""
        from docman.repo_config import set_default_filename_convention

        convention = "{year}-{month}-{description}"
        set_default_filename_convention(tmp_path, convention)

        result = get_default_filename_convention(tmp_path)
        assert result == convention


class TestSetDefaultFilenameConvention:
    """Tests for set_default_filename_convention function."""

    def test_sets_convention_in_new_config(self, tmp_path: Path) -> None:
        """Test setting convention in new config file."""
        convention = "{year}-{month}-{description}"
        set_default_filename_convention(tmp_path, convention)

        # Verify convention was set
        result = get_default_filename_convention(tmp_path)
        assert result == convention

    def test_sets_convention_in_existing_config(self, tmp_path: Path) -> None:
        """Test setting convention in existing config file."""
        # Create existing config with folder definitions
        add_folder_definition(tmp_path, "Financial", "Financial documents")

        # Set default convention
        convention = "{date}-{company}"
        set_default_filename_convention(tmp_path, convention)

        # Verify convention was set and folders preserved
        result = get_default_filename_convention(tmp_path)
        assert result == convention

        folders = get_folder_definitions(tmp_path)
        assert "Financial" in folders

    def test_updates_existing_convention(self, tmp_path: Path) -> None:
        """Test updating existing convention."""
        set_default_filename_convention(tmp_path, "{year}-{month}")
        set_default_filename_convention(tmp_path, "{company}-{date}")

        result = get_default_filename_convention(tmp_path)
        assert result == "{company}-{date}"

    def test_strips_whitespace(self, tmp_path: Path) -> None:
        """Test that whitespace is stripped from convention."""
        set_default_filename_convention(tmp_path, "  {year}-{month}  ")

        result = get_default_filename_convention(tmp_path)
        assert result == "{year}-{month}"

    def test_empty_convention_raises_error(self, tmp_path: Path) -> None:
        """Test that empty convention raises ValueError."""
        with pytest.raises(ValueError, match="Filename convention cannot be empty"):
            set_default_filename_convention(tmp_path, "")

    def test_whitespace_only_convention_raises_error(self, tmp_path: Path) -> None:
        """Test that whitespace-only convention raises ValueError."""
        with pytest.raises(ValueError, match="Filename convention cannot be empty"):
            set_default_filename_convention(tmp_path, "   ")
