"""
test_security.py — Tests for the security module.
"""

import os
import stat
import sys
import tempfile

import pytest

from mempalace.security import (
    content_hash,
    secure_dir,
    secure_file,
    validate_bind_address,
)


# ── Hashing ──────────────────────────────────────────────────────────────


class TestContentHash:
    def test_returns_hex_string(self):
        result = content_hash("hello world")
        assert all(c in "0123456789abcdef" for c in result)

    def test_default_length_is_16(self):
        assert len(content_hash("test data")) == 16

    def test_custom_length(self):
        assert len(content_hash("test data", length=8)) == 8
        assert len(content_hash("test data", length=32)) == 32

    def test_deterministic(self):
        assert content_hash("same input") == content_hash("same input")

    def test_different_inputs_differ(self):
        assert content_hash("input a") != content_hash("input b")

    def test_uses_sha256(self):
        """Verify the output matches a known SHA-256 prefix."""
        import hashlib

        expected = hashlib.sha256(b"test").hexdigest()[:16]
        assert content_hash("test") == expected


# ── File Permissions ─────────────────────────────────────────────────────


@pytest.mark.skipif(sys.platform == "win32", reason="Unix permissions")
class TestFilePermissions:
    def test_secure_file_sets_600(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"secret")
            path = f.name
        try:
            secure_file(path)
            mode = stat.S_IMODE(os.stat(path).st_mode)
            assert mode == 0o600
        finally:
            os.unlink(path)

    def test_secure_dir_sets_700(self):
        d = tempfile.mkdtemp()
        try:
            secure_dir(d)
            mode = stat.S_IMODE(os.stat(d).st_mode)
            assert mode == 0o700
        finally:
            os.rmdir(d)

    def test_secure_file_nonexistent_does_not_raise(self):
        """Should log a warning but not crash."""
        secure_file("/nonexistent/path/to/file")

    def test_secure_dir_nonexistent_does_not_raise(self):
        """Should log a warning but not crash."""
        secure_dir("/nonexistent/path/to/dir")


# ── Localhost Validation ─────────────────────────────────────────────────


class TestValidateBindAddress:
    def test_allows_127_0_0_1(self):
        validate_bind_address("127.0.0.1")  # should not raise

    def test_allows_ipv6_loopback(self):
        validate_bind_address("::1")  # should not raise

    def test_allows_localhost(self):
        validate_bind_address("localhost")  # should not raise

    def test_rejects_0_0_0_0(self):
        with pytest.raises(ValueError, match="non-localhost"):
            validate_bind_address("0.0.0.0")

    def test_rejects_public_ip(self):
        with pytest.raises(ValueError, match="non-localhost"):
            validate_bind_address("192.168.1.1")

    def test_rejects_wildcard_ipv6(self):
        with pytest.raises(ValueError, match="non-localhost"):
            validate_bind_address("::")

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError, match="non-localhost"):
            validate_bind_address("")
