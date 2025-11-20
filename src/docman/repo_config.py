"""Repository-level configuration management for docman.

This module handles reading and writing repository-specific configuration,
particularly folder definitions stored in .docman/config.yaml.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class PatternValue:
    """Represents a predefined value for a variable pattern.

    Attributes:
        value: The canonical value (e.g., "Acme Corp.").
        description: Optional description of this value.
        aliases: Alternative names that should map to this value.
    """

    value: str
    description: str | None = None
    aliases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation for YAML serialization."""
        result: dict[str, Any] = {"value": self.value}
        if self.description is not None:
            result["description"] = self.description
        if self.aliases:
            result["aliases"] = self.aliases
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PatternValue":
        """Create PatternValue from dictionary representation."""
        return cls(
            value=data["value"],
            description=data.get("description"),
            aliases=data.get("aliases", []),
        )


@dataclass
class VariablePattern:
    """Represents a variable pattern with optional predefined values.

    Attributes:
        description: Human-readable description of the pattern.
        values: List of predefined values with optional aliases.
    """

    description: str
    values: list[PatternValue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation for YAML serialization.

        Returns simple string format if no values defined (backward compatible).
        """
        if not self.values:
            # Simple format: just the description string
            return self.description  # type: ignore
        # Extended format with values
        result: dict[str, Any] = {"description": self.description}
        result["values"] = [v.to_dict() for v in self.values]
        return result

    @classmethod
    def from_dict(cls, data: str | dict[str, Any]) -> "VariablePattern":
        """Create VariablePattern from dictionary or string representation.

        Supports both simple string format (backward compatible) and
        extended dict format with values.
        """
        if isinstance(data, str):
            # Simple format: just description
            return cls(description=data)
        # Extended format
        return cls(
            description=data["description"],
            values=[PatternValue.from_dict(v) for v in data.get("values", [])],
        )


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


def _validate_no_duplicate_variable_siblings(
    siblings: dict[str, Any], new_part: str, full_path: str
) -> None:
    """Validate that adding new_part doesn't create duplicate variable patterns.

    At any given level, you cannot have multiple DIFFERENT variable patterns
    as siblings. The same variable pattern is allowed (for extending paths),
    and mixing literals with variables is allowed.

    Args:
        siblings: Dictionary of existing siblings at this level.
        new_part: The new folder name to add.
        full_path: Full path being defined (for error messages).

    Raises:
        ValueError: If adding new_part would create duplicate variable patterns.
    """
    is_variable = new_part.startswith("{") and new_part.endswith("}")

    if not is_variable:
        return  # Literals don't create conflicts

    # Find any existing variable siblings
    variable_siblings = [
        k for k in siblings.keys() if k.startswith("{") and k.endswith("}")
    ]

    if variable_siblings:
        # There's already a variable sibling
        if variable_siblings[0] != new_part:
            # Different variable pattern - not allowed
            raise ValueError(
                f"Cannot define '{full_path}': Multiple different variable patterns "
                f"are not allowed at the same level. '{variable_siblings[0]}' already "
                f"exists as a sibling."
            )


def _validate_folder_tree(folders_data: dict[str, Any], path_prefix: str = "") -> None:
    """Recursively validate folder tree for duplicate variable patterns.

    Ensures that at any level, there are no multiple different variable patterns
    as siblings.

    Args:
        folders_data: Dictionary of folder definitions at this level.
        path_prefix: Current path prefix for error messages (e.g., "Financial/invoices").

    Raises:
        ValueError: If duplicate variable patterns are found at any level.
    """
    # Check for duplicate variable patterns at this level
    variable_folders = [
        name for name in folders_data.keys() if name.startswith("{") and name.endswith("}")
    ]

    if len(variable_folders) > 1:
        # Multiple different variable patterns at same level
        path_display = path_prefix if path_prefix else "root level"
        raise ValueError(
            f"Invalid folder structure at '{path_display}': Multiple different "
            f"variable patterns are not allowed at the same level. "
            f"Found: {', '.join(variable_folders)}"
        )

    # Recursively validate subfolders
    for folder_name, folder_data in folders_data.items():
        if "folders" in folder_data and folder_data["folders"]:
            # Build path for nested validation
            current_path = f"{path_prefix}/{folder_name}" if path_prefix else folder_name
            _validate_folder_tree(folder_data["folders"], current_path)


def get_folder_definitions(repo_root: Path) -> dict[str, FolderDefinition]:
    """Get folder definitions from repository config.

    Args:
        repo_root: The repository root directory.

    Returns:
        Dictionary mapping top-level folder names to FolderDefinition objects.
        Returns empty dict if no folders defined.

    Raises:
        ValueError: If the folder structure contains duplicate variable patterns.
    """
    config = load_repo_config(repo_root)
    organization = config.get("organization", {})
    folders_data = organization.get("folders", {})

    # Validate folder structure before returning
    if folders_data:
        _validate_folder_tree(folders_data)

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
            # Validate no duplicate variable siblings before creating
            _validate_no_duplicate_variable_siblings(current_level, part, path)
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
    convention = organization.get("default_filename_convention")
    return convention if isinstance(convention, str) else None


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


def get_variable_patterns(repo_root: Path) -> dict[str, VariablePattern]:
    """Get variable pattern definitions from repository config.

    Handles both simple string format (backward compatible) and extended
    dict format with values.

    Args:
        repo_root: The repository root directory.

    Returns:
        Dictionary mapping variable names to VariablePattern objects.
        Returns empty dict if no patterns defined.
    """
    config = load_repo_config(repo_root)
    organization = config.get("organization", {})
    patterns_data = organization.get("variable_patterns", {})

    if not isinstance(patterns_data, dict):
        return {}

    # Normalize all patterns to VariablePattern objects
    result: dict[str, VariablePattern] = {}
    for name, data in patterns_data.items():
        result[name] = VariablePattern.from_dict(data)

    return result


def get_variable_pattern_descriptions(repo_root: Path) -> dict[str, str]:
    """Get variable pattern descriptions from repository config.

    Convenience function for backward compatibility that returns just
    the description strings.

    Args:
        repo_root: The repository root directory.

    Returns:
        Dictionary mapping variable names to descriptions.
        Returns empty dict if no patterns defined.
    """
    patterns = get_variable_patterns(repo_root)
    return {name: pattern.description for name, pattern in patterns.items()}


def set_variable_pattern(repo_root: Path, name: str, description: str) -> None:
    """Add or update a variable pattern definition.

    Updates only the description. If the pattern has values, they are preserved.
    If updating an existing pattern with values, only the description is changed.

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

    name = name.strip()
    description = description.strip()

    # Check if pattern already exists with values
    existing = config["organization"]["variable_patterns"].get(name)
    if isinstance(existing, dict) and "values" in existing:
        # Preserve values, update description
        config["organization"]["variable_patterns"][name]["description"] = description
    else:
        # Simple format (no values)
        config["organization"]["variable_patterns"][name] = description

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


def get_pattern_values(repo_root: Path, pattern_name: str) -> list[PatternValue]:
    """Get predefined values for a variable pattern.

    Args:
        repo_root: The repository root directory.
        pattern_name: Name of the variable pattern.

    Returns:
        List of PatternValue objects for this pattern.
        Returns empty list if pattern has no predefined values.

    Raises:
        ValueError: If pattern doesn't exist.
    """
    patterns = get_variable_patterns(repo_root)

    if pattern_name not in patterns:
        raise ValueError(f"Variable pattern '{pattern_name}' not found")

    return patterns[pattern_name].values


def add_pattern_value(
    repo_root: Path,
    pattern_name: str,
    value: str,
    description: str | None = None,
    alias_of: str | None = None,
) -> None:
    """Add a value to a variable pattern, or add an alias to an existing value.

    If alias_of is specified, the value is added as an alias to the canonical value.
    Otherwise, it's added as a new canonical value.

    Args:
        repo_root: The repository root directory.
        pattern_name: Name of the variable pattern.
        value: The value to add.
        description: Optional description (only for canonical values, not aliases).
        alias_of: If specified, add this value as an alias of the canonical value.

    Raises:
        ValueError: If pattern doesn't exist, value already exists, or alias_of not found.
        OSError: If config file cannot be written.
    """
    if not value or not value.strip():
        raise ValueError("Value cannot be empty")

    value = value.strip()

    # Load existing config
    config = load_repo_config(repo_root)

    # Ensure organization.variable_patterns structure exists
    organization = config.get("organization", {})
    patterns = organization.get("variable_patterns", {})

    if pattern_name not in patterns:
        raise ValueError(f"Variable pattern '{pattern_name}' not found")

    # Get current pattern data
    pattern_data = patterns[pattern_name]

    # Convert simple string format to extended format if needed
    if isinstance(pattern_data, str):
        pattern_data = {"description": pattern_data, "values": []}
        config["organization"]["variable_patterns"][pattern_name] = pattern_data
    elif "values" not in pattern_data:
        pattern_data["values"] = []

    # Check for duplicate values and aliases
    for pv in pattern_data["values"]:
        if pv["value"] == value:
            raise ValueError(f"Value '{value}' already exists for pattern '{pattern_name}'")
        if value in pv.get("aliases", []):
            raise ValueError(
                f"'{value}' already exists as an alias of '{pv['value']}' "
                f"for pattern '{pattern_name}'"
            )

    if alias_of:
        # Add as alias to existing canonical value
        alias_of = alias_of.strip()
        found = False
        for pv in pattern_data["values"]:
            if pv["value"] == alias_of:
                if "aliases" not in pv:
                    pv["aliases"] = []
                pv["aliases"].append(value)
                found = True
                break

        if not found:
            raise ValueError(
                f"Canonical value '{alias_of}' not found for pattern '{pattern_name}'"
            )
    else:
        # Add as new canonical value
        new_value: dict[str, Any] = {"value": value}
        if description:
            new_value["description"] = description.strip()
        pattern_data["values"].append(new_value)

    # Save updated config
    save_repo_config(repo_root, config)


def remove_pattern_value(repo_root: Path, pattern_name: str, value: str) -> None:
    """Remove a value or alias from a variable pattern.

    If the value is a canonical value, removes it and all its aliases.
    If the value is an alias, removes only the alias.

    Args:
        repo_root: The repository root directory.
        pattern_name: Name of the variable pattern.
        value: The value or alias to remove.

    Raises:
        ValueError: If pattern doesn't exist or value/alias not found.
        OSError: If config file cannot be written.
    """
    if not value or not value.strip():
        raise ValueError("Value cannot be empty")

    value = value.strip()

    # Load existing config
    config = load_repo_config(repo_root)

    # Ensure pattern exists
    organization = config.get("organization", {})
    patterns = organization.get("variable_patterns", {})

    if pattern_name not in patterns:
        raise ValueError(f"Variable pattern '{pattern_name}' not found")

    pattern_data = patterns[pattern_name]

    # Handle simple string format (no values to remove)
    if isinstance(pattern_data, str):
        raise ValueError(f"Value '{value}' not found for pattern '{pattern_name}'")

    if "values" not in pattern_data or not pattern_data["values"]:
        raise ValueError(f"Value '{value}' not found for pattern '{pattern_name}'")

    # Find and remove the value or alias
    found = False
    new_values = []

    for pv in pattern_data["values"]:
        if pv["value"] == value:
            # Found as canonical value - remove entire entry
            found = True
            continue  # Skip this entry

        # Check if it's an alias
        if value in pv.get("aliases", []):
            # Remove only the alias
            pv["aliases"] = [a for a in pv["aliases"] if a != value]
            if not pv["aliases"]:
                del pv["aliases"]
            found = True

        new_values.append(pv)

    if not found:
        raise ValueError(f"Value '{value}' not found for pattern '{pattern_name}'")

    pattern_data["values"] = new_values

    # If no values left, convert back to simple format
    if not pattern_data["values"]:
        config["organization"]["variable_patterns"][pattern_name] = pattern_data[
            "description"
        ]

    # Save updated config
    save_repo_config(repo_root, config)
