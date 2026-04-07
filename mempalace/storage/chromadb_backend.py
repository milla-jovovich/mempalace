"""ChromaDB storage backend — wraps chromadb.PersistentClient into BaseCollection."""

import os

import chromadb

from .base import BaseCollection


class ChromaCollection(BaseCollection):
    """Thin wrapper around a ChromaDB collection implementing BaseCollection."""

    def __init__(self, name="mempalace_drawers", config=None, create=False, palace_path=None):
        from ..config import MempalaceConfig

        config = config or MempalaceConfig()
        palace_path = palace_path or config.palace_path
        os.makedirs(palace_path, exist_ok=True)

        self._client = chromadb.PersistentClient(path=palace_path)
        try:
            if create:
                self._col = self._client.get_or_create_collection(name)
            else:
                self._col = self._client.get_collection(name)
        except Exception:
            self._col = None

    @property
    def _ready(self):
        return self._col is not None

    def add(self, ids, documents, metadatas=None):
        if not self._ready:
            raise RuntimeError("Collection not available")
        kwargs = {"ids": ids, "documents": documents}
        if metadatas is not None:
            kwargs["metadatas"] = metadatas
        self._col.add(**kwargs)

    def get(self, ids=None, where=None, include=None, limit=None, offset=None):
        if not self._ready:
            return {"ids": [], "documents": [], "metadatas": []}
        kwargs = {}
        if ids is not None:
            kwargs["ids"] = ids
        if where:
            kwargs["where"] = where
        if include is not None:
            kwargs["include"] = include
        if limit is not None:
            kwargs["limit"] = limit
        if offset is not None:
            kwargs["offset"] = offset
        return self._col.get(**kwargs)

    def query(self, query_texts, n_results=5, where=None, include=None):
        if not self._ready:
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
        kwargs = {"query_texts": query_texts, "n_results": n_results}
        if where:
            kwargs["where"] = where
        if include is not None:
            kwargs["include"] = include
        return self._col.query(**kwargs)

    def delete(self, ids):
        if not self._ready:
            return
        self._col.delete(ids=ids)

    def count(self):
        if not self._ready:
            return 0
        return self._col.count()

    def upsert(self, ids, documents, metadatas=None):
        if not self._ready:
            raise RuntimeError("Collection not available")
        kwargs = {"ids": ids, "documents": documents}
        if metadatas is not None:
            kwargs["metadatas"] = metadatas
        self._col.upsert(**kwargs)
