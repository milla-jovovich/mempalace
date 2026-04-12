"""
palace.py — Shared palace operations.

Consolidates database access patterns used by both miners and the MCP server.
Backend-agnostic: works with LanceDB (default) or ChromaDB (legacy).
"""

import os

from .backends import detect_backend, LanceBackend, ChromaBackend

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

_lance_backend = LanceBackend()
_chroma_backend = ChromaBackend()


def get_collection(
    palace_path: str, collection_name: str = "mempalace_drawers",
    backend: str = None, embedder=None, create: bool = True,
):
    """Get or create the palace collection.

    This is the main entry point for all palace database access.
    Auto-detects the backend (LanceDB or ChromaDB) based on existing data.
    LanceDB is the default for new palaces.
    """
    if backend is None:
        from .config import MempalaceConfig
        configured = MempalaceConfig().backend
        backend = configured or detect_backend(palace_path)

    if backend == "chroma":
        return _chroma_backend.get_collection(
            palace_path, collection_name=collection_name, create=create,
        )
    return _lance_backend.get_collection(
        palace_path, collection_name=collection_name, create=create, embedder=embedder,
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
            return abs(float(stored_mtime) - current_mtime) < 0.001
        return True
    except Exception:
        return False
