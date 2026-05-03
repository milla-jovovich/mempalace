"""Tests for atexit hook registration, SIGTERM bridge, and ChromaBackend cache key normalization.

Covers:
  - atexit.register is called with _DEFAULT_BACKEND.close at import time
  - SIGTERM handler bridges to sys.exit(0) so atexit hooks fire on MCP kill
  - _DEFAULT_BACKEND.close() is idempotent (safe to call multiple times)
  - _cache_key() normalizes relative, absolute, and trailing-slash paths
  - close_palace() finds the cached client even when path formats diverge
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mempalace.backends.chroma import ChromaBackend


# ── atexit hook registration ──────────────────────────────────────────────


class TestAtexitRegistration:
    """Verify atexit.register is called for _DEFAULT_BACKEND.close."""

    def test_atexit_registered_at_import(self):
        """The palace module registers _DEFAULT_BACKEND.close via atexit."""
        import atexit

        # atexit._run_exitfuncs is CPython internal, but atexit callbacks
        # are visible via the _ncallbacks() count. Instead, we verify that
        # the _DEFAULT_BACKEND singleton's close method is registered by
        # checking that importing palace doesn't crash and the backend
        # has the expected close method that atexit would call.
        from mempalace.palace import _DEFAULT_BACKEND

        assert callable(_DEFAULT_BACKEND.close)
        assert isinstance(_DEFAULT_BACKEND, ChromaBackend)
        # Verify close is safe to call (what atexit will do)
        # We can't inspect atexit's internal list portably, but we can
        # verify the registration line exists in source as a structural test.
        import inspect

        source = inspect.getsource(
            __import__("mempalace.palace", fromlist=["_DEFAULT_BACKEND"])
        )
        assert "atexit.register(_DEFAULT_BACKEND.close)" in source


class TestCloseIdempotent:
    """Verify _DEFAULT_BACKEND.close() can be called multiple times safely."""

    def test_close_twice_does_not_raise(self):
        backend = ChromaBackend()
        backend.close()
        backend.close()  # Should not raise

    def test_close_clears_state(self):
        backend = ChromaBackend()
        backend.close()
        assert backend._closed is True
        assert len(backend._clients) == 0
        assert len(backend._freshness) == 0


# ── _cache_key normalization ──────────────────────────────────────────────


class TestCacheKey:
    """Verify _cache_key produces consistent keys for equivalent paths."""

    def test_relative_and_absolute_resolve_to_same_key(self, tmp_path):
        """./subdir and /abs/subdir resolve to the same cache key."""
        subdir = tmp_path / "palace"
        subdir.mkdir()
        absolute = str(subdir)
        # Build a relative path from cwd
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            relative = "./palace"
            assert ChromaBackend._cache_key(relative) == ChromaBackend._cache_key(absolute)
        finally:
            os.chdir(original_cwd)

    def test_trailing_slash_normalized(self, tmp_path):
        """Trailing slash doesn't create a different cache key."""
        palace = tmp_path / "palace"
        palace.mkdir()
        without_slash = str(palace)
        with_slash = str(palace) + "/"
        assert ChromaBackend._cache_key(without_slash) == ChromaBackend._cache_key(with_slash)

    def test_absolute_path_unchanged(self, tmp_path):
        """An absolute path resolves to itself (no trailing slash)."""
        palace = tmp_path / "palace"
        palace.mkdir()
        key = ChromaBackend._cache_key(str(palace))
        assert key == str(palace.resolve())


class TestClosePalaceCacheKeyMatch:
    """Verify close_palace finds the cached client even with path divergence."""

    def test_close_palace_finds_client_with_different_path_format(self, tmp_path):
        """get_collection with relative path, close_palace with absolute — client.close() fires."""
        palace = tmp_path / "palace"
        palace.mkdir()

        backend = ChromaBackend()
        mock_client = MagicMock()

        # Inject a cached client under the normalized key
        normalized = backend._cache_key(str(palace))
        backend._clients[normalized] = mock_client
        backend._freshness[normalized] = (12345, 1000.0)

        # close_palace with a different format (trailing slash)
        backend.close_palace(str(palace) + "/")

        mock_client.close.assert_called_once()
        assert normalized not in backend._clients
        assert normalized not in backend._freshness

    def test_close_palace_noop_when_no_client_cached(self, tmp_path):
        """close_palace on an uncached path is a silent no-op."""
        palace = tmp_path / "palace"
        palace.mkdir()
        backend = ChromaBackend()
        # Should not raise
        backend.close_palace(str(palace))


# ── SIGTERM → sys.exit bridge ─────────────────────────────────────────────


class TestSigtermBridge:
    """Verify SIGTERM handler is installed to trigger atexit on MCP kill."""

    def test_sigterm_handler_installed(self):
        """palace module installs a SIGTERM handler at import time."""
        import signal

        handler = signal.getsignal(signal.SIGTERM)
        # Should not be SIG_DFL (default) — our handler replaces it.
        assert handler is not signal.SIG_DFL, (
            "SIGTERM handler is still SIG_DFL — palace module's "
            "signal.signal(SIGTERM, ...) did not execute"
        )

    def test_sigterm_handler_raises_systemexit(self):
        """The SIGTERM handler calls sys.exit(0), which raises SystemExit."""
        import signal

        handler = signal.getsignal(signal.SIGTERM)
        with pytest.raises(SystemExit) as exc_info:
            handler(signal.SIGTERM, None)
        assert exc_info.value.code == 0

    def test_sigterm_source_has_bridge(self):
        """Structural test: palace.py source contains the SIGTERM bridge."""
        import inspect

        source = inspect.getsource(
            __import__("mempalace.palace", fromlist=["_DEFAULT_BACKEND"])
        )
        assert "signal.signal(signal.SIGTERM" in source
