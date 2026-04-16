"""Storage backend implementations for MemPalace.

Two backends ship by default:

    ChromaBackend  — local DuckDB+Parquet via chromadb (the original).
    MilvusBackend  — local single-file Milvus Lite (``./milvus.db``);
                     also supports self-hosted Milvus over HTTP.

Both implement the same :class:`BaseCollection` contract so the rest of
MemPalace never has to care which one is in use.

Selecting a backend
-------------------
Set the ``MEMPALACE_BACKEND`` environment variable to ``chroma`` (default)
or ``milvus``. :func:`make_default_backend` honors the env var; callers
that need fine control (e.g. dependency injection in tests) can
instantiate a backend class directly.

The ``milvus`` backend requires the ``milvus`` optional dependency
group — install with ``pip install mempalace[milvus]``.
"""

from __future__ import annotations

import os
from typing import Any

from .base import (
    DEFAULT_GET_INCLUDE,
    DEFAULT_QUERY_INCLUDE,
    BaseCollection,
    GetResult,
    QueryResult,
)
from .chroma import ChromaBackend, ChromaCollection


class BackendNotInstalledError(ImportError):
    """Raised when the requested backend's optional dependencies are missing."""


def _load_milvus_backend() -> Any:
    """Import :class:`MilvusBackend` lazily so Chroma-only installs work.

    The ``milvus`` optional dependency group pulls in ``pymilvus``,
    ``milvus-lite``, ``onnxruntime``, and ``huggingface_hub``. If any
    are missing we surface a targeted error with install instructions
    rather than a raw ImportError on some deep-transitive symbol.
    """
    try:
        from .milvus import MilvusBackend  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised indirectly
        raise BackendNotInstalledError(
            "MilvusBackend requires optional dependencies. Install with: "
            "pip install 'mempalace[milvus]'"
        ) from exc
    return MilvusBackend


def make_default_backend(**kwargs: Any):
    """Factory that honors the ``MEMPALACE_BACKEND`` environment variable.

    ``kwargs`` are forwarded to the chosen backend's constructor.
    """
    name = os.environ.get("MEMPALACE_BACKEND", "chroma").strip().lower()
    if name == "chroma":
        return ChromaBackend(**kwargs)
    if name == "milvus":
        cls = _load_milvus_backend()
        return cls(**kwargs)
    raise ValueError(f"Unknown MEMPALACE_BACKEND={name!r}. Expected 'chroma' or 'milvus'.")


__all__ = [
    "BackendNotInstalledError",
    "BaseCollection",
    "ChromaBackend",
    "ChromaCollection",
    "DEFAULT_GET_INCLUDE",
    "DEFAULT_QUERY_INCLUDE",
    "GetResult",
    "QueryResult",
    "make_default_backend",
]


def __getattr__(name: str) -> Any:
    """Lazy attribute access so ``from mempalace.backends import MilvusBackend``
    works when ``pymilvus`` is installed and raises a helpful error otherwise.
    """
    if name == "MilvusBackend":
        return _load_milvus_backend()
    if name == "MilvusCollection":
        from .milvus import MilvusCollection

        return MilvusCollection
    raise AttributeError(f"module 'mempalace.backends' has no attribute {name!r}")
