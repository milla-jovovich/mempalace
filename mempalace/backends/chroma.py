"""ChromaDB-backed MemPalace collection adapter."""

from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any, Dict, Iterable, List, Optional

import chromadb

from .base import (
    DEFAULT_GET_INCLUDE,
    DEFAULT_QUERY_INCLUDE,
    BaseCollection,
    GetResult,
    QueryResult,
)

logger = logging.getLogger(__name__)


def _fix_blob_seq_ids(palace_path: str):
    """Fix ChromaDB 0.6.x -> 1.5.x migration bug: BLOB seq_ids -> INTEGER.

    ChromaDB 0.6.x stored seq_id as big-endian 8-byte BLOBs. ChromaDB 1.5.x
    expects INTEGER. The auto-migration doesn't convert existing rows, causing
    the Rust compactor to crash with "mismatched types; Rust type u64 (as SQL
    type INTEGER) is not compatible with SQL type BLOB".

    Must run BEFORE PersistentClient is created (the compactor fires on init).
    """
    db_path = os.path.join(palace_path, "chroma.sqlite3")
    if not os.path.isfile(db_path):
        return
    try:
        with sqlite3.connect(db_path) as conn:
            for table in ("embeddings", "max_seq_id"):
                try:
                    rows = conn.execute(
                        f"SELECT rowid, seq_id FROM {table} WHERE typeof(seq_id) = 'blob'"
                    ).fetchall()
                except sqlite3.OperationalError:
                    continue
                if not rows:
                    continue
                updates = [(int.from_bytes(blob, byteorder="big"), rowid) for rowid, blob in rows]
                conn.executemany(f"UPDATE {table} SET seq_id = ? WHERE rowid = ?", updates)
                logger.info("Fixed %d BLOB seq_ids in %s", len(updates), table)
            conn.commit()
    except Exception:
        logger.exception("Could not fix BLOB seq_ids in %s", db_path)


def _first_or_empty(raw: Dict[str, Any], key: str) -> List[Any]:
    """Safely pull the single-query slice out of a Chroma batch response."""
    outer = raw.get(key)
    if not outer:
        return []
    inner = outer[0]
    return inner if inner else []


class ChromaCollection(BaseCollection):
    """Thin adapter over a ChromaDB collection."""

    def __init__(self, collection):
        self._collection = collection

    # -- writes -----------------------------------------------------------

    def add(
        self,
        *,
        ids: List[str],
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self._collection.add(ids=ids, documents=documents, metadatas=metadatas)

    def upsert(
        self,
        *,
        ids: List[str],
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    def update(
        self,
        *,
        ids: List[str],
        documents: Optional[List[str]] = None,
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        kwargs: Dict[str, Any] = {"ids": ids}
        if documents is not None:
            kwargs["documents"] = documents
        if metadatas is not None:
            kwargs["metadatas"] = metadatas
        self._collection.update(**kwargs)

    # -- reads ------------------------------------------------------------

    def query(
        self,
        *,
        query_texts: List[str],
        n_results: int = 10,
        where: Optional[Dict[str, Any]] = None,
        include: Iterable[str] = DEFAULT_QUERY_INCLUDE,
    ) -> QueryResult:
        include_list = list(include)
        kwargs: Dict[str, Any] = {
            "query_texts": query_texts,
            "n_results": n_results,
            "include": include_list,
        }
        if where:
            kwargs["where"] = where
        raw = self._collection.query(**kwargs)
        return QueryResult(
            ids=_first_or_empty(raw, "ids"),
            documents=_first_or_empty(raw, "documents"),
            metadatas=_first_or_empty(raw, "metadatas"),
            distances=_first_or_empty(raw, "distances"),
        )

    def get(
        self,
        *,
        ids: Optional[List[str]] = None,
        where: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        include: Iterable[str] = DEFAULT_GET_INCLUDE,
    ) -> GetResult:
        kwargs: Dict[str, Any] = {"include": list(include)}
        if ids is not None:
            kwargs["ids"] = ids
        if where is not None:
            kwargs["where"] = where
        if limit is not None:
            kwargs["limit"] = limit
        if offset is not None:
            kwargs["offset"] = offset
        raw = self._collection.get(**kwargs)
        return GetResult(
            ids=raw.get("ids") or [],
            documents=raw.get("documents") or [],
            metadatas=raw.get("metadatas") or [],
        )

    def delete(
        self,
        *,
        ids: Optional[List[str]] = None,
        where: Optional[Dict[str, Any]] = None,
    ) -> None:
        kwargs: Dict[str, Any] = {}
        if ids is not None:
            kwargs["ids"] = ids
        if where is not None:
            kwargs["where"] = where
        self._collection.delete(**kwargs)

    def count(self) -> int:
        return self._collection.count()


class ChromaBackend:
    """Factory for MemPalace's default ChromaDB backend."""

    def __init__(self):
        # Per-instance client cache: palace_path -> chromadb.PersistentClient
        self._clients: dict = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _client(self, palace_path: str):
        """Return a cached PersistentClient for *palace_path*, creating one if needed."""
        if palace_path not in self._clients:
            _fix_blob_seq_ids(palace_path)
            self._clients[palace_path] = chromadb.PersistentClient(path=palace_path)
        return self._clients[palace_path]

    # ------------------------------------------------------------------
    # Public static helpers (for callers that manage their own caching)
    # ------------------------------------------------------------------

    @staticmethod
    def make_client(palace_path: str):
        """Create and return a fresh PersistentClient (fix BLOB seq_ids first).

        Intended for long-lived callers (e.g. mcp_server) that keep their own
        inode/mtime-based client cache.
        """
        _fix_blob_seq_ids(palace_path)
        return chromadb.PersistentClient(path=palace_path)

    @staticmethod
    def backend_version() -> str:
        """Return the installed chromadb package version string."""
        return chromadb.__version__

    # ------------------------------------------------------------------
    # Collection lifecycle
    # ------------------------------------------------------------------

    def get_collection(self, palace_path: str, collection_name: str, create: bool = False):
        if not create and not os.path.isdir(palace_path):
            raise FileNotFoundError(palace_path)

        if create:
            os.makedirs(palace_path, exist_ok=True)
            try:
                os.chmod(palace_path, 0o700)
            except (OSError, NotImplementedError):
                pass

        client = self._client(palace_path)
        if create:
            collection = client.get_or_create_collection(
                collection_name, metadata={"hnsw:space": "cosine"}
            )
        else:
            collection = client.get_collection(collection_name)
        return ChromaCollection(collection)

    def get_or_create_collection(
        self, palace_path: str, collection_name: str
    ) -> "ChromaCollection":
        """Shorthand for get_collection(..., create=True)."""
        return self.get_collection(palace_path, collection_name, create=True)

    def delete_collection(self, palace_path: str, collection_name: str) -> None:
        """Delete *collection_name* from the palace at *palace_path*."""
        self._client(palace_path).delete_collection(collection_name)

    def create_collection(
        self, palace_path: str, collection_name: str, hnsw_space: str = "cosine"
    ) -> "ChromaCollection":
        """Create (not get-or-create) *collection_name* with cosine HNSW space."""
        collection = self._client(palace_path).create_collection(
            collection_name, metadata={"hnsw:space": hnsw_space}
        )
        return ChromaCollection(collection)
