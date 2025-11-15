"""Repository-level configuration management for docman.

This module handles reading and writing repository-specific configuration,
particularly folder definitions stored in .docman/config.yaml.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class FolderDefinition:
    """Represents a folder with its description and nested subfolders.

    Attributes:
        description: Human-readable description of what belongs in this folder.
            Optional - can be None if folder structure is self-documenting via
            variable patterns and context.
        folders: Dictionary mapping folder names to their FolderDefinition objects.
        filename_convention: Optional filename template pattern for files in this folder.
            Uses variable placeholders like {year}, {month}, {description}, etc.
            If None, inherits from parent folder or uses repository default.
            Example: "{year}-{month}-invoice" (extension preserved automatically)
    """

    description: str | None = None
    folders: dict[str, "FolderDefinition"] = field(default_factory=dict)
    filename_convention: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation for YAML serialization.

        Returns:
            Dictionary with optional 'description', optional 'filename_convention',
            and 'folders' keys. Description key is omitted if None for cleaner YAML.
        """
        result: dict[str, Any] = {}
        if self.description is not None:
            result["description"] = self.description
        if self.filename_convention is not None:
            result["filename_convention"] = self.filename_convention
        if self.folders:
            result["folders"] = {
                name: folder.to_dict() for name, folder in self.folders.items()
            }
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FolderDefinition":
        """Create FolderDefinition from dictionary representation.

        Args:
            data: Dictionary with optional 'description', optional 'filename_convention',
                and optional 'folders' keys.

        Returns:
            FolderDefinition instance.
        """
        description = data.get("description")
        # Normalize empty strings to None for backwards compatibility
        if description == "":
            description = None
        filename_convention = data.get("filename_convention")
        folders_data = data.get("folders", {})
        folders = {
            name: cls.from_dict(folder_data)
            for name, folder_data in folders_data.items()
        }
        return cls(
            description=description,
            folders=folders,
            filename_convention=filename_convention,
        )


def get_repo_config_path(repo_root: Path) -> Path:
    """Get the path to the repository's config file.

    Args:
        repo_root: The repository root directory.

    Returns:
        Path to .docman/config.yaml file.
    """
    return repo_root / ".docman" / "config.yaml"


def load_repo_config(repo_root: Path) -> dict[str, Any]:
    """Load repository configuration from .docman/config.yaml.

    Args:
        repo_root: The repository root directory.

    Returns:
        Dictionary containing configuration data. Returns empty dict if file
        doesn't exist or is empty.

    Raises:
        ValueError: If the YAML file contains syntax errors.
    """
    config_path = get_repo_config_path(repo_root)

    if not config_path.exists():
        return {}

    content = config_path.read_text()
    if not content.strip():
        return {}

    try:
        config = yaml.safe_load(content)
        return config if config is not None else {}
    except yaml.YAMLError as e:
        # Provide actionable error message for invalid YAML
        raise ValueError(
            f"Configuration file {config_path} contains invalid YAML syntax. "
            f"Please fix the syntax errors or delete the file to reset. "
            f"Error: {e}"
        ) from e


def save_repo_config(repo_root: Path, config: dict[str, Any]) -> None:
    """Save repository configuration to .docman/config.yaml.

    Creates .docman directory if it doesn't exist.

    Args:
        repo_root: The repository root directory.
        config: Dictionary containing configuration data to save.

    Raises:
        OSError: If file cannot be written.
    """
    config_path = get_repo_config_path(repo_root)

    # Ensure .docman directory exists
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Write config
    content = yaml.safe_dump(config, default_flow_style=False, sort_keys=False)
    config_path.write_text(content)


def get_folder_definitions(repo_root: Path) -> dict[str, FolderDefinition]:
    """Get folder definitions from repository config.

    Args:
        repo_root: The repository root directory.

    Returns:
        Dictionary mapping top-level folder names to FolderDefinition objects.
        Returns empty dict if no folders defined.
    """
    config = load_repo_config(repo_root)
    organization = config.get("organization", {})
    folders_data = organization.get("folders", {})

    return {
        name: FolderDefinition.from_dict(folder_data)
        for name, folder_data in folders_data.items()
    }


