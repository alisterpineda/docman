"""Integration tests for LLM CLI commands."""

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from click.testing import CliRunner

from docman.cli import main
from docman.llm_config import ProviderConfig, add_provider


@pytest.mark.integration
class TestLLMAdd:
    """Integration tests for 'docman llm add' command."""

    def setup_isolated_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Set up isolated environment with separate app config."""
        app_config_dir = tmp_path / "app_config"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(app_config_dir))

    @patch("docman.cli.get_llm_provider")
    @patch("docman.llm_config.keyring")
    def test_add_success_with_all_options(
        self,
        mock_keyring: Mock,
        mock_get_provider: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test successfully adding provider with all options provided (non-interactive)."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        # Mock keyring operations
        mock_keyring.set_password.return_value = None

        # Mock LLM provider test connection
        mock_provider_instance = MagicMock()
        mock_provider_instance.test_connection.return_value = True
        mock_get_provider.return_value = mock_provider_instance

        # Run command with all options
        result = cli_runner.invoke(
            main,
            [
                "llm",
                "add",
                "--name",
                "test-provider",
                "--provider",
                "google",
                "--model",
                "gemini-1.5-flash",
                "--api-key",
                "test-api-key-123",
            ],
            catch_exceptions=False,
        )

        # Verify success
        assert result.exit_code == 0
        assert "Testing connection..." in result.output
        assert "Connection successful!" in result.output
        assert "Provider 'test-provider' added successfully!" in result.output
        assert "Provider 'test-provider' is now active." in result.output

        # Verify keyring was called
        mock_keyring.set_password.assert_called_once_with(
            "docman_llm", "test-provider", "test-api-key-123"
        )

        # Verify provider test was called
        mock_provider_instance.test_connection.assert_called_once()

    @patch("docman.cli.run_llm_wizard")
    def test_add_falls_back_to_wizard_when_options_missing(
        self,
        mock_wizard: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that add command uses wizard when options are missing."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        # Mock wizard to return success
        mock_wizard.return_value = True

        # Run command without options
        result = cli_runner.invoke(main, ["llm", "add"], catch_exceptions=False)

        # Verify wizard was called
        mock_wizard.assert_called_once()
        assert result.exit_code == 0

    @patch("docman.cli.run_llm_wizard")
    def test_add_wizard_cancelled(
        self,
        mock_wizard: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that add command handles wizard cancellation."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        # Mock wizard to return failure
        mock_wizard.return_value = False

        # Run command without options
        result = cli_runner.invoke(main, ["llm", "add"], catch_exceptions=False)

        # Verify wizard was called
        mock_wizard.assert_called_once()
        assert result.exit_code == 1
        assert "Setup failed or cancelled." in result.output

    @patch("docman.cli.get_llm_provider")
    @patch("docman.llm_config.keyring")
    def test_add_duplicate_name_error(
        self,
        mock_keyring: Mock,
        mock_get_provider: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that adding provider with duplicate name fails."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        # Mock keyring operations
        mock_keyring.set_password.return_value = None

        # Mock LLM provider test connection
        mock_provider_instance = MagicMock()
        mock_provider_instance.test_connection.return_value = True
        mock_get_provider.return_value = mock_provider_instance

        # Add first provider
        result1 = cli_runner.invoke(
            main,
            [
                "llm",
                "add",
                "--name",
                "test-provider",
                "--provider",
                "google",
                "--model",
                "gemini-1.5-flash",
                "--api-key",
                "test-api-key-123",
            ],
            catch_exceptions=False,
        )
        assert result1.exit_code == 0

        # Try to add duplicate
        result2 = cli_runner.invoke(
            main,
            [
                "llm",
                "add",
                "--name",
                "test-provider",
                "--provider",
                "google",
                "--model",
                "gemini-1.5-pro",
                "--api-key",
                "different-key",
            ],
            catch_exceptions=False,
        )

        # Verify error
        assert result2.exit_code == 1
        assert "Error:" in result2.output
        assert "already exists" in result2.output

    @patch("docman.cli.get_llm_provider")
    @patch("docman.llm_config.keyring")
    def test_add_connection_test_failure(
        self,
        mock_keyring: Mock,
        mock_get_provider: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that add command handles connection test failures."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        # Mock keyring operations
        mock_keyring.set_password.return_value = None

        # Mock LLM provider to fail connection test
        mock_provider_instance = MagicMock()
        mock_provider_instance.test_connection.side_effect = Exception("Invalid API key")
        mock_get_provider.return_value = mock_provider_instance

        # Run command
        result = cli_runner.invoke(
            main,
            [
                "llm",
                "add",
                "--name",
                "test-provider",
                "--provider",
                "google",
                "--model",
                "gemini-1.5-flash",
                "--api-key",
                "invalid-key",
            ],
            catch_exceptions=False,
        )

        # Verify failure
        assert result.exit_code == 1
        assert "Connection test failed:" in result.output
        assert "Invalid API key" in result.output

    @patch("docman.cli.get_llm_provider")
    @patch("docman.llm_config.keyring")
    def test_add_first_provider_becomes_active(
        self,
        mock_keyring: Mock,
        mock_get_provider: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that first provider is automatically set as active."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        # Mock keyring operations
        mock_keyring.set_password.return_value = None

        # Mock LLM provider
        mock_provider_instance = MagicMock()
        mock_provider_instance.test_connection.return_value = True
        mock_get_provider.return_value = mock_provider_instance

        # Add first provider
        result = cli_runner.invoke(
            main,
            [
                "llm",
                "add",
                "--name",
                "first-provider",
                "--provider",
                "google",
                "--model",
                "gemini-1.5-flash",
                "--api-key",
                "test-key",
            ],
            catch_exceptions=False,
        )

        # Verify it's marked as active
        assert result.exit_code == 0
        assert "Provider 'first-provider' is now active." in result.output


@pytest.mark.integration
class TestLLMList:
    """Integration tests for 'docman llm list' command."""

    def setup_isolated_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Set up isolated environment with separate app config."""
        app_config_dir = tmp_path / "app_config"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(app_config_dir))

    def test_list_empty(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test list command with no providers configured."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        result = cli_runner.invoke(main, ["llm", "list"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "No LLM providers configured." in result.output
        assert "Run 'docman llm add' to add a provider." in result.output

    @patch("docman.cli.get_llm_provider")
    @patch("docman.llm_config.keyring")
    def test_list_single_provider(
        self,
        mock_keyring: Mock,
        mock_get_provider: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test list command with single provider."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        # Mock dependencies
        mock_keyring.set_password.return_value = None
        mock_provider_instance = MagicMock()
        mock_provider_instance.test_connection.return_value = True
        mock_get_provider.return_value = mock_provider_instance

        # Add a provider
        cli_runner.invoke(
            main,
            [
                "llm",
                "add",
                "--name",
                "my-provider",
                "--provider",
                "google",
                "--model",
                "gemini-1.5-flash",
                "--api-key",
                "test-key",
            ],
            catch_exceptions=False,
        )

        # List providers
        result = cli_runner.invoke(main, ["llm", "list"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Configured LLM Providers:" in result.output
        assert "my-provider" in result.output
        assert "Type: google" in result.output
        assert "Model: gemini-1.5-flash" in result.output
        assert "●" in result.output  # Active marker

    @patch("docman.cli.get_llm_provider")
    @patch("docman.llm_config.keyring")
    def test_list_multiple_providers_with_active_indicator(
        self,
        mock_keyring: Mock,
        mock_get_provider: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test list command with multiple providers shows active indicator correctly."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        # Mock dependencies
        mock_keyring.set_password.return_value = None
        mock_provider_instance = MagicMock()
        mock_provider_instance.test_connection.return_value = True
        mock_get_provider.return_value = mock_provider_instance

        # Add first provider (becomes active)
        cli_runner.invoke(
            main,
            [
                "llm",
                "add",
                "--name",
                "provider-1",
                "--provider",
                "google",
                "--model",
                "gemini-1.5-flash",
                "--api-key",
                "key1",
            ],
            catch_exceptions=False,
        )

        # Add second provider
        cli_runner.invoke(
            main,
            [
                "llm",
                "add",
                "--name",
                "provider-2",
                "--provider",
                "google",
                "--model",
                "gemini-1.5-pro",
                "--api-key",
                "key2",
            ],
            catch_exceptions=False,
        )

        # List providers
        result = cli_runner.invoke(main, ["llm", "list"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "provider-1" in result.output
        assert "provider-2" in result.output
        # First provider should still be active (marked with ●)
        # Count the active markers - should be exactly one
        active_markers = result.output.count("●")
        inactive_markers = result.output.count("○")
        assert active_markers == 1
        assert inactive_markers == 1


@pytest.mark.integration
class TestLLMRemove:
    """Integration tests for 'docman llm remove' command."""

    def setup_isolated_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Set up isolated environment with separate app config."""
        app_config_dir = tmp_path / "app_config"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(app_config_dir))

    @patch("docman.cli.get_llm_provider")
    @patch("docman.llm_config.keyring")
    def test_remove_success_with_confirmation(
        self,
        mock_keyring: Mock,
        mock_get_provider: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test successfully removing provider with confirmation."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        # Mock dependencies for add
        mock_keyring.set_password.return_value = None
        mock_keyring.delete_password.return_value = None
        mock_provider_instance = MagicMock()
        mock_provider_instance.test_connection.return_value = True
        mock_get_provider.return_value = mock_provider_instance

        # Add a provider
        cli_runner.invoke(
            main,
            [
                "llm",
                "add",
                "--name",
                "test-provider",
                "--provider",
                "google",
                "--model",
                "gemini-1.5-flash",
                "--api-key",
                "test-key",
            ],
            catch_exceptions=False,
        )

        # Remove with confirmation
        result = cli_runner.invoke(
            main, ["llm", "remove", "test-provider"], input="y\n", catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Provider to remove:" in result.output
        assert "test-provider" in result.output
        assert "Are you sure you want to remove 'test-provider'?" in result.output
        assert "Provider 'test-provider' removed successfully." in result.output
        mock_keyring.delete_password.assert_called_with("docman_llm", "test-provider")

    @patch("docman.cli.get_llm_provider")
    @patch("docman.llm_config.keyring")
    def test_remove_success_with_yes_flag(
        self,
        mock_keyring: Mock,
        mock_get_provider: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test removing provider with -y flag skips confirmation."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        # Mock dependencies
        mock_keyring.set_password.return_value = None
        mock_keyring.delete_password.return_value = None
        mock_provider_instance = MagicMock()
        mock_provider_instance.test_connection.return_value = True
        mock_get_provider.return_value = mock_provider_instance

        # Add a provider
        cli_runner.invoke(
            main,
            [
                "llm",
                "add",
                "--name",
                "test-provider",
                "--provider",
                "google",
                "--model",
                "gemini-1.5-flash",
                "--api-key",
                "test-key",
            ],
            catch_exceptions=False,
        )

        # Remove with -y flag
        result = cli_runner.invoke(
            main, ["llm", "remove", "test-provider", "-y"], catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Are you sure" not in result.output  # No confirmation prompt
        assert "Provider 'test-provider' removed successfully." in result.output

    @patch("docman.cli.get_llm_provider")
    @patch("docman.llm_config.keyring")
    def test_remove_confirmation_declined(
        self,
        mock_keyring: Mock,
        mock_get_provider: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that declining confirmation aborts removal."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        # Mock dependencies
        mock_keyring.set_password.return_value = None
        mock_keyring.delete_password.return_value = None
        mock_provider_instance = MagicMock()
        mock_provider_instance.test_connection.return_value = True
        mock_get_provider.return_value = mock_provider_instance

        # Add a provider
        cli_runner.invoke(
            main,
            [
                "llm",
                "add",
                "--name",
                "test-provider",
                "--provider",
                "google",
                "--model",
                "gemini-1.5-flash",
                "--api-key",
                "test-key",
            ],
            catch_exceptions=False,
        )

        # Remove but decline confirmation
        result = cli_runner.invoke(
            main, ["llm", "remove", "test-provider"], input="n\n", catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Aborted." in result.output
        # Verify provider still exists
        list_result = cli_runner.invoke(main, ["llm", "list"], catch_exceptions=False)
        assert "test-provider" in list_result.output

    def test_remove_nonexistent_provider(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test removing a provider that doesn't exist."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        result = cli_runner.invoke(
            main, ["llm", "remove", "nonexistent"], catch_exceptions=False
        )

        assert result.exit_code == 1
        assert "Error: Provider 'nonexistent' not found." in result.output

    @patch("docman.cli.get_llm_provider")
    @patch("docman.llm_config.keyring")
    def test_remove_active_provider_selects_new_active(
        self,
        mock_keyring: Mock,
        mock_get_provider: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that removing active provider selects a new active provider."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        # Mock dependencies
        mock_keyring.set_password.return_value = None
        mock_keyring.delete_password.return_value = None
        mock_provider_instance = MagicMock()
        mock_provider_instance.test_connection.return_value = True
        mock_get_provider.return_value = mock_provider_instance

        # Add two providers
        cli_runner.invoke(
            main,
            [
                "llm",
                "add",
                "--name",
                "provider-1",
                "--provider",
                "google",
                "--model",
                "gemini-1.5-flash",
                "--api-key",
                "key1",
            ],
            catch_exceptions=False,
        )
        cli_runner.invoke(
            main,
            [
                "llm",
                "add",
                "--name",
                "provider-2",
                "--provider",
                "google",
                "--model",
                "gemini-1.5-pro",
                "--api-key",
                "key2",
            ],
            catch_exceptions=False,
        )

        # Set provider-1 as active
        cli_runner.invoke(
            main, ["llm", "set-active", "provider-1"], catch_exceptions=False
        )

        # Remove active provider
        result = cli_runner.invoke(
            main, ["llm", "remove", "provider-1", "-y"], catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Active provider is now: provider-2" in result.output


@pytest.mark.integration
class TestLLMSetActive:
    """Integration tests for 'docman llm set-active' command."""

    def setup_isolated_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Set up isolated environment with separate app config."""
        app_config_dir = tmp_path / "app_config"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(app_config_dir))

    @patch("docman.cli.get_llm_provider")
    @patch("docman.llm_config.keyring")
    def test_set_active_success(
        self,
        mock_keyring: Mock,
        mock_get_provider: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test successfully setting a provider as active."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        # Mock dependencies
        mock_keyring.set_password.return_value = None
        mock_provider_instance = MagicMock()
        mock_provider_instance.test_connection.return_value = True
        mock_get_provider.return_value = mock_provider_instance

        # Add two providers
        cli_runner.invoke(
            main,
            [
                "llm",
                "add",
                "--name",
                "provider-1",
                "--provider",
                "google",
                "--model",
                "gemini-1.5-flash",
                "--api-key",
                "key1",
            ],
            catch_exceptions=False,
        )
        cli_runner.invoke(
            main,
            [
                "llm",
                "add",
                "--name",
                "provider-2",
                "--provider",
                "google",
                "--model",
                "gemini-1.5-pro",
                "--api-key",
                "key2",
            ],
            catch_exceptions=False,
        )

        # Set provider-2 as active
        result = cli_runner.invoke(
            main, ["llm", "set-active", "provider-2"], catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Provider 'provider-2' is now active." in result.output

        # Verify via list command
        list_result = cli_runner.invoke(main, ["llm", "list"], catch_exceptions=False)
        # provider-2 should have the active marker in its line
        lines = list_result.output.split("\n")
        for i, line in enumerate(lines):
            if "provider-2" in line:
                assert "●" in line
            elif "provider-1" in line:
                assert "○" in line

    def test_set_active_nonexistent_provider(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test setting a nonexistent provider as active."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        result = cli_runner.invoke(
            main, ["llm", "set-active", "nonexistent"], catch_exceptions=False
        )

        assert result.exit_code == 1
        assert "Error: Provider 'nonexistent' not found." in result.output


@pytest.mark.integration
class TestLLMShow:
    """Integration tests for 'docman llm show' command."""

    def setup_isolated_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Set up isolated environment with separate app config."""
        app_config_dir = tmp_path / "app_config"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(app_config_dir))

    @patch("docman.cli.get_llm_provider")
    @patch("docman.llm_config.keyring")
    def test_show_active_provider_no_args(
        self,
        mock_keyring: Mock,
        mock_get_provider: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test showing active provider without specifying name."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        # Mock dependencies
        mock_keyring.set_password.return_value = None
        mock_keyring.get_password.return_value = "test-key"
        mock_provider_instance = MagicMock()
        mock_provider_instance.test_connection.return_value = True
        mock_get_provider.return_value = mock_provider_instance

        # Add a provider
        cli_runner.invoke(
            main,
            [
                "llm",
                "add",
                "--name",
                "my-provider",
                "--provider",
                "google",
                "--model",
                "gemini-1.5-flash",
                "--api-key",
                "test-key",
            ],
            catch_exceptions=False,
        )

        # Show active provider
        result = cli_runner.invoke(main, ["llm", "show"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Provider: my-provider" in result.output
        assert "(Active)" in result.output
        assert "Type: google" in result.output
        assert "Model: gemini-1.5-flash" in result.output
        assert "API Key: Configured ✓" in result.output
        # Should NOT show actual API key
        assert "test-key" not in result.output

    @patch("docman.cli.get_llm_provider")
    @patch("docman.llm_config.keyring")
    def test_show_specific_provider_by_name(
        self,
        mock_keyring: Mock,
        mock_get_provider: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test showing a specific provider by name."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        # Mock dependencies
        mock_keyring.set_password.return_value = None
        mock_keyring.get_password.return_value = "test-key"
        mock_provider_instance = MagicMock()
        mock_provider_instance.test_connection.return_value = True
        mock_get_provider.return_value = mock_provider_instance

        # Add two providers
        cli_runner.invoke(
            main,
            [
                "llm",
                "add",
                "--name",
                "provider-1",
                "--provider",
                "google",
                "--model",
                "gemini-1.5-flash",
                "--api-key",
                "key1",
            ],
            catch_exceptions=False,
        )
        cli_runner.invoke(
            main,
            [
                "llm",
                "add",
                "--name",
                "provider-2",
                "--provider",
                "google",
                "--model",
                "gemini-1.5-pro",
                "--api-key",
                "key2",
            ],
            catch_exceptions=False,
        )

        # Show specific provider (not active)
        result = cli_runner.invoke(
            main, ["llm", "show", "provider-2"], catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Provider: provider-2" in result.output
        assert "Type: google" in result.output
        assert "Model: gemini-1.5-pro" in result.output

    def test_show_nonexistent_provider(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test showing a provider that doesn't exist."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        result = cli_runner.invoke(
            main, ["llm", "show", "nonexistent"], catch_exceptions=False
        )

        assert result.exit_code == 1
        assert "Error: Provider 'nonexistent' not found." in result.output

    def test_show_no_active_provider(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test showing active provider when none is configured."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        result = cli_runner.invoke(main, ["llm", "show"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "No active provider configured." in result.output
        assert "Run 'docman llm add' to add a provider." in result.output

    @patch("docman.cli.get_llm_provider")
    @patch("docman.llm_config.keyring")
    def test_show_api_key_not_found(
        self,
        mock_keyring: Mock,
        mock_get_provider: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test showing provider when API key is missing from keyring."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        # Mock dependencies
        mock_keyring.set_password.return_value = None
        # Simulate API key not found
        mock_keyring.get_password.return_value = None
        mock_provider_instance = MagicMock()
        mock_provider_instance.test_connection.return_value = True
        mock_get_provider.return_value = mock_provider_instance

        # Add a provider
        cli_runner.invoke(
            main,
            [
                "llm",
                "add",
                "--name",
                "my-provider",
                "--provider",
                "google",
                "--model",
                "gemini-1.5-flash",
                "--api-key",
                "test-key",
            ],
            catch_exceptions=False,
        )

        # Show provider
        result = cli_runner.invoke(main, ["llm", "show"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "API Key: Not found ✗" in result.output


@pytest.mark.integration
class TestLLMTest:
    """Integration tests for 'docman llm test' command."""

    def setup_isolated_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Set up isolated environment with separate app config."""
        app_config_dir = tmp_path / "app_config"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(app_config_dir))

    @patch("docman.cli.get_llm_provider")
    @patch("docman.llm_config.keyring")
    def test_test_active_provider_success(
        self,
        mock_keyring: Mock,
        mock_get_provider: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test connection to active provider successfully."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        # Mock dependencies
        mock_keyring.set_password.return_value = None
        mock_keyring.get_password.return_value = "test-key"
        mock_provider_instance = MagicMock()
        mock_provider_instance.test_connection.return_value = True
        mock_get_provider.return_value = mock_provider_instance

        # Add a provider
        cli_runner.invoke(
            main,
            [
                "llm",
                "add",
                "--name",
                "my-provider",
                "--provider",
                "google",
                "--model",
                "gemini-1.5-flash",
                "--api-key",
                "test-key",
            ],
            catch_exceptions=False,
        )

        # Test connection (no name argument, uses active)
        result = cli_runner.invoke(main, ["llm", "test"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Testing connection to 'my-provider'..." in result.output
        assert "Connection successful!" in result.output

    @patch("docman.cli.get_llm_provider")
    @patch("docman.llm_config.keyring")
    def test_test_specific_provider_by_name(
        self,
        mock_keyring: Mock,
        mock_get_provider: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test connection to specific provider by name."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        # Mock dependencies
        mock_keyring.set_password.return_value = None
        mock_keyring.get_password.return_value = "test-key"
        mock_provider_instance = MagicMock()
        mock_provider_instance.test_connection.return_value = True
        mock_get_provider.return_value = mock_provider_instance

        # Add two providers
        cli_runner.invoke(
            main,
            [
                "llm",
                "add",
                "--name",
                "provider-1",
                "--provider",
                "google",
                "--model",
                "gemini-1.5-flash",
                "--api-key",
                "key1",
            ],
            catch_exceptions=False,
        )
        cli_runner.invoke(
            main,
            [
                "llm",
                "add",
                "--name",
                "provider-2",
                "--provider",
                "google",
                "--model",
                "gemini-1.5-pro",
                "--api-key",
                "key2",
            ],
            catch_exceptions=False,
        )

        # Test specific provider
        result = cli_runner.invoke(
            main, ["llm", "test", "provider-2"], catch_exceptions=False
        )

        assert result.exit_code == 0
        assert "Testing connection to 'provider-2'..." in result.output
        assert "Connection successful!" in result.output

    @patch("docman.cli.get_llm_provider")
    @patch("docman.llm_config.keyring")
    def test_test_connection_failure(
        self,
        mock_keyring: Mock,
        mock_get_provider: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test handling of connection failure."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        # Mock dependencies
        mock_keyring.set_password.return_value = None
        mock_keyring.get_password.return_value = "test-key"
        mock_provider_instance = MagicMock()
        # First call succeeds (for add command), second call fails (for test command)
        mock_provider_instance.test_connection.side_effect = [
            True,
            Exception("Connection timeout"),
        ]
        mock_get_provider.return_value = mock_provider_instance

        # Add a provider
        cli_runner.invoke(
            main,
            [
                "llm",
                "add",
                "--name",
                "my-provider",
                "--provider",
                "google",
                "--model",
                "gemini-1.5-flash",
                "--api-key",
                "test-key",
            ],
            catch_exceptions=False,
        )

        # Test connection
        result = cli_runner.invoke(main, ["llm", "test"], catch_exceptions=False)

        assert result.exit_code == 1
        assert "Connection failed:" in result.output
        assert "Connection timeout" in result.output

    @patch("docman.cli.get_llm_provider")
    @patch("docman.llm_config.keyring")
    def test_test_missing_api_key(
        self,
        mock_keyring: Mock,
        mock_get_provider: Mock,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test error when API key is not found."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        # Mock dependencies
        mock_keyring.set_password.return_value = None
        # API key not found during test
        mock_keyring.get_password.return_value = None
        mock_provider_instance = MagicMock()
        mock_provider_instance.test_connection.return_value = True
        mock_get_provider.return_value = mock_provider_instance

        # Add a provider
        cli_runner.invoke(
            main,
            [
                "llm",
                "add",
                "--name",
                "my-provider",
                "--provider",
                "google",
                "--model",
                "gemini-1.5-flash",
                "--api-key",
                "test-key",
            ],
            catch_exceptions=False,
        )

        # Test connection
        result = cli_runner.invoke(main, ["llm", "test"], catch_exceptions=False)

        assert result.exit_code == 1
        assert "Error: API key not found for this provider." in result.output

    def test_test_no_active_provider(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test error when no active provider is configured."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        result = cli_runner.invoke(main, ["llm", "test"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "No active provider configured." in result.output
        assert "Run 'docman llm add' to add a provider." in result.output

    def test_test_nonexistent_provider(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test error when testing a nonexistent provider."""
        self.setup_isolated_env(tmp_path, monkeypatch)

        result = cli_runner.invoke(
            main, ["llm", "test", "nonexistent"], catch_exceptions=False
        )

        assert result.exit_code == 1
        assert "Error: Provider 'nonexistent' not found." in result.output
