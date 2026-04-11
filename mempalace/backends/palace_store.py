"""PalaceStore-backed MemPalace collection adapter.

Implements the :class:`BaseCollection` contract defined in
``mempalace.backends.base`` by wrapping a collection built from the
``palace_store.compat`` drop-in shim. Selected via the ``MEMPAL_STORAGE``
environment variable — see :func:`mempalace.backends.get_default_backend`.

Opt-in by design: the module is only imported when a user explicitly
sets ``MEMPAL_STORAGE=palace_store``. If ``palace_store`` isn't
installed, :class:`PalaceStoreBackend` raises a clear ImportError
message pointing at the extras install so users know what to add.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from .base import BaseCollection


class PalaceStoreCollection(BaseCollection):
    """Thin adapter over a ``palace_store.compat`` collection.

    Shape mirrors :class:`mempalace.backends.chroma.ChromaCollection`
    exactly — the compat shim implements the same method names and
    keyword arguments as ChromaDB's ``Collection`` for the narrow
    subset mempalace uses.
    """

    def __init__(self, collection: Any):
        self._collection = collection

    def add(self, *, documents, ids, metadatas=None):
        self._collection.add(documents=documents, ids=ids, metadatas=metadatas)

    def upsert(self, *, documents, ids, metadatas=None):
        self._collection.upsert(documents=documents, ids=ids, metadatas=metadatas)

    def query(self, **kwargs: Any) -> Dict[str, Any]:
        return self._collection.query(**kwargs)

    def get(self, **kwargs: Any) -> Dict[str, Any]:
        return self._collection.get(**kwargs)

    def delete(self, **kwargs: Any) -> None:
        self._collection.delete(**kwargs)

    def count(self) -> int:
        return self._collection.count()


class PalaceStoreBackend:
    """Factory for a PalaceStore-backed MemPalace collection.

    Opening a collection is idempotent in both ``create=True`` and
    ``create=False`` modes but preserves ChromaDB's "no palace found"
    behavior: if ``create=False`` is passed and the palace directory
    doesn't exist, we raise ``FileNotFoundError`` rather than silently
    creating one.
    """

    def __init__(self):
        # Import lazily so users who don't opt in never pay for the
        # palace_store import graph (fastembed, threadpoolctl, etc).
        try:
            from palace_store import compat as _compat  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "MEMPAL_STORAGE=palace_store requires the palace_store "
                "package. It ships with mempalace but may not be "
                "available in minimal installs — install the optional "
                "extra: pip install 'mempalace[palace-parallel]'"
            ) from e
        self._parallel_query = _env_bool("MEMPAL_PARALLEL_QUERY", default=False)
        self._max_workers_env = os.environ.get("MEMPAL_MAX_WORKERS")

    def get_collection(
        self,
        palace_path: str,
        collection_name: str = "mempalace_drawers",
        create: bool = False,
    ) -> PalaceStoreCollection:
        if not create and not os.path.isdir(palace_path):
            raise FileNotFoundError(palace_path)

        if create:
            os.makedirs(palace_path, exist_ok=True)
            try:
                os.chmod(palace_path, 0o700)
            except (OSError, NotImplementedError):
                pass

        from palace_store import compat as _compat

        max_workers: Optional[int] = None
        if self._max_workers_env:
            try:
                max_workers = int(self._max_workers_env)
            except ValueError:
                max_workers = None

        client = _compat.PersistentClient(
            path=palace_path,
            dtype="float32",
            parallel_query=self._parallel_query,
            max_workers=max_workers,
        )
        if create:
            collection = client.get_or_create_collection(collection_name)
        else:
            collection = client.get_collection(collection_name)
        return PalaceStoreCollection(collection)


def _env_bool(name: str, *, default: bool = False) -> bool:
    """Parse a boolean env var in the usual way (``1/true/yes/on`` = True)."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


__all__ = ["PalaceStoreBackend", "PalaceStoreCollection"]
