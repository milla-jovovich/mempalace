"""
palace.py — Shared palace operations.

Consolidates ChromaDB access patterns used by both miners and the MCP server.
Provides a singleton client factory to avoid creating multiple PersistentClient
instances to the same path (which causes SQLite locking contention).
"""

import os
import chromadb

SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    ".next",
    "coverage",
    ".mempalace",
    ".ruff_cache",
    ".mypy_cache",
    ".pytest_cache",
    ".cache",
    ".tox",
    ".nox",
    ".idea",
    ".vscode",
    ".ipynb_checkpoints",
    ".eggs",
    "htmlcov",
    "target",
}

# Singleton client cache — one PersistentClient per palace path
_client_cache = {}


def get_client(palace_path: str) -> chromadb.ClientAPI:
    """Return a singleton ChromaDB PersistentClient for the given path."""
    if palace_path not in _client_cache:
        os.makedirs(palace_path, exist_ok=True)
        try:
            os.chmod(palace_path, 0o700)
        except (OSError, NotImplementedError):
            pass
        _client_cache[palace_path] = chromadb.PersistentClient(path=palace_path)
    return _client_cache[palace_path]


def get_collection(palace_path: str, collection_name: str = "mempalace_drawers"):
    """Get or create the palace ChromaDB collection using singleton client."""
    client = get_client(palace_path)
    try:
        return client.get_collection(collection_name)
    except Exception:
        return client.create_collection(collection_name)


def get_mined_files(collection) -> dict:
    """Pre-fetch all mined source_file values and their mtimes in one batch.

    Returns a dict of {source_file: mtime_or_None} for O(1) lookups.
    """
    mined = {}
    offset = 0
    while True:
        batch = collection.get(limit=5000, offset=offset, include=["metadatas"])
        if not batch["ids"]:
            break
        for m in batch["metadatas"]:
            sf = m.get("source_file", "")
            if sf:
                mined[sf] = m.get("source_mtime")
        offset += len(batch["ids"])
        if len(batch["ids"]) < 5000:
            break
    return mined


def file_already_mined(collection, source_file: str, mined_cache: dict = None) -> bool:
    """Check if a file has already been filed in the palace.

    If mined_cache is provided (from get_mined_files), uses O(1) dict lookup.
    Otherwise falls back to a ChromaDB query.
    """
    if mined_cache is not None:
        if source_file not in mined_cache:
            return False
        stored_mtime = mined_cache[source_file]
        if stored_mtime is None:
            return True  # Filed but no mtime stored — treat as mined
        try:
            current_mtime = os.path.getmtime(source_file)
            return float(stored_mtime) == current_mtime
        except OSError:
            return False
    # Fallback: single query
    try:
        results = collection.get(where={"source_file": source_file}, limit=1)
        return len(results.get("ids", [])) > 0
    except Exception:
        return False
