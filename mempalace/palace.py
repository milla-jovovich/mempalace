"""
palace.py — Shared palace operations.

Consolidates ChromaDB access patterns used by both miners and the MCP server.
"""

import logging
import os
import chromadb

logger = logging.getLogger("mempalace")

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


def iter_metadatas(col, where=None, batch=500):
    """Yield every metadata dict in *col*, fetched in pages of *batch*.

    Replaces single col.get(limit=10000) calls that silently truncate on
    palaces with more than ~10k drawers (issue #171). Safe against ChromaDB
    returning None for the metadatas key.
    """
    offset = 0
    while True:
        kwargs = {"include": ["metadatas"], "limit": batch, "offset": offset}
        if where is not None:
            kwargs["where"] = where
        try:
            batch_result = col.get(**kwargs)
        except Exception as exc:
            logger.warning("iter_metadatas: ChromaDB error at offset %d: %s", offset, exc)
            return
        metas = batch_result.get("metadatas") or []
        if not metas:
            return
        yield from metas
        offset += len(metas)
        if len(metas) < batch:
            return


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
