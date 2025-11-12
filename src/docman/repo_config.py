"""Repository-level configuration management for docman.

This module handles reading and writing repository-specific configuration,
particularly document organization instructions stored in .docman/instructions.md
and folder definitions stored in .docman/config.yaml.
"""

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Template for new instructions file
INSTRUCTIONS_TEMPLATE = """# Document Organization Instructions

Add your instructions here for how documents should be organized in this repository.

## Examples:
- Organize invoices by year and month (e.g., finance/invoices/2024/01/)
- Keep all contracts in legal/contracts/
- Use lowercase and hyphens for directory names
"""


@dataclass
class FolderDefinition:
    """Represents a folder with its description and nested subfolders.

    Attributes:
        description: Human-readable description of what belongs in this folder.
        folders: Dictionary mapping folder names to their FolderDefinition objects.
        filename_convention: Optional filename template pattern for files in this folder.
            Uses variable placeholders like {year}, {month}, {description}, etc.
            If None, inherits from parent folder or uses repository default.
            Example: "{year}-{month}-invoice" (extension preserved automatically)
    """

    description: str
    folders: dict[str, "FolderDefinition"] = field(default_factory=dict)
    filename_convention: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation for YAML serialization.

        Returns:
            Dictionary with 'description', optional 'filename_convention', and 'folders' keys.
        """
        result: dict[str, Any] = {"description": self.description}
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
            data: Dictionary with 'description', optional 'filename_convention', and optional 'folders' keys.

        Returns:
            FolderDefinition instance.
        """
        description = data.get("description", "")
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
    description: str,
    filename_convention: str | None = None,
) -> None:
    """Add or update a folder definition.

    Parses the path (e.g., "Financial/invoices/{year}") and creates/updates
    the nested folder structure with the given description and optional filename convention.

    Args:
        repo_root: The repository root directory.
        path: Folder path, using '/' as separator (e.g., "Financial/invoices/{year}").
        description: Human-readable description of the folder.
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
            # Create new folder entry
            current_level[part] = {"description": "", "folders": {}}

        # If this is the last part, update description and filename_convention
        if i == len(parts) - 1:
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


def get_instructions_path(repo_root: Path) -> Path:
    """Get the path to the repository's document organization instructions file.

    Args:
        repo_root: The repository root directory.

    Returns:
        Path to .docman/instructions.md file.
    """
    return repo_root / ".docman" / "instructions.md"


def create_instructions_template(repo_root: Path) -> None:
    """Create instructions file with template content.

    Creates .docman directory if it doesn't exist.

    Args:
        repo_root: The repository root directory.

    Raises:
        OSError: If file cannot be written.
    """
    instructions_path = get_instructions_path(repo_root)
    instructions_path.parent.mkdir(parents=True, exist_ok=True)
    instructions_path.write_text(INSTRUCTIONS_TEMPLATE)


def load_instructions(repo_root: Path) -> str | None:
    """Load document organization instructions from the repository.

    Args:
        repo_root: The repository root directory.

    Returns:
        Instructions content, or None if not found or empty.
    """
    instructions_path = get_instructions_path(repo_root)

    if not instructions_path.exists():
        return None

    try:
        content = instructions_path.read_text().strip()
        return content if content else None
    except Exception:
        return None


def save_instructions(repo_root: Path, content: str) -> None:
    """Save document organization instructions to the repository.

    Creates .docman directory if it doesn't exist.

    Args:
        repo_root: The repository root directory.
        content: Instructions content to save.

    Raises:
        OSError: If file cannot be written.
    """
    instructions_path = get_instructions_path(repo_root)

    # Ensure .docman directory exists
    instructions_path.parent.mkdir(parents=True, exist_ok=True)

    # Write instructions
    instructions_path.write_text(content)


def edit_instructions_interactive(repo_root: Path) -> bool:
    """Open instructions file in user's preferred editor.

    Uses $EDITOR environment variable if set, otherwise falls back to
    sensible defaults (nano on Unix, notepad on Windows).

    If instructions file doesn't exist, creates it with a template.

    Args:
        repo_root: The repository root directory.

    Returns:
        True if editing was successful, False if editor not found or failed.

    Raises:
        OSError: If file operations fail.
    """
    instructions_path = get_instructions_path(repo_root)

    # Get editor from environment or use defaults
    editor = os.environ.get("EDITOR")

    if not editor:
        # Try common editors
        if os.name == "nt":  # Windows
            editor = "notepad"
        else:  # Unix-like
            # Try to find a suitable editor
            for candidate in ["nano", "vim", "vi"]:
                if subprocess.run(
                    ["which", candidate],
                    capture_output=True,
                    check=False,
                ).returncode == 0:
                    editor = candidate
                    break

    if not editor:
        return False

    # Create file with template if it doesn't exist
    if not instructions_path.exists():
        instructions_path.parent.mkdir(parents=True, exist_ok=True)
        instructions_path.write_text(INSTRUCTIONS_TEMPLATE)

    # Open editor
    try:
        subprocess.run([editor, str(instructions_path)], check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
