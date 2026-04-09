"""
palace.py — Shared palace operations.

Consolidates ChromaDB access patterns used by both miners and the MCP server.
"""

import os
import chromadb
from chromadb.errors import NotFoundError

from .config import MempalaceConfig

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


def resolve_drawer_context(
    palace_path: str = None,
    collection_name: str = None,
    config: MempalaceConfig = None,
):
    """Resolve the default drawer collection path and name."""
    cfg = config or MempalaceConfig()
    resolved_path = os.path.expanduser(os.fspath(palace_path)) if palace_path else cfg.palace_path
    resolved_collection = collection_name or cfg.collection_name
    return resolved_path, resolved_collection


def open_collection_on_client(client, collection_name: str, create: bool):
    """Open a collection on an existing client without hiding real failures."""
    if create:
        return client.get_or_create_collection(collection_name)
    try:
        return client.get_collection(collection_name)
    except NotFoundError:
        return None


def get_drawer_collection(
    palace_path: str = None,
    collection_name: str = None,
    *,
    create: bool = False,
    config: MempalaceConfig = None,
):
    """Open the configured drawer collection for reads or writes."""
    palace_path, collection_name = resolve_drawer_context(
        palace_path=palace_path,
        collection_name=collection_name,
        config=config,
    )
    if not create and not os.path.isdir(palace_path):
        return None
    if create:
        _ensure_palace_dir(palace_path)
    client = chromadb.PersistentClient(path=palace_path)
    return open_collection_on_client(client, collection_name, create=create)


def get_collection(palace_path: str, collection_name: str = None):
    """Backward-compatible wrapper for write paths that need the drawer collection."""
    return get_drawer_collection(
        palace_path=palace_path,
        collection_name=collection_name,
        create=True,
    )


def iter_collection_metadatas(collection, *, where=None, batch_size: int = 1000):
    """Yield collection metadata rows in pages without a hard cap."""
    offset = 0
    while True:
        kwargs = {"include": ["metadatas"], "limit": batch_size, "offset": offset}
        if where:
            kwargs["where"] = where
        batch = collection.get(**kwargs)
        metadatas = batch.get("metadatas") or []
        batch_ids = batch.get("ids")
        batch_count = len(batch_ids) if batch_ids is not None else len(metadatas)
        if batch_count == 0:
            break
        for metadata in metadatas:
            if metadata:
                yield metadata
        offset += batch_count
        if batch_count < batch_size:
            break


def _ensure_palace_dir(palace_path: str):
    """Create the palace directory with best-effort owner-only permissions."""
    os.makedirs(palace_path, exist_ok=True)
    try:
        os.chmod(palace_path, 0o700)
    except (OSError, NotImplementedError):
        pass


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
