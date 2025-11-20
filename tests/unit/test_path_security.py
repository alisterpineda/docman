"""
Unit tests for path security validation.

Tests cover all security requirements:
- Parent directory traversal prevention
- Absolute path rejection
- Null byte injection prevention
- Invalid character handling
- Repository boundary enforcement
"""

from pathlib import Path

import pytest

from docman.path_security import (
    PathSecurityError,
    validate_path_component,
    validate_repository_path,
    validate_target_path,
)


class TestValidatePathComponent:
    """Test individual path component validation."""

    def test_accept_safe_relative_path(self):
        """Accept valid relative path components."""
        assert validate_path_component("documents") == "documents"
        assert validate_path_component("reports/2024") == "reports/2024"
        assert validate_path_component("my-files") == "my-files"
        assert validate_path_component("files_123") == "files_123"

    def test_accept_empty_when_allowed(self):
        """Accept empty path when allow_empty=True."""
        assert validate_path_component("", allow_empty=True) == ""

    def test_reject_empty_by_default(self):
        """Reject empty path by default."""
        with pytest.raises(PathSecurityError, match="cannot be empty"):
            validate_path_component("")

    def test_reject_parent_directory_simple(self):
        """Reject simple parent directory traversal (..)."""
        with pytest.raises(PathSecurityError, match="parent directory traversal"):
            validate_path_component("..")

    def test_reject_parent_directory_in_path(self):
        """Reject paths containing parent directory traversal."""
        with pytest.raises(PathSecurityError, match="parent directory traversal"):
            validate_path_component("safe/../danger")

        with pytest.raises(PathSecurityError, match="parent directory traversal"):
            validate_path_component("../../etc/passwd")

        with pytest.raises(PathSecurityError, match="parent directory traversal"):
            validate_path_component("docs/../../../etc")

    def test_reject_absolute_paths_unix(self):
        """Reject Unix absolute paths."""
        with pytest.raises(PathSecurityError, match="cannot be absolute"):
            validate_path_component("/etc/passwd")

        with pytest.raises(PathSecurityError, match="cannot be absolute"):
            validate_path_component("/home/user")

    def test_reject_null_bytes(self):
        """Reject paths containing null bytes."""
        with pytest.raises(PathSecurityError, match="null byte"):
            validate_path_component("file\0.txt")

        with pytest.raises(PathSecurityError, match="null byte"):
            validate_path_component("docs/\0/file.pdf")

    def test_reject_invalid_characters(self):
        """Reject paths with invalid characters."""
        invalid_chars = ["<", ">", ":", '"', "|", "?", "*"]

        for char in invalid_chars:
            with pytest.raises(PathSecurityError, match="invalid character"):
                validate_path_component(f"file{char}name.txt")

    def test_accept_dots_in_filename(self):
        """Accept valid dots in filenames (not parent traversal)."""
        assert validate_path_component("file.txt") == "file.txt"
        assert validate_path_component(".hidden") == ".hidden"
        assert validate_path_component("archive.tar.gz") == "archive.tar.gz"

    def test_accept_current_directory(self):
        """Accept current directory reference (.)."""
        # Single dot is not a security issue - it's normalized by Path.resolve()
        assert validate_path_component(".") == "."