def add_folder_definition(
    repo_root: Path,
    path: str,
    description: str | None = None,
    filename_convention: str | None = None,
) -> None:
    """Add or update a folder definition.

    Parses the path (e.g., "Financial/invoices/{year}") and creates/updates
    the nested folder structure with the given description and optional filename convention.

    Args:
        repo_root: The repository root directory.
        path: Folder path, using '/' as separator (e.g., "Financial/invoices/{year}").
        description: Human-readable description of the folder. Optional - if None,
            preserves existing description when updating or omits it for new folders.
        filename_convention: Optional filename template pattern for this folder.

    Raises:
        ValueError: If path is empty or invalid.
        OSError: If config file cannot be written.
    """
    if not path or not path.strip():
        raise ValueError("Folder path cannot be empty")

    # Split path into components
    parts = [p.strip() for p in path.split("/") if p.strip()]
    if not parts:
        raise ValueError("Folder path cannot be empty")

    # Load existing config
    config = load_repo_config(repo_root)

    # Ensure organization.folders structure exists
    if "organization" not in config:
        config["organization"] = {}
    if "folders" not in config["organization"]:
        config["organization"]["folders"] = {}

    # Navigate/create the tree structure
    current_level = config["organization"]["folders"]
    for i, part in enumerate(parts):
        if part not in current_level:
            # Create new folder entry without description (will be added if provided)
            current_level[part] = {"folders": {}}

        # If this is the last part, update description and filename_convention
        if i == len(parts) - 1:
            # Only set description if explicitly provided (preserves existing or omits for new)
            if description is not None:
                current_level[part]["description"] = description
            if filename_convention is not None:
                current_level[part]["filename_convention"] = filename_convention
        else:
            # Ensure folders key exists for navigation
            if "folders" not in current_level[part]:
                current_level[part]["folders"] = {}
            current_level = current_level[part]["folders"]

    # Save updated config
    save_repo_config(repo_root, config)


def get_default_filename_convention(repo_root: Path) -> str | None:
    """Get the default filename convention for the repository.

    Args:
        repo_root: The repository root directory.

    Returns:
        Default filename convention string, or None if not set.
    """
    config = load_repo_config(repo_root)
    organization = config.get("organization", {})
    return organization.get("default_filename_convention")


def set_default_filename_convention(repo_root: Path, convention: str) -> None:
    """Set the default filename convention for the repository.

    Args:
        repo_root: The repository root directory.
        convention: Filename convention template pattern (e.g., "{year}-{month}-{description}").

    Raises:
        ValueError: If convention is empty.
        OSError: If config file cannot be written.
    """
    if not convention or not convention.strip():
        raise ValueError("Filename convention cannot be empty")

    # Load existing config
    config = load_repo_config(repo_root)

    # Ensure organization structure exists
    if "organization" not in config:
        config["organization"] = {}

    # Set default convention
    config["organization"]["default_filename_convention"] = convention.strip()

    # Save updated config
    save_repo_config(repo_root, config)


def get_variable_patterns(repo_root: Path) -> dict[str, str]:
    """Get variable pattern definitions from repository config.

    Args:
        repo_root: The repository root directory.

    Returns:
        Dictionary mapping variable names to descriptions.
        Returns empty dict if no patterns defined.
    """
    config = load_repo_config(repo_root)
    organization = config.get("organization", {})
    return organization.get("variable_patterns", {})


def set_variable_pattern(repo_root: Path, name: str, description: str) -> None:
    """Add or update a variable pattern definition.

    Args:
        repo_root: The repository root directory.
        name: Variable name (e.g., "year", "category").
        description: Human-readable description of the variable.

    Raises:
        ValueError: If name or description is empty.
        OSError: If config file cannot be written.
    """
    if not name or not name.strip():
        raise ValueError("Variable name cannot be empty")
    if not description or not description.strip():
        raise ValueError("Variable description cannot be empty")

    # Load existing config
    config = load_repo_config(repo_root)

    # Ensure organization.variable_patterns structure exists
    if "organization" not in config:
        config["organization"] = {}
    if "variable_patterns" not in config["organization"]:
        config["organization"]["variable_patterns"] = {}

    # Set pattern
    config["organization"]["variable_patterns"][name.strip()] = description.strip()

    # Save updated config
    save_repo_config(repo_root, config)


def remove_variable_pattern(repo_root: Path, name: str) -> None:
    """Remove a variable pattern definition.

    Args:
        repo_root: The repository root directory.
        name: Variable name to remove.

    Raises:
        ValueError: If pattern doesn't exist.
        OSError: If config file cannot be written.
    """
    if not name or not name.strip():
        raise ValueError("Variable name cannot be empty")

    # Load existing config
    config = load_repo_config(repo_root)

    # Check if pattern exists
    organization = config.get("organization", {})
    patterns = organization.get("variable_patterns", {})

    if name.strip() not in patterns:
        raise ValueError(f"Variable pattern '{name}' not found")

    # Remove pattern
    del config["organization"]["variable_patterns"][name.strip()]

    # Save updated config
    save_repo_config(repo_root, config)
