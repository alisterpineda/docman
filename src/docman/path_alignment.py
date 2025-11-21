"""Path alignment validation for docman.

This module validates whether a suggested directory path aligns with
the folder structure defined in the repository configuration.
"""

from .repo_config import FolderDefinition, VariablePattern


def _is_variable_pattern(folder_name: str) -> bool:
    """Check if a folder name is a variable pattern placeholder.

    Args:
        folder_name: The folder name to check (e.g., "{year}", "invoices").

    Returns:
        True if it's a variable pattern (e.g., "{year}"), False otherwise.
    """
    return folder_name.startswith("{") and folder_name.endswith("}")


def _extract_variable_name(pattern: str) -> str:
    """Extract the variable name from a pattern placeholder.

    Args:
        pattern: The pattern placeholder (e.g., "{year}").

    Returns:
        The variable name (e.g., "year").
    """
    return pattern[1:-1]


def _check_value_against_pattern(
    value: str,
    var_name: str,
    var_patterns: dict[str, VariablePattern],
) -> tuple[bool, str | None]:
    """Check if a value is valid for a variable pattern.

    Args:
        value: The actual value from the path (e.g., "2024").
        var_name: The variable name (e.g., "year").
        var_patterns: Dictionary of variable pattern definitions.

    Returns:
        (is_valid, warning_message)
        - (True, None) if valid or can't be validated
        - (False, message) if invalid (value not in predefined list)
    """
    # If the variable pattern isn't defined, treat as valid (can't validate)
    if var_name not in var_patterns:
        return True, None

    pattern = var_patterns[var_name]

    # If no predefined values, treat as valid (can't validate)
    if not pattern.values:
        return True, None

    # Check against predefined values and their aliases
    for pattern_value in pattern.values:
        if value == pattern_value.value:
            return True, None
        if value in pattern_value.aliases:
            return True, None

    return (
        False,
        f'"{value}" is not a known value for {{{var_name}}}',
    )


def check_path_alignment(
    suggested_dir: str,
    folder_defs: dict[str, FolderDefinition],
    var_patterns: dict[str, VariablePattern],
) -> tuple[bool, str | None]:
    """Check if a suggested directory path aligns with the defined folder structure.

    Traverses the folder definition tree and validates each path component
    against literal folder names or variable patterns.

    Args:
        suggested_dir: The suggested directory path (e.g., "Financial/invoices/2024").
        folder_defs: Dictionary of top-level folder definitions.
        var_patterns: Dictionary of variable pattern definitions.

    Returns:
        (is_aligned, warning_message)
        - (True, None) if the path aligns or no definitions exist
        - (False, warning_message) if the path doesn't align
    """
    # If no folder definitions, skip check
    if not folder_defs:
        return True, None

    # If empty path (root), it's valid
    if not suggested_dir or not suggested_dir.strip():
        return True, None

    # Split path into components
    components = [c.strip() for c in suggested_dir.split("/") if c.strip()]
    if not components:
        return True, None

    # Start traversing the folder tree
    current_level = folder_defs
    path_so_far = ""

    for component in components:
        if not current_level:
            # No more defined folders at this level, but path continues
            # This is acceptable - we don't enforce full hierarchy depth
            return True, None

        # Try to find a matching folder at this level
        matched = False
        matched_folder: FolderDefinition | None = None
        variable_warning: str | None = None

        # First, try exact match with literal folder names
        if component in current_level:
            matched = True
            matched_folder = current_level[component]
        else:
            # Look for variable patterns at this level
            for folder_name, folder_def in current_level.items():
                if _is_variable_pattern(folder_name):
                    # This is a variable pattern - it can match any value
                    var_name = _extract_variable_name(folder_name)

                    # Check if value is valid for this pattern
                    is_valid, warning = _check_value_against_pattern(
                        component, var_name, var_patterns
                    )

                    if is_valid:
                        # Found a valid match - use it and clear any previous warning
                        matched = True
                        matched_folder = folder_def
                        variable_warning = None
                        break
                    else:
                        # This variable pattern exists but can't validate the value
                        # Save as potential match but continue checking other patterns
                        if not matched:
                            variable_warning = warning
                            matched = True
                            matched_folder = folder_def
                        # Don't break - continue checking other patterns

        if not matched:
            # No match found at this level
            if path_so_far:
                return (
                    False,
                    f'Path doesn\'t match folder structure: "{component}" '
                    f'is not a defined folder under "{path_so_far}"',
                )
            else:
                return (
                    False,
                    f'Path doesn\'t match folder structure: "{component}" '
                    f"is not a defined folder",
                )

        # If we have a variable warning, return it
        if variable_warning:
            return False, f"Path alignment: {variable_warning}"

        # Update path tracking
        if path_so_far:
            path_so_far = f"{path_so_far}/{component}"
        else:
            path_so_far = component

        # Move to next level
        if matched_folder:
            current_level = matched_folder.folders
        else:
            current_level = {}

    return True, None