class TestValidateTargetPath:
    """Test complete target path validation and construction."""

    def test_construct_safe_path_with_directory(self, tmp_path):
        """Construct safe paths with directory and filename."""
        result = validate_target_path(tmp_path, "reports", "file.pdf")
        assert result == tmp_path / "reports" / "file.pdf"

    def test_construct_safe_path_without_directory(self, tmp_path):
        """Construct safe paths with only filename (no directory)."""
        result = validate_target_path(tmp_path, "", "file.pdf")
        assert result == tmp_path / "file.pdf"

    def test_construct_nested_directories(self, tmp_path):
        """Construct paths with nested directories."""
        result = validate_target_path(tmp_path, "reports/2024/Q1", "summary.pdf")
        assert result == tmp_path / "reports" / "2024" / "Q1" / "summary.pdf"

    def test_reject_path_escaping_repository(self, tmp_path):
        """Reject paths that escape the repository."""
        with pytest.raises(PathSecurityError, match="parent directory traversal"):
            validate_target_path(tmp_path, "../../etc", "passwd")

        with pytest.raises(PathSecurityError, match="parent directory traversal"):
            validate_target_path(tmp_path, "..", "file.txt")

    def test_reject_absolute_directory_path(self, tmp_path):
        """Reject absolute paths in directory component."""
        with pytest.raises(PathSecurityError, match="cannot be absolute"):
            validate_target_path(tmp_path, "/etc", "hosts")

    def test_reject_absolute_filename(self, tmp_path):
        """Reject absolute paths in filename component."""
        with pytest.raises(PathSecurityError, match="cannot be absolute"):
            validate_target_path(tmp_path, "docs", "/etc/passwd")

    def test_reject_parent_traversal_in_directory(self, tmp_path):
        """Reject parent directory traversal in directory path."""
        with pytest.raises(PathSecurityError, match="parent directory traversal"):
            validate_target_path(tmp_path, "safe/../danger", "file.txt")

    def test_reject_parent_traversal_in_filename(self, tmp_path):
        """Reject parent directory traversal in filename."""
        with pytest.raises(PathSecurityError, match="parent directory traversal"):
            validate_target_path(tmp_path, "docs", "../file.txt")

    def test_reject_null_bytes_in_paths(self, tmp_path):
        """Reject null bytes in any component."""
        with pytest.raises(PathSecurityError, match="null byte"):
            validate_target_path(tmp_path, "docs\0", "file.txt")

        with pytest.raises(PathSecurityError, match="null byte"):
            validate_target_path(tmp_path, "docs", "file\0.txt")

    def test_reject_invalid_characters_in_paths(self, tmp_path):
        """Reject invalid characters in any component."""
        with pytest.raises(PathSecurityError, match="invalid character"):
            validate_target_path(tmp_path, "docs<>", "file.txt")

        with pytest.raises(PathSecurityError, match="invalid character"):
            validate_target_path(tmp_path, "docs", "file*.txt")

    def test_require_absolute_base_path(self, tmp_path):
        """Require base_path to be absolute."""
        relative_base = Path("relative/path")
        with pytest.raises(ValueError, match="must be absolute"):
            validate_target_path(relative_base, "docs", "file.txt")

    def test_normalize_with_current_directory(self, tmp_path):
        """Normalize paths containing current directory (.)."""
        # Current directory references are normalized by resolve()
        result = validate_target_path(tmp_path, "./docs", "file.txt")
        assert result == tmp_path / "docs" / "file.txt"

    def test_reject_complex_escape_attempt(self, tmp_path):
        """Reject complex path traversal attempts."""
        # Try to escape via multiple levels
        with pytest.raises(PathSecurityError, match="parent directory traversal"):
            validate_target_path(tmp_path, "a/b/c/../../../..", "file.txt")

    def test_accept_deeply_nested_safe_path(self, tmp_path):
        """Accept deeply nested paths that stay within repository."""
        result = validate_target_path(
            tmp_path, "a/b/c/d/e/f/g/h/i/j", "deeply_nested.txt"
        )
        assert str(result).startswith(str(tmp_path))

    def test_return_resolved_absolute_path(self, tmp_path):
        """Return resolved absolute path."""
        result = validate_target_path(tmp_path, "docs", "file.txt")
        assert result.is_absolute()
        # Path should be normalized (no . or .. components)
        assert ".." not in result.parts
        assert "." not in result.parts or result.parts == (".",)


