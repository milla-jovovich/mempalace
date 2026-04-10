"""
palace.py — Shared palace operations.

Consolidates database access patterns used by both miners and the MCP server.
Backend-agnostic: works with LanceDB (default) or ChromaDB (legacy).
"""

import os

from .db import open_collection, detect_backend

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


def get_collection(palace_path: str, collection_name: str = "mempalace_drawers",
                   backend: str = None, embedder=None):
    """Get or create the palace collection.

    This is the main entry point for all palace database access.
    Auto-detects the backend (LanceDB or ChromaDB) based on existing data.
    """
    return open_collection(
        palace_path=palace_path,
        collection_name=collection_name,
        backend=backend,
        embedder=embedder,
    )


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
