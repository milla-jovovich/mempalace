"""Runtime backend-mode helpers used by searcher, repair, and the MCP server.

Centralizes the "are we running against a local chromadb or a remote one?"
question so the call sites that historically read ``chroma.sqlite3``
directly (BM25 fallback, HNSW capacity probe, ``mempalace repair``)
have a single source of truth for routing.

The decision priority mirrors :func:`mempalace.backends.registry.resolve_backend_for_palace`:

1. ``MEMPALACE_BACKEND`` env var (``chroma`` or ``chroma_http``).
2. ``MEMPALACE_CHROMA_URL`` / ``MEMPALACE_CHROMA_HOST`` set → HTTP.
3. Otherwise → local.

A small in-process cache keeps the answer stable across the lifetime of a
search/repair invocation; tests can call :func:`reset_backend_mode_cache`
between cases.
"""

from __future__ import annotations

import os
from typing import Optional


_BackendMode = str  # "local" | "http"
_LOCAL = "local"
_HTTP = "http"

_cached_mode: Optional[_BackendMode] = None


def _detect_chroma_http_env() -> bool:
    """Return True iff any HTTP-mode chromadb env var is set."""
    return any(
        os.environ.get(name, "").strip()
        for name in (
            "MEMPALACE_CHROMA_URL",
            "MEMPALACE_CHROMA_HOST",
            "MEMPALACE_CHROMA_PORT",
        )
    )


def resolve_backend_mode() -> _BackendMode:
    """Return ``"local"`` or ``"http"`` for the current process configuration.

    Cached after the first call. Use :func:`reset_backend_mode_cache` from
    tests when env vars change between cases.
    """
    global _cached_mode
    if _cached_mode is not None:
        return _cached_mode

    explicit = os.environ.get("MEMPALACE_BACKEND", "").strip().lower()
    if explicit == "chroma_http":
        _cached_mode = _HTTP
        return _HTTP
    if explicit == "chroma":
        _cached_mode = _LOCAL
        return _LOCAL

    _cached_mode = _HTTP if _detect_chroma_http_env() else _LOCAL
    return _cached_mode


def using_local_chroma() -> bool:
    """Return True when the active backend is the file-backed local one.

    Use this gate before calling code that reads ``chroma.sqlite3`` or
    ``index_metadata.pickle`` directly. On HTTP mode those files don't
    exist client-side and the caller must use the chromadb API instead.
    """
    return resolve_backend_mode() == _LOCAL


def using_http_chroma() -> bool:
    """Inverse of :func:`using_local_chroma` for readability at call sites."""
    return resolve_backend_mode() == _HTTP


def reset_backend_mode_cache() -> None:
    """Forget the cached mode so the next call re-resolves from env.

    Tests that toggle ``MEMPALACE_*`` env vars between cases must call
    this between cases or use ``monkeypatch`` plus an explicit reset.
    """
    global _cached_mode
    _cached_mode = None


__all__ = [
    "resolve_backend_mode",
    "using_local_chroma",
    "using_http_chroma",
    "reset_backend_mode_cache",
]