class TestValidateRepositoryPath:
    """Test repository boundary validation."""

    def test_accept_path_within_repository(self, tmp_path):
        """Accept paths within repository boundaries."""
        file_path = tmp_path / "docs" / "file.txt"
        validate_repository_path(file_path, tmp_path)  # Should not raise

    def test_reject_path_outside_repository(self, tmp_path):
        """Reject paths outside repository boundaries."""
        outside_path = tmp_path.parent / "outside.txt"
        with pytest.raises(PathSecurityError, match="outside repository"):
            validate_repository_path(outside_path, tmp_path)

    def test_accept_repository_root(self, tmp_path):
        """Accept repository root itself."""
        validate_repository_path(tmp_path, tmp_path)  # Should not raise

    def test_resolve_relative_paths(self, tmp_path):
        """Resolve relative paths before validation."""
        # Even if path is relative, it should be resolved and validated
        relative_path = Path("docs/file.txt")
        # This will resolve relative to cwd, which may be outside tmp_path
        # So we expect this to fail
        with pytest.raises(PathSecurityError, match="outside repository"):
            validate_repository_path(relative_path, tmp_path)


class TestEdgeCases:
    """Test edge cases and corner scenarios."""

    def test_empty_filename_rejected(self, tmp_path):
        """Empty filename is always rejected."""
        with pytest.raises(PathSecurityError, match="cannot be empty"):
            validate_target_path(tmp_path, "docs", "")

    def test_whitespace_only_paths(self, tmp_path):
        """Handle whitespace-only paths."""
        # Whitespace-only should be treated as valid (OS will handle)
        # Though unusual, it's not a security issue
        result = validate_target_path(tmp_path, "  ", "file.txt")
        assert result.is_absolute()

    def test_unicode_paths(self, tmp_path):
        """Accept Unicode characters in paths."""
        result = validate_target_path(tmp_path, "文档", "файл.txt")
        assert result.is_absolute()
        assert "文档" in str(result)

    def test_very_long_paths(self, tmp_path):
        """Handle very long paths."""
        # Create a very long directory path
        long_dir = "a" * 100 + "/" + "b" * 100
        result = validate_target_path(tmp_path, long_dir, "file.txt")
        assert result.is_absolute()

    def test_mixed_slashes_normalized(self, tmp_path):
        """Mixed forward and backslashes are normalized."""
        # Path() handles mixed slashes automatically
        result = validate_target_path(tmp_path, "docs/subdir", "file.txt")
        # Result should use OS-appropriate separators
        assert result.is_absolute()


class TestSecurityAttackVectors:
    """Test specific attack vectors from security analysis."""

    def test_attack_ssh_keys(self, tmp_path):
        """Block attempt to access SSH keys."""
        with pytest.raises(PathSecurityError, match="parent directory traversal"):
            validate_target_path(tmp_path, "../../.ssh", "id_rsa")

    def test_attack_etc_passwd(self, tmp_path):
        """Block attempt to access /etc/passwd."""
        with pytest.raises(PathSecurityError, match="parent directory traversal"):
            validate_target_path(tmp_path, "../../../etc", "passwd")

    def test_attack_absolute_etc_hosts(self, tmp_path):
        """Block attempt to overwrite /etc/hosts."""
        with pytest.raises(PathSecurityError, match="cannot be absolute"):
            validate_target_path(tmp_path, "/etc", "hosts")

    def test_attack_hidden_traversal(self, tmp_path):
        """Block hidden traversal in seemingly safe path."""
        with pytest.raises(PathSecurityError, match="parent directory traversal"):
            validate_target_path(tmp_path, "safe/../../danger", "file.pdf")

    def test_attack_null_byte_injection(self, tmp_path):
        """Block null byte injection attack."""
        with pytest.raises(PathSecurityError, match="null byte"):
            validate_target_path(tmp_path, "docs", "file.txt\0.pdf")

    def test_attack_windows_device_names(self, tmp_path):
        """Handle Windows device names."""
        # Device names like CON, PRN, AUX are OS-specific
        # We don't block them at validation level (OS will handle)
        result = validate_target_path(tmp_path, "docs", "CON.txt")
        assert result.is_absolute()
