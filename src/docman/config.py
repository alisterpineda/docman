"""Application configuration management for docman.

This module handles the creation, reading, and writing of app-level
configuration stored in OS-specific application data directories.
"""

import os
from pathlib import Path
from typing import Any

import yaml
from platformdirs import user_config_dir


def get_app_config_dir() -> Path:
    """Get the application configuration directory path.

    The directory path is OS-dependent:
    - macOS: ~/Library/Application Support/docman
    - Linux: ~/.config/docman
    - Windows: %APPDATA%/docman

    Can be overridden for testing purposes using the DOCMAN_APP_CONFIG_DIR
    environment variable.

    Returns:
        Path object pointing to the app configuration directory.
    """
    override_dir = os.environ.get("DOCMAN_APP_CONFIG_DIR")
    if override_dir:
        return Path(override_dir)
    return Path(user_config_dir("docman", appauthor=False))


def get_app_config_path() -> Path:
    """Get the full path to the app configuration file.

    Returns:
        Path object pointing to config.yaml in the app config directory.
    """
    return get_app_config_dir() / "config.yaml"


def ensure_app_config() -> None:
    """Ensure the app configuration directory and file exist.

    Creates the configuration directory and an empty config.yaml file if they
    don't already exist. This operation is idempotent and safe to call multiple times.

    Raises:
        OSError: If directory or file creation fails due to permissions or other I/O errors.
    """
    config_dir = get_app_config_dir()
    config_file = get_app_config_path()

    # Create directory if it doesn't exist
    config_dir.mkdir(parents=True, exist_ok=True)

    # Create config file if it doesn't exist
    if not config_file.exists():
        config_file.write_text("{}\n")


def load_app_config() -> dict[str, Any]:
    """Load and parse the app configuration file.

    Ensures the configuration file exists before attempting to read it.
    If the file is empty or contains only whitespace, returns an empty dictionary.

    Returns:
        Dictionary containing the parsed configuration data.

    Raises:
        OSError: If the file cannot be read.
        yaml.YAMLError: If the file contains invalid YAML syntax.
    """
    ensure_app_config()
    config_file = get_app_config_path()

    content = config_file.read_text()
    if not content.strip():
        return {}

    config = yaml.safe_load(content)
    return config if config is not None else {}


def save_app_config(config: dict[str, Any]) -> None:
    """Save configuration data to the app configuration file.

    Ensures the configuration directory and file exist before writing.

    Args:
        config: Dictionary containing configuration data to save.

    Raises:
        OSError: If the file cannot be written.
        yaml.YAMLError: If the configuration data cannot be serialized to YAML.
    """
    ensure_app_config()
    config_file = get_app_config_path()

    content = yaml.safe_dump(config, default_flow_style=False, sort_keys=False)
    config_file.write_text(content)
