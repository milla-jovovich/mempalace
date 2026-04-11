"""Storage backend implementations for MemPalace."""

import os

from .base import BaseCollection
from .chroma import ChromaBackend, ChromaCollection


def get_default_backend():
    """Return the configured default storage backend.

    Reads the ``MEMPAL_STORAGE`` environment variable at call time:

    * unset / ``chromadb`` / ``chroma`` → :class:`ChromaBackend` (default)
    * ``palace_store`` / ``palace`` / ``palacestore`` →
      :class:`~mempalace.backends.palace_store.PalaceStoreBackend`

    The PalaceStore backend is imported lazily so users who don't opt
    in never pay for its dependency graph. Unknown values raise
    ``RuntimeError`` rather than silently falling back — an obvious
    typo is better surfaced than ignored.
    """
    raw = os.environ.get("MEMPAL_STORAGE", "").strip().lower()
    if raw in ("", "chromadb", "chroma"):
        return ChromaBackend()
    if raw in ("palace_store", "palace", "palacestore"):
        from .palace_store import PalaceStoreBackend

        return PalaceStoreBackend()
    raise RuntimeError(
        f"MEMPAL_STORAGE={raw!r} is not a valid backend. "
        f"Use 'chromadb' (default) or 'palace_store'."
    )


__all__ = [
    "BaseCollection",
    "ChromaBackend",
    "ChromaCollection",
    "get_default_backend",
]
