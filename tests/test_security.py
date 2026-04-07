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
    decrypt,
    encrypt,
    generate_auth_token,
    generate_encryption_key,
    load_or_create_key,
    load_or_create_token,
    secure_dir,
    secure_file,
    validate_bind_address,
    verify_token,
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


# ── Authentication ───────────────────────────────────────────────────────


class TestAuthToken:
    def test_generate_auth_token_format(self):
        token = generate_auth_token()
        assert isinstance(token, str)
        assert len(token) == 43  # secrets.token_urlsafe(32) produces 43 chars

    def test_generate_auth_token_unique(self):
        assert generate_auth_token() != generate_auth_token()

    def test_verify_token_correct(self):
        assert verify_token("my-secret", "my-secret") is True

    def test_verify_token_wrong(self):
        assert verify_token("wrong", "my-secret") is False

    def test_verify_token_empty(self):
        assert verify_token("", "my-secret") is False

    def test_load_or_create_token_creates(self, monkeypatch):
        """Token is created and returned on first call (file fallback)."""
        # Force keyring to fail so we test file fallback
        monkeypatch.setattr("mempalace.security._try_keyring_get", lambda account: None)
        monkeypatch.setattr("mempalace.security._try_keyring_set", lambda account, value: False)
        d = tempfile.mkdtemp()
        token = load_or_create_token(d)
        assert isinstance(token, str)
        assert len(token) == 43
        # Token file exists with restrictive permissions
        token_path = os.path.join(d, "auth_token")
        assert os.path.exists(token_path)
        if sys.platform != "win32":
            mode = stat.S_IMODE(os.stat(token_path).st_mode)
            assert mode == 0o600

    def test_load_or_create_token_reads_existing(self, monkeypatch):
        """Second call returns the same token."""
        monkeypatch.setattr("mempalace.security._try_keyring_get", lambda account: None)
        monkeypatch.setattr("mempalace.security._try_keyring_set", lambda account, value: False)
        d = tempfile.mkdtemp()
        token1 = load_or_create_token(d)
        token2 = load_or_create_token(d)
        assert token1 == token2


# ── Encryption ───────────────────────────────────────────────────────────


class TestEncryption:
    def test_generate_encryption_key(self):
        key = generate_encryption_key()
        assert isinstance(key, bytes)
        assert len(key) == 44  # Fernet key is 44 bytes base64-encoded

    def test_encrypt_decrypt_roundtrip(self):
        from cryptography.fernet import Fernet

        f = Fernet(Fernet.generate_key())
        plaintext = "This is sensitive palace data about family relationships."
        ciphertext = encrypt(f, plaintext)
        assert ciphertext != plaintext
        assert decrypt(f, ciphertext) == plaintext

    def test_encrypt_produces_different_ciphertext(self):
        """Fernet uses random IV, so two encryptions of the same text differ."""
        from cryptography.fernet import Fernet

        f = Fernet(Fernet.generate_key())
        plaintext = "same input"
        ct1 = encrypt(f, plaintext)
        ct2 = encrypt(f, plaintext)
        assert ct1 != ct2
        # Both decrypt to same plaintext
        assert decrypt(f, ct1) == plaintext
        assert decrypt(f, ct2) == plaintext

    def test_decrypt_wrong_key_fails(self):
        from cryptography.fernet import Fernet, InvalidToken

        f1 = Fernet(Fernet.generate_key())
        f2 = Fernet(Fernet.generate_key())
        ciphertext = encrypt(f1, "secret")
        with pytest.raises(InvalidToken):
            decrypt(f2, ciphertext)

    def test_load_or_create_key_creates(self, monkeypatch):
        """Key is created and returned on first call (file fallback)."""
        monkeypatch.setattr("mempalace.security._try_keyring_get", lambda account: None)
        monkeypatch.setattr("mempalace.security._try_keyring_set", lambda account, value: False)
        d = tempfile.mkdtemp()
        fernet = load_or_create_key(d)
        # Verify it's a working Fernet instance
        ct = encrypt(fernet, "test")
        assert decrypt(fernet, ct) == "test"
        # Key file exists
        assert os.path.exists(os.path.join(d, "palace.key"))

    def test_load_or_create_key_reads_existing(self, monkeypatch):
        """Second call returns a Fernet with the same key."""
        monkeypatch.setattr("mempalace.security._try_keyring_get", lambda account: None)
        monkeypatch.setattr("mempalace.security._try_keyring_set", lambda account, value: False)
        d = tempfile.mkdtemp()
        f1 = load_or_create_key(d)
        f2 = load_or_create_key(d)
        # Both should decrypt each other's ciphertext
        ct = encrypt(f1, "cross-test")
        assert decrypt(f2, ct) == "cross-test"
