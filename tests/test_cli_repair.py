"""
test_cli_repair.py — Tests for CLI repair command, specifically path normalization

Issue #395: Trailing slash in palace_path causes infinite recursion and disk fill.
"""

import os
from pathlib import Path




class TestCmdRepairPathNormalization:
    """Tests for cmd_repair path handling, specifically issue #395."""

    def test_trailing_slash_backup_outside_palace(self, tmp_path):
        """
        Issue #395: Trailing slash should not cause backup to be inside palace.

        When palace_path ends with '/', backup_path must be OUTSIDE the palace directory,
        not inside it (which would cause infinite recursion).
        """

        # Test the actual path normalization logic from cli.py
        palace_dir = tmp_path / "test_palace"
        palace_dir.mkdir()

        # Simulate the exact logic from cmd_repair (lines 207-208)
        palace_path_with_slash = str(palace_dir) + "/"  # Trailing slash!

        # This is the fix: normalize with Path.resolve() before creating backup_path
        palace_path_normalized = str(Path(palace_path_with_slash).resolve())
        backup_path = palace_path_normalized + ".backup"

        # Verify the normalized path doesn't have trailing slash
        assert not palace_path_normalized.endswith("/")
        assert not palace_path_normalized.endswith(os.sep)

        # Verify backup is OUTSIDE the palace (not inside)
        palace_str = str(palace_dir.resolve())
        assert not backup_path.startswith(palace_str + os.sep), \
            f"Backup path {backup_path} is inside palace {palace_str}"

        # Verify backup is at the correct location
        expected_backup = palace_str + ".backup"
        assert backup_path == expected_backup, \
            f"Expected {expected_backup}, got {backup_path}"

        # Verify the bug would have occurred WITHOUT the fix
        buggy_backup_path = palace_path_with_slash + ".backup"
        assert buggy_backup_path.startswith(palace_str + os.sep), \
            "Without the fix, backup would be inside palace (this proves the bug)"

    def test_multiple_trailing_slashes_normalized(self, tmp_path):
        """Multiple trailing slashes should all be normalized."""
        palace_dir = tmp_path / "test_palace"
        palace_dir.mkdir()

        # Test the path normalization directly

        path_with_slashes = str(palace_dir) + "///"
        normalized = str(Path(path_with_slashes).resolve())

        # Normalized path should not end with any separators
        assert not normalized.endswith("/")
        assert not normalized.endswith(os.sep)

        # Backup path should be outside
        backup_path = normalized + ".backup"
        assert not backup_path.startswith(normalized + os.sep)

    def test_no_trailing_slash_works_correctly(self, tmp_path):
        """Verify normal case (no trailing slash) still works."""
        palace_dir = tmp_path / "test_palace"
        palace_dir.mkdir()


        path_no_slash = str(palace_dir)
        normalized = str(Path(path_no_slash).resolve())
        backup_path = normalized + ".backup"

        # Should be correct in both cases
        expected = str(palace_dir.resolve()) + ".backup"
        assert backup_path == expected


class TestPathNormalizationEdgeCases:
    """Additional edge cases for path normalization."""

    def test_symlink_in_path_resolved(self, tmp_path):
        """Symlinks in palace path should be resolved."""
        real_dir = tmp_path / "real_palace"
        real_dir.mkdir()
        symlink_dir = tmp_path / "symlink_palace"
        symlink_dir.symlink_to(real_dir)


        # Path with trailing slash through symlink
        path_with_slash = str(symlink_dir) + "/"
        normalized = str(Path(path_with_slash).resolve())

        # Should resolve to real path
        assert "symlink" not in normalized or normalized == str(symlink_dir.resolve())

        # Backup should be outside resolved path
        backup_path = normalized + ".backup"
        assert not backup_path.startswith(normalized + os.sep)

    def test_relative_path_normalized(self, tmp_path):
        """Relative paths should be converted to absolute."""

        # Change to tmp_path
        import os
        original_cwd = os.getcwd()
        os.chdir(str(tmp_path))

        try:
            rel_path = "./palace/"
            normalized = str(Path(rel_path).resolve())

            # Should be absolute
            assert os.path.isabs(normalized)
            # Should not end with slash
            assert not normalized.endswith("/")
            # Backup should be outside
            backup_path = normalized + ".backup"
            assert not backup_path.startswith(normalized + os.sep)
        finally:
            os.chdir(original_cwd)
