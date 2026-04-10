"""
palace.py — Shared palace operations.

Consolidates ChromaDB access patterns used by both miners and the MCP server.
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


def get_collection(palace_path: str, collection_name: str = "mempalace_drawers"):
    """Get or create the palace ChromaDB collection."""
    os.makedirs(palace_path, exist_ok=True)
    try:
        os.chmod(palace_path, 0o700)
    except (OSError, NotImplementedError):
        pass
    client = chromadb.PersistentClient(path=palace_path)
    try:
        return client.get_collection(collection_name)
    except Exception:
        return client.create_collection(collection_name)


def _build_where(wing: str, room: str | None = None) -> dict:
    """Build a ChromaDB where filter for wing/room scoped operations."""
    if room:
        return {"$and": [{"wing": wing}, {"room": room}]}
    return {"wing": wing}


def find_drawer_ids(collection, wing: str, room: str | None = None) -> list[str]:
    """Return drawer IDs matching a wing (and optional room) in one scan.

    Uses ``include=[]`` so ChromaDB only fetches IDs — no documents,
    embeddings, or metadatas. Callers that need both a count and a
    subsequent delete should call this once and reuse the result to
    avoid a second scan.
    """
    try:
        results = collection.get(where=_build_where(wing, room), include=[])
        return list(results.get("ids", []))
    except Exception:
        return []


def count_drawers(collection, wing: str, room: str | None = None) -> int:
    """Count drawers in a wing (and optionally a specific room)."""
    return len(find_drawer_ids(collection, wing, room))


def file_already_mined(collection, source_file: str, check_mtime: bool = False) -> bool:
    """Check if a file has already been filed in the palace.

    When check_mtime=True (used by project miner), returns False if the file
    has been modified since it was last mined, so it gets re-mined.
    When check_mtime=False (used by convo miner), just checks existence.
    """
    try:
        results = collection.get(where={"source_file": source_file}, limit=1)
        if not results.get("ids"):
            return False
        if check_mtime:
            stored_meta = results.get("metadatas", [{}])[0]
            stored_mtime = stored_meta.get("source_mtime")
            if stored_mtime is None:
                return False
            current_mtime = os.path.getmtime(source_file)
            return float(stored_mtime) == current_mtime
        return True
    except Exception:
        return False
