"""ChromaDB-backed MemPalace collection adapter."""

import datetime as _dt
import logging
import os
import sqlite3

import chromadb

from .base import BaseCollection

logger = logging.getLogger(__name__)


_BLOB_FIX_MARKER = ".blob_seq_ids_migrated"


def quarantine_stale_hnsw(palace_path: str, stale_seconds: float = 3600.0) -> list[str]:
    """Rename HNSW segment dirs whose files are stale vs. chroma.sqlite3.

    When ChromaDB 1.5.x loads an HNSW segment that disagrees with the live
    ``embeddings`` table in sqlite, the Rust graph-walk dereferences dangling
    neighbor pointers and segfaults in a background thread (the failure
    mirrored at neo-cortex-mcp#2 and observed locally at offset ``a3ee57``
    in ``chromadb_rust_bindings.abi3.so``).

    Heuristic: if the sqlite mtime is more than *stale_seconds* newer than
    the HNSW ``data_level0.bin`` mtime, the segment is suspect and gets
    renamed out of the way. Chroma reopens cleanly without it and rebuilds
    index files on next write. The original directory is renamed, not
    deleted, so recovery remains possible.

    Returns the list of quarantined segment paths.
    """
    db_path = os.path.join(palace_path, "chroma.sqlite3")
    if not os.path.isfile(db_path):
        return []
    try:
        sqlite_mtime = os.path.getmtime(db_path)
    except OSError:
        return []

    moved: list[str] = []
    try:
        entries = os.listdir(palace_path)
    except OSError:
        return []

    for name in entries:
        if "-" not in name or name.startswith(".") or ".drift-" in name:
            continue
        seg_dir = os.path.join(palace_path, name)
        if not os.path.isdir(seg_dir):
            continue
        hnsw_bin = os.path.join(seg_dir, "data_level0.bin")
        if not os.path.isfile(hnsw_bin):
            continue
        try:
            hnsw_mtime = os.path.getmtime(hnsw_bin)
        except OSError:
            continue
        if sqlite_mtime - hnsw_mtime < stale_seconds:
            continue
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        target = f"{seg_dir}.drift-{stamp}"
        try:
            os.rename(seg_dir, target)
            moved.append(target)
            logger.warning(
                "Quarantined stale HNSW segment %s "
                "(sqlite %.0fs newer than HNSW); renamed to %s",
                seg_dir,
                sqlite_mtime - hnsw_mtime,
                target,
            )
        except OSError:
            logger.exception("Failed to quarantine stale HNSW segment %s", seg_dir)
    return moved


def _fix_blob_seq_ids(palace_path: str):
    """Fix ChromaDB 0.6.x -> 1.5.x migration bug: BLOB seq_ids -> INTEGER.

    ChromaDB 0.6.x stored seq_id as big-endian 8-byte BLOBs. ChromaDB 1.5.x
    expects INTEGER. The auto-migration doesn't convert existing rows, causing
    the Rust compactor to crash with "mismatched types; Rust type u64 (as SQL
    type INTEGER) is not compatible with SQL type BLOB".

    Must run BEFORE PersistentClient is created (the compactor fires on init).

    Opening a Python sqlite3 connection against a ChromaDB 1.5.x WAL-mode
    database leaves state that segfaults the next PersistentClient call.
    After the migration has run once successfully, a marker file is written
    so subsequent opens skip the sqlite connection entirely.
    """
    db_path = os.path.join(palace_path, "chroma.sqlite3")
    if not os.path.isfile(db_path):
        return
    marker = os.path.join(palace_path, _BLOB_FIX_MARKER)
    if os.path.isfile(marker):
        return
    try:
        with sqlite3.connect(db_path) as conn:
            table_rows: dict = {}
            for table in ("embeddings", "max_seq_id"):
                try:
                    rows = conn.execute(
                        f"SELECT rowid, seq_id FROM {table} WHERE typeof(seq_id) = 'blob'"
                    ).fetchall()
                except sqlite3.OperationalError:
                    continue
                if rows:
                    table_rows[table] = rows
            for table, rows in table_rows.items():
                updates = [(int.from_bytes(blob, byteorder="big"), rowid) for rowid, blob in rows]
                conn.executemany(f"UPDATE {table} SET seq_id = ? WHERE rowid = ?", updates)
                logger.info("Fixed %d BLOB seq_ids in %s", len(updates), table)
            conn.commit()
        try:
            with open(marker, "w", encoding="utf-8") as f:
                f.write("migrated\n")
        except OSError:
            pass
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
        if create:
            # ChromaDB 1.5.x segfaults when get_or_create_collection is called
            # with metadata that differs from an existing collection's metadata.
            # Fetch first; only pass hnsw:space when actually creating fresh.
            try:
                collection = client.get_collection(collection_name)
            except Exception:
                collection = client.create_collection(
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
