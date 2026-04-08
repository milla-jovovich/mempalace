"""
security.py — Centralized security primitives for MemPalace.

Provides:
  - File permission hardening (secure_file, secure_dir)
  - SHA-256 content hashing (replacing MD5)
  - Localhost bind address validation
  - Token-based authentication (generate, store, verify)
  - Fernet encryption at rest (encrypt, decrypt, key management)

All security features are opt-in. MemPalace works without them.
"""

import hashlib
import hmac
import logging
import os
import secrets
import sys
from pathlib import Path

logger = logging.getLogger("mempalace_security")

# ── File permissions ─────────────────────────────────────────────────────

_IS_WINDOWS = sys.platform == "win32"


def secure_file(path):
    """Set file to owner-only read/write (0o600). No-op on Windows."""
    if _IS_WINDOWS:
        return
    try:
        os.chmod(path, 0o600)
    except OSError as e:
        logger.warning("Could not set permissions on %s: %s", path, e)


def secure_dir(path):
    """Set directory to owner-only (0o700). No-op on Windows."""
    if _IS_WINDOWS:
        return
    try:
        os.chmod(path, 0o700)
    except OSError as e:
        logger.warning("Could not set permissions on %s: %s", path, e)


# ── Hashing ──────────────────────────────────────────────────────────────


def content_hash(data, length=16):
    """SHA-256 hash of data, truncated to `length` hex characters.

    Drop-in replacement for the old MD5-based ID generation.
    """
    return hashlib.sha256(data.encode()).hexdigest()[:length]


# ── Localhost validation ─────────────────────────────────────────────────

_LOCALHOST_ADDRESSES = frozenset({"127.0.0.1", "::1", "localhost"})


def validate_bind_address(host):
    """Raise ValueError if host is not a localhost address.

    Defensive guard for any future network transport — ensures the MCP
    server can never accidentally bind to a public interface.
    """
    if host not in _LOCALHOST_ADDRESSES:
        raise ValueError(
            f"Refusing to bind to non-localhost address '{host}'. "
            f"Allowed: {', '.join(sorted(_LOCALHOST_ADDRESSES))}"
        )


# ── Authentication ───────────────────────────────────────────────────────

_KEYRING_SERVICE = "mempalace"


def generate_auth_token():
    """Generate a URL-safe random auth token (43 characters)."""
    return secrets.token_urlsafe(32)


def _try_keyring_get(account):
    """Try to read a secret from the OS keychain. Returns None on failure."""
    try:
        import keyring

        return keyring.get_password(_KEYRING_SERVICE, account)
    except ImportError:
        logger.debug("keyring package not installed")
        return None
    except Exception as e:
        logger.warning("Failed to read from OS keychain: %s", e)
        return None


def _try_keyring_set(account, value):
    """Try to store a secret in the OS keychain. Returns True on success."""
    try:
        import keyring

        keyring.set_password(_KEYRING_SERVICE, account, value)
        return True
    except ImportError:
        logger.debug("keyring package not installed")
        return False
    except Exception as e:
        logger.warning("Failed to write to OS keychain: %s", e)
        return False


def load_or_create_token(config_dir):
    """Load auth token from OS keychain, falling back to file.

    Storage priority:
      1. OS Keychain (macOS Keychain / Windows Credential Manager / Linux Secret Service)
      2. File at {config_dir}/auth_token with 0o600 permissions

    Returns the token string.
    """
    account = "auth_token"

    # Try keychain first
    token = _try_keyring_get(account)
    if token:
        return token

    # Try file fallback
    token_path = Path(config_dir) / "auth_token"
    if token_path.exists():
        token = token_path.read_text().strip()
        # Migrate to keychain if possible
        _try_keyring_set(account, token)
        return token

    # Generate new token
    token = generate_auth_token()

    # Store in keychain
    if _try_keyring_set(account, token):
        logger.info("Auth token stored in OS keychain.")
    else:
        # Fall back to file
        logger.warning(
            "OS keychain unavailable. Storing auth token in file. "
            "Install 'keyring' for secure storage: pip install mempalace[security]",
        )
        config_path = Path(config_dir)
        config_path.mkdir(parents=True, exist_ok=True)
        secure_dir(config_path)
        token_path.write_text(token)
        secure_file(token_path)

    return token


def verify_token(provided, expected):
    """Constant-time token comparison to prevent timing attacks."""
    return hmac.compare_digest(provided, expected)


# ── Encryption ───────────────────────────────────────────────────────────


def _require_cryptography():
    """Import and return Fernet, raising a clear error if not installed."""
    try:
        from cryptography.fernet import Fernet

        return Fernet
    except ImportError:
        raise ImportError(
            "Encryption requires the 'cryptography' package. "
            "Install it with: pip install mempalace[security]"
        )


def generate_encryption_key():
    """Generate a new Fernet encryption key (bytes)."""
    Fernet = _require_cryptography()
    return Fernet.generate_key()


def load_or_create_key(config_dir):
    """Load encryption key from OS keychain, falling back to file.

    Storage priority:
      1. OS Keychain (macOS Keychain / Windows Credential Manager / Linux Secret Service)
      2. File at {config_dir}/palace.key with 0o600 permissions

    Returns a Fernet instance ready for encrypt/decrypt.
    """
    Fernet = _require_cryptography()
    account = "encryption_key"

    # Try keychain first
    key_str = _try_keyring_get(account)
    if key_str:
        return Fernet(key_str.encode())

    # Try file fallback
    key_path = Path(config_dir) / "palace.key"
    if key_path.exists():
        key_bytes = key_path.read_text().strip().encode()
        # Migrate to keychain if possible
        _try_keyring_set(account, key_bytes.decode())
        return Fernet(key_bytes)

    # Generate new key
    key_bytes = generate_encryption_key()

    # Store in keychain
    if _try_keyring_set(account, key_bytes.decode()):
        logger.info("Encryption key stored in OS keychain.")
    else:
        # Fall back to file
        logger.warning(
            "OS keychain unavailable. Storing encryption key in file. "
            "Install 'keyring' for secure storage: pip install mempalace[security]",
        )
        config_path = Path(config_dir)
        config_path.mkdir(parents=True, exist_ok=True)
        secure_dir(config_path)
        key_path.write_text(key_bytes.decode())
        secure_file(key_path)

    return Fernet(key_bytes)


def encrypt(fernet, plaintext):
    """Encrypt plaintext string, returning base64-encoded ciphertext string."""
    return fernet.encrypt(plaintext.encode()).decode()


def decrypt(fernet, ciphertext):
    """Decrypt base64-encoded ciphertext string, returning plaintext string."""
    return fernet.decrypt(ciphertext.encode()).decode()
