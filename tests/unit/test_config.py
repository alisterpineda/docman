"""Unit tests for the config module."""

from pathlib import Path

import pytest
import yaml

from docman.config import (
    ensure_app_config,
    get_app_config_dir,
    get_app_config_path,
    load_app_config,
    save_app_config,
)


class TestGetAppConfigDir:
    """Tests for get_app_config_dir function."""

    def test_env_var_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that DOCMAN_APP_CONFIG_DIR environment variable overrides default."""
        custom_dir = tmp_path / "custom_config"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(custom_dir))

        result = get_app_config_dir()
        assert result == custom_dir


class TestGetAppConfigPath:
    """Tests for get_app_config_path function."""

    def test_env_var_override_affects_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that env var override affects the config path."""
        custom_dir = tmp_path / "custom_config"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(custom_dir))

        result = get_app_config_path()
        assert result == custom_dir / "config.yaml"


class TestEnsureAppConfig:
    """Tests for ensure_app_config function."""

    def test_creates_config_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that the function creates the config directory."""
        config_dir = tmp_path / "test_docman"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(config_dir))

        ensure_app_config()

        assert config_dir.exists()
        assert config_dir.is_dir()

    def test_creates_config_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that the function creates the config file."""
        config_dir = tmp_path / "test_docman"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(config_dir))

        ensure_app_config()

        config_file = config_dir / "config.yaml"
        assert config_file.exists()
        assert config_file.is_file()

    def test_config_file_is_valid_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that the created config file contains valid YAML."""
        config_dir = tmp_path / "test_docman"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(config_dir))

        ensure_app_config()

        config_file = config_dir / "config.yaml"
        content = config_file.read_text()
        parsed = yaml.safe_load(content)
        assert parsed == {} or parsed is None

    def test_idempotent_directory_already_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that calling the function twice is safe (directory exists)."""
        config_dir = tmp_path / "test_docman"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(config_dir))

        ensure_app_config()
        ensure_app_config()  # Call again

        assert config_dir.exists()
        assert config_dir.is_dir()

    def test_idempotent_file_already_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that calling the function twice is safe (file exists)."""
        config_dir = tmp_path / "test_docman"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(config_dir))

        ensure_app_config()
        config_file = config_dir / "config.yaml"
        original_content = "key: value\n"
        config_file.write_text(original_content)

        ensure_app_config()  # Call again

        # File content should be preserved
        assert config_file.read_text() == original_content


class TestLoadAppConfig:
    """Tests for load_app_config function."""

    def test_returns_empty_dict_for_empty_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that loading an empty config file returns empty dict."""
        config_dir = tmp_path / "test_docman"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(config_dir))

        result = load_app_config()
        assert result == {}

    def test_returns_dict_for_valid_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that loading valid YAML returns correct dict."""
        config_dir = tmp_path / "test_docman"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(config_dir))

        # Create config with data
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.yaml"
        test_data = {"key1": "value1", "key2": {"nested": "value2"}}
        config_file.write_text(yaml.safe_dump(test_data))

        result = load_app_config()
        assert result == test_data

    def test_creates_config_if_not_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that load creates config if it doesn't exist."""
        config_dir = tmp_path / "test_docman"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(config_dir))

        # Ensure config doesn't exist yet
        assert not config_dir.exists()

        result = load_app_config()

        # Config should be created
        assert config_dir.exists()
        assert (config_dir / "config.yaml").exists()
        assert result == {}

    def test_raises_on_invalid_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that loading invalid YAML raises an error."""
        config_dir = tmp_path / "test_docman"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(config_dir))

        # Create invalid YAML
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.yaml"
        config_file.write_text("invalid: yaml: content: [")

        with pytest.raises(yaml.YAMLError):
            load_app_config()


class TestSaveAppConfig:
    """Tests for save_app_config function."""

    def test_creates_config_if_not_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that save creates config if it doesn't exist."""
        config_dir = tmp_path / "test_docman"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(config_dir))

        test_data = {"key": "value"}
        save_app_config(test_data)

        assert config_dir.exists()
        assert (config_dir / "config.yaml").exists()

    def test_saves_dict_as_yaml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that save writes dict as valid YAML."""
        config_dir = tmp_path / "test_docman"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(config_dir))

        test_data = {"key1": "value1", "key2": {"nested": "value2"}}
        save_app_config(test_data)

        config_file = config_dir / "config.yaml"
        loaded_data = yaml.safe_load(config_file.read_text())
        assert loaded_data == test_data

    def test_overwrites_existing_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that save overwrites existing config."""
        config_dir = tmp_path / "test_docman"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(config_dir))

        # Save initial data
        initial_data = {"old": "data"}
        save_app_config(initial_data)

        # Save new data
        new_data = {"new": "data"}
        save_app_config(new_data)

        config_file = config_dir / "config.yaml"
        loaded_data = yaml.safe_load(config_file.read_text())
        assert loaded_data == new_data
        assert "old" not in loaded_data

    def test_saves_empty_dict(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that save handles empty dict correctly."""
        config_dir = tmp_path / "test_docman"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(config_dir))

        save_app_config({})

        config_file = config_dir / "config.yaml"
        loaded_data = yaml.safe_load(config_file.read_text())
        assert loaded_data == {} or loaded_data is None

    def test_saves_nested_structures(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that save handles complex nested structures."""
        config_dir = tmp_path / "test_docman"
        monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(config_dir))

        test_data = {
            "level1": {
                "level2": {"level3": ["item1", "item2", "item3"]},
                "another_key": 42,
            },
            "list_data": [1, 2, 3],
        }
        save_app_config(test_data)

        config_file = config_dir / "config.yaml"
        loaded_data = yaml.safe_load(config_file.read_text())
        assert loaded_data == test_data
