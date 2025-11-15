"""Integration tests for the 'docman define' and 'docman config list-dirs' commands."""

from pathlib import Path

from click.testing import CliRunner

from docman.cli import main
from docman.repo_config import get_folder_definitions, get_repo_config_path
import pytest


@pytest.mark.integration
class TestDocmanDefine:
    """Integration tests for docman define command."""

    def test_define_single_folder(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Test defining a single top-level folder."""
        # Initialize repository first
        cli_runner.invoke(main, ["init", str(tmp_path)], input="n\n")

        # Define a folder from within the repository
        with cli_runner.isolated_filesystem(temp_dir=tmp_path):
            result = cli_runner.invoke(
                main, ["define", "Financial", "--desc", "Financial documents"]
            )

            assert result.exit_code == 0
            assert "✓ Defined folder: Financial" in result.output

        # Verify folder was saved to config
        folders = get_folder_definitions(tmp_path)
        assert "Financial" in folders
        assert folders["Financial"].description == "Financial documents"

    def test_define_nested_folder(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Test defining a nested folder path."""
        # Initialize repository
        cli_runner.invoke(main, ["init", str(tmp_path)], input="n\n")

        # Define nested folder from within the repository
        with cli_runner.isolated_filesystem(temp_dir=tmp_path):
            result = cli_runner.invoke(
                main,
                ["define", "Financial/invoices/{year}", "--desc", "Invoices by year"],
            )

            assert result.exit_code == 0
            assert "✓ Defined folder: Financial/invoices/{year}" in result.output

        # Verify nested structure
        folders = get_folder_definitions(tmp_path)
        assert "Financial" in folders
        assert "invoices" in folders["Financial"].folders
        assert "{year}" in folders["Financial"].folders["invoices"].folders
        assert (
            folders["Financial"].folders["invoices"].folders["{year}"].description
            == "Invoices by year"
        )

    def test_define_multiple_folders(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Test defining multiple folders in sequence."""
        # Initialize repository
        cli_runner.invoke(main, ["init", str(tmp_path)], input="n\n")

        # Define multiple folders from within repository
        with cli_runner.isolated_filesystem(temp_dir=tmp_path):
            result1 = cli_runner.invoke(
                main, ["define", "Financial", "--desc", "Financial documents"]
            )
            result2 = cli_runner.invoke(
                main, ["define", "Personal", "--desc", "Personal documents"]
            )
            result3 = cli_runner.invoke(
                main,
                ["define", "Financial/invoices", "--desc", "Customer invoices"],
            )

            assert result1.exit_code == 0
            assert result2.exit_code == 0
            assert result3.exit_code == 0

        # Verify all folders exist
        folders = get_folder_definitions(tmp_path)
        assert "Financial" in folders
        assert "Personal" in folders
        assert "invoices" in folders["Financial"].folders

    def test_define_update_existing_folder(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test updating an existing folder's description."""
        # Initialize repository
        cli_runner.invoke(main, ["init", str(tmp_path)], input="n\n")

        # Define folder, then update from within repository
        with cli_runner.isolated_filesystem(temp_dir=tmp_path):
            cli_runner.invoke(
                main, ["define", "Financial", "--desc", "Old description"]
            )

            # Update description
            result = cli_runner.invoke(
                main, ["define", "Financial", "--desc", "New description"]
            )

            assert result.exit_code == 0
            assert "✓ Defined folder: Financial" in result.output

        # Verify description was updated
        folders = get_folder_definitions(tmp_path)
        assert folders["Financial"].description == "New description"

    def test_define_empty_path_error(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Test that defining with empty path shows error."""
        # Initialize repository
        cli_runner.invoke(main, ["init", str(tmp_path)], input="n\n")

        # Try to define with empty path from within repository
        with cli_runner.isolated_filesystem(temp_dir=tmp_path):
            result = cli_runner.invoke(
                main, ["define", "", "--desc", "Some description"]
            )

            assert result.exit_code == 1
            assert "Error" in result.output

    def test_define_without_desc(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test that defining without --desc works (description is optional)."""
        # Initialize repository
        cli_runner.invoke(main, ["init", str(tmp_path)], input="n\n")

        # Define without --desc from within repository
        with cli_runner.isolated_filesystem(temp_dir=tmp_path):
            result = cli_runner.invoke(main, ["define", "Financial"])

            assert result.exit_code == 0
            assert "✓ Defined folder: Financial" in result.output

        # Verify folder was created without description
        folders = get_folder_definitions(tmp_path)
        assert "Financial" in folders
        assert folders["Financial"].description is None

    def test_define_preserves_existing_desc_when_not_provided(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test that existing description is preserved when updating without providing --desc."""
        # Initialize repository
        cli_runner.invoke(main, ["init", str(tmp_path)], input="n\n")

        # Define folder with description from within repository
        with cli_runner.isolated_filesystem(temp_dir=tmp_path):
            cli_runner.invoke(
                main, ["define", "Financial", "--desc", "Financial documents"]
            )

            # Update with filename convention but no description
            cli_runner.invoke(
                main,
                ["define", "Financial", "--filename-convention", "{year}-{month}"],
            )

        # Verify description was preserved
        folders = get_folder_definitions(tmp_path)
        assert folders["Financial"].description == "Financial documents"
        assert folders["Financial"].filename_convention == "{year}-{month}"

    def test_define_not_in_repository(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Test that define fails when not in a docman repository."""
        with cli_runner.isolated_filesystem(temp_dir=tmp_path):
            result = cli_runner.invoke(
                main, ["define", "Financial", "--desc", "Financial documents"]
            )

            assert result.exit_code == 1
            assert "Error" in result.output
            assert "Not in a docman repository" in result.output

    def test_define_persists_to_config_file(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test that define persists folder definitions to config.yaml."""
        # Initialize repository
        cli_runner.invoke(main, ["init", str(tmp_path)], input="n\n")

        # Define folder from within repository
        with cli_runner.isolated_filesystem(temp_dir=tmp_path):
            result = cli_runner.invoke(
                main, ["define", "Financial", "--desc", "Financial documents"]
            )

            assert result.exit_code == 0

        # Verify config file exists and contains the definition
        config_path = get_repo_config_path(tmp_path)
        assert config_path.exists()

        # Verify the folder was actually saved
        folders = get_folder_definitions(tmp_path)
        assert "Financial" in folders

    def test_define_handles_malformed_yaml(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test that define shows helpful error for malformed YAML config."""
        # Initialize repository
        cli_runner.invoke(main, ["init", str(tmp_path)], input="n\n")

        # Corrupt the config file with invalid YAML
        config_path = get_repo_config_path(tmp_path)
        config_path.write_text("organization:\n  folders: {\n    invalid")

        # Try to define a folder
        with cli_runner.isolated_filesystem(temp_dir=tmp_path):
            result = cli_runner.invoke(
                main, ["define", "Financial", "--desc", "Financial documents"]
            )

            assert result.exit_code == 1
            assert "Error" in result.output
            assert "invalid YAML syntax" in result.output
            assert "config.yaml" in result.output


@pytest.mark.integration
class TestDocmanConfigListDirs:
    """Integration tests for docman config list-dirs command."""

    def test_list_dirs_empty(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Test listing directories when none are defined."""
        # Initialize repository
        cli_runner.invoke(main, ["init", str(tmp_path)], input="n\n")

        # List directories from within repository
        with cli_runner.isolated_filesystem(temp_dir=tmp_path):
            result = cli_runner.invoke(main, ["config", "list-dirs"])

            assert result.exit_code == 0
            assert "No folder definitions found" in result.output

    def test_list_dirs_single_folder(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Test listing a single folder."""
        # Initialize and define folder
        cli_runner.invoke(main, ["init", str(tmp_path)], input="n\n")

        with cli_runner.isolated_filesystem(temp_dir=tmp_path):
            cli_runner.invoke(
                main, ["define", "Financial", "--desc", "Financial documents"]
            )

            # List directories
            result = cli_runner.invoke(main, ["config", "list-dirs"])

            assert result.exit_code == 0
            assert "Financial" in result.output

    def test_list_dirs_nested_structure(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test listing nested folder structure."""
        # Initialize repository
        cli_runner.invoke(main, ["init", str(tmp_path)], input="n\n")

        # Define nested structure from within repository
        with cli_runner.isolated_filesystem(temp_dir=tmp_path):
            cli_runner.invoke(
                main, ["define", "Financial", "--desc", "Financial documents"]
            )
            cli_runner.invoke(
                main,
                ["define", "Financial/invoices", "--desc", "Customer invoices"],
            )
            cli_runner.invoke(
                main,
                ["define", "Financial/receipts", "--desc", "Personal receipts"],
            )

            # List directories
            result = cli_runner.invoke(main, ["config", "list-dirs"])

            assert result.exit_code == 0
            assert "Financial" in result.output
            assert "invoices" in result.output
            assert "receipts" in result.output
            # Check for tree structure characters
            assert "├─" in result.output or "└─" in result.output

    def test_list_dirs_multiple_top_level(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test listing multiple top-level folders."""
        # Initialize repository
        cli_runner.invoke(main, ["init", str(tmp_path)], input="n\n")

        # Define multiple top-level folders from within repository
        with cli_runner.isolated_filesystem(temp_dir=tmp_path):
            cli_runner.invoke(
                main, ["define", "Financial", "--desc", "Financial documents"]
            )
            cli_runner.invoke(
                main, ["define", "Personal", "--desc", "Personal documents"]
            )
            cli_runner.invoke(
                main, ["define", "Work", "--desc", "Work documents"]
            )

            # List directories
            result = cli_runner.invoke(main, ["config", "list-dirs"])

            assert result.exit_code == 0
            assert "Financial" in result.output
            assert "Personal" in result.output
            assert "Work" in result.output

    def test_list_dirs_complex_structure(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test listing complex nested structure."""
        # Initialize repository
        cli_runner.invoke(main, ["init", str(tmp_path)], input="n\n")

        # Define complex structure from within repository
        with cli_runner.isolated_filesystem(temp_dir=tmp_path):
            cli_runner.invoke(
                main,
                ["define", "Financial/invoices/{year}/{company}", "--desc", "Invoices"],
            )
            cli_runner.invoke(
                main,
                ["define", "Financial/receipts/{category}", "--desc", "Receipts"],
            )
            cli_runner.invoke(
                main,
                ["define", "Personal/medical/{family_member}", "--desc", "Medical records"],
            )

            # List directories
            result = cli_runner.invoke(main, ["config", "list-dirs"])

            assert result.exit_code == 0
            assert "Financial" in result.output
            assert "invoices" in result.output
            assert "{year}" in result.output
            assert "{company}" in result.output
            assert "receipts" in result.output
            assert "{category}" in result.output
            assert "Personal" in result.output
            assert "medical" in result.output
            assert "{family_member}" in result.output

    def test_list_dirs_not_in_repository(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test that list-dirs fails when not in a docman repository."""
        with cli_runner.isolated_filesystem(temp_dir=tmp_path):
            result = cli_runner.invoke(main, ["config", "list-dirs"])

            assert result.exit_code == 1
            assert "Error" in result.output or result.exit_code != 0

    def test_list_dirs_with_path_option(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test list-dirs with --path option."""
        # Initialize and define folder
        cli_runner.invoke(main, ["init", str(tmp_path)], input="n\n")

        with cli_runner.isolated_filesystem(temp_dir=tmp_path):
            cli_runner.invoke(
                main, ["define", "Financial", "--desc", "Financial documents"]
            )

        # List directories from different location using --path
        result = cli_runner.invoke(
            main, ["config", "list-dirs", "--path", str(tmp_path)]
        )

        assert result.exit_code == 0
        assert "Financial" in result.output

    def test_list_dirs_handles_malformed_yaml(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test that list-dirs shows helpful error for malformed YAML config."""
        # Initialize repository
        cli_runner.invoke(main, ["init", str(tmp_path)], input="n\n")

        # Corrupt the config file with invalid YAML
        config_path = get_repo_config_path(tmp_path)
        config_path.write_text("organization:\n  folders: {\n    invalid")

        # Try to list directories
        with cli_runner.isolated_filesystem(temp_dir=tmp_path):
            result = cli_runner.invoke(main, ["config", "list-dirs"])

            assert result.exit_code == 1
            assert "Error" in result.output
            assert "invalid YAML syntax" in result.output
            assert "config.yaml" in result.output


@pytest.mark.integration
class TestPatternCommands:
    """Integration tests for pattern management commands."""

    def test_pattern_add(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Test adding a variable pattern."""
        # Initialize repository
        cli_runner.invoke(main, ["init", str(tmp_path)], input="n\n")

        # Add a variable pattern
        result = cli_runner.invoke(
            main,
            ["pattern", "add", "year", "--desc", "4-digit year in YYYY format", "--path", str(tmp_path)],
        )

        assert result.exit_code == 0
        assert "Variable pattern 'year' saved" in result.output
        assert "4-digit year in YYYY format" in result.output

        # Verify pattern was saved
        from docman.repo_config import get_variable_patterns

        patterns = get_variable_patterns(tmp_path)
        assert "year" in patterns
        assert patterns["year"] == "4-digit year in YYYY format"

    def test_pattern_add_updates_existing(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test that adding a pattern with existing name updates it."""
        # Initialize repository
        cli_runner.invoke(main, ["init", str(tmp_path)], input="n\n")

        # Add pattern first time
        cli_runner.invoke(
            main, ["pattern", "add", "year", "--desc", "Old description", "--path", str(tmp_path)]
        )

        # Update pattern
        result = cli_runner.invoke(
            main, ["pattern", "add", "year", "--desc", "New description", "--path", str(tmp_path)]
        )

        assert result.exit_code == 0
        assert "Variable pattern 'year' saved" in result.output

        # Verify pattern was updated
        from docman.repo_config import get_variable_patterns

        patterns = get_variable_patterns(tmp_path)
        assert patterns["year"] == "New description"

    def test_pattern_list_empty(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Test listing patterns when none are defined."""
        # Initialize repository
        cli_runner.invoke(main, ["init", str(tmp_path)], input="n\n")

        # List patterns
        result = cli_runner.invoke(main, ["pattern", "list", "--path", str(tmp_path)])

        assert result.exit_code == 0
        assert "No variable patterns defined" in result.output

    def test_pattern_list_shows_patterns(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test listing patterns shows all defined patterns."""
        # Initialize repository
        cli_runner.invoke(main, ["init", str(tmp_path)], input="n\n")

        # Add multiple patterns
        cli_runner.invoke(
            main,
            ["pattern", "add", "year", "--desc", "4-digit year in YYYY format", "--path", str(tmp_path)],
        )
        cli_runner.invoke(
            main, ["pattern", "add", "category", "--desc", "Document category", "--path", str(tmp_path)]
        )

        # List patterns
        result = cli_runner.invoke(main, ["pattern", "list", "--path", str(tmp_path)])

        assert result.exit_code == 0
        assert "Variable Patterns:" in result.output
        assert "year:" in result.output
        assert "4-digit year in YYYY format" in result.output
        assert "category:" in result.output
        assert "Document category" in result.output

    def test_pattern_show(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Test showing details of a specific pattern."""
        # Initialize repository
        cli_runner.invoke(main, ["init", str(tmp_path)], input="n\n")

        # Add pattern
        cli_runner.invoke(
            main,
            ["pattern", "add", "year", "--desc", "4-digit year in YYYY format", "--path", str(tmp_path)],
        )

        # Show pattern
        result = cli_runner.invoke(main, ["pattern", "show", "year", "--path", str(tmp_path)])

        assert result.exit_code == 0
        assert "Pattern: year" in result.output
        assert "4-digit year in YYYY format" in result.output

    def test_pattern_show_not_found(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test showing a non-existent pattern."""
        # Initialize repository
        cli_runner.invoke(main, ["init", str(tmp_path)], input="n\n")

        # Show pattern that doesn't exist
        result = cli_runner.invoke(main, ["pattern", "show", "year", "--path", str(tmp_path)])

        assert result.exit_code == 1
        assert "Variable pattern 'year' not found" in result.output

    def test_pattern_remove(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Test removing a variable pattern."""
        # Initialize repository
        cli_runner.invoke(main, ["init", str(tmp_path)], input="n\n")

        # Add pattern
        cli_runner.invoke(
            main,
            ["pattern", "add", "year", "--desc", "4-digit year in YYYY format", "--path", str(tmp_path)],
        )

        # Remove pattern (with -y to skip confirmation)
        result = cli_runner.invoke(main, ["pattern", "remove", "year", "-y", "--path", str(tmp_path)])

        assert result.exit_code == 0
        assert "Variable pattern 'year' removed" in result.output

        # Verify pattern was removed
        from docman.repo_config import get_variable_patterns

        patterns = get_variable_patterns(tmp_path)
        assert "year" not in patterns

    def test_pattern_remove_not_found(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test removing a non-existent pattern."""
        # Initialize repository
        cli_runner.invoke(main, ["init", str(tmp_path)], input="n\n")

        # Try to remove pattern that doesn't exist
        result = cli_runner.invoke(main, ["pattern", "remove", "year", "-y", "--path", str(tmp_path)])

        assert result.exit_code == 1
        assert "Variable pattern 'year' not found" in result.output

    def test_pattern_remove_requires_confirmation(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test that pattern removal requires confirmation without -y flag."""
        # Initialize repository
        cli_runner.invoke(main, ["init", str(tmp_path)], input="n\n")

        # Add pattern
        cli_runner.invoke(
            main,
            ["pattern", "add", "year", "--desc", "4-digit year in YYYY format", "--path", str(tmp_path)],
        )

        # Try to remove without -y, answer 'n' to cancel
        result = cli_runner.invoke(
            main, ["pattern", "remove", "year", "--path", str(tmp_path)], input="n\n"
        )

        assert result.exit_code == 0
        assert "Remove variable pattern 'year'?" in result.output
        assert "Cancelled" in result.output

        # Verify pattern was NOT removed
        from docman.repo_config import get_variable_patterns

        patterns = get_variable_patterns(tmp_path)
        assert "year" in patterns
