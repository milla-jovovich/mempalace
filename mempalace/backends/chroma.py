"""ChromaDB-backed MemPalace collection adapter."""

import logging
import os
import sqlite3
from typing import Any, Dict

import chromadb

from .base import BaseCollection

logger = logging.getLogger(__name__)


_DEFAULT_OLLAMA_URL = "http://localhost:11434"
_DEFAULT_OLLAMA_MODEL = "nomic-embed-text"
_DEFAULT_OLLAMA_TIMEOUT = 60


def _parse_timeout(raw):
    """Parse OLLAMA_EMBED_TIMEOUT env with a clear error on non-integers."""
    if raw is None or str(raw).strip() == "":
        return _DEFAULT_OLLAMA_TIMEOUT
    try:
        return int(str(raw).strip())
    except ValueError as exc:
        raise ValueError(
            f"OLLAMA_EMBED_TIMEOUT must be an integer number of seconds, "
            f"got {raw!r}"
        ) from exc


def get_embedding_function():
    """Return an embedding function based on env, or ``None`` for Chroma's default.

    Set ``EMBEDDING_PROVIDER=ollama`` to route embeddings through a local
    Ollama server (GPU-accelerated). Tunables:

    - ``OLLAMA_URL`` (default ``http://localhost:11434``) - base URL
    - ``OLLAMA_EMBED_MODEL`` (default ``nomic-embed-text``)
    - ``OLLAMA_EMBED_TIMEOUT`` seconds (default ``60``)

    Returning ``None`` keeps ChromaDB's ``DefaultEmbeddingFunction`` (ONNX
    MiniLM, 384 dims, CPU) for backward compatibility with existing palaces.
    """
    provider = os.environ.get("EMBEDDING_PROVIDER", "").strip().lower()
    if provider != "ollama":
        return None
    from chromadb.utils.embedding_functions import OllamaEmbeddingFunction

    return OllamaEmbeddingFunction(
        url=(os.environ.get("OLLAMA_URL") or _DEFAULT_OLLAMA_URL).strip(),
        model_name=(os.environ.get("OLLAMA_EMBED_MODEL") or _DEFAULT_OLLAMA_MODEL).strip(),
        timeout=_parse_timeout(os.environ.get("OLLAMA_EMBED_TIMEOUT")),
    )


def _ef_kwargs() -> Dict[str, Any]:
    """Return ``{"embedding_function": ef}`` when an EF is configured, else ``{}``.

    Spreading this dict into ChromaDB's ``get_or_create_collection`` / ``get_collection``
    / ``create_collection`` calls keeps the default-embedding-function path completely
    untouched (no ``embedding_function=None`` kwarg is passed) and keeps the Ollama
    path explicit, eliminating both the typing mismatch and any risk of passing
    ``None`` into a positional that older chromadb releases may reject.
    """
    ef = get_embedding_function()
    return {"embedding_function": ef} if ef is not None else {}


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


class ChromaCollection(BaseCollection):
    """Thin adapter over a ChromaDB collection."""

    def __init__(self, collection):
        self._collection = collection

    def add(self, *, documents, ids, metadatas=None):
        self._collection.add(documents=documents, ids=ids, metadatas=metadatas)

    def upsert(self, *, documents, ids, metadatas=None):
        self._collection.upsert(documents=documents, ids=ids, metadatas=metadatas)

    def update(self, **kwargs):
        self._collection.update(**kwargs)

    def query(self, **kwargs):
        return self._collection.query(**kwargs)

    def get(self, **kwargs):
        return self._collection.get(**kwargs)

    def delete(self, **kwargs):
        self._collection.delete(**kwargs)

    def count(self):
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
        ef_kwargs = _ef_kwargs()
        if create:
            collection = client.get_or_create_collection(
                collection_name,
                metadata={"hnsw:space": "cosine"},
                **ef_kwargs,
            )
        else:
            collection = client.get_collection(collection_name, **ef_kwargs)
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
            collection_name,
            metadata={"hnsw:space": hnsw_space},
            **_ef_kwargs(),
        )
        return ChromaCollection(collection)
