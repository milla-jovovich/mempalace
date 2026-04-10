"""
palace.py — Shared palace operations.

Consolidates ChromaDB access patterns used by both miners and the MCP server.
"""

import logging
import os

import chromadb

from .embeddings import verify_embedding_compatibility

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
    """Get or create the palace ChromaDB collection.

    When opening an existing collection fails with a ``ValueError`` (typically
    caused by an embedding-function mismatch between ONNX and
    sentence-transformers), falls back to creating/opening without a custom
    function and runs a one-time vector-compatibility check.
    """
    os.makedirs(palace_path, exist_ok=True)
    try:
        os.chmod(palace_path, 0o700)
    except (OSError, NotImplementedError):
        pass
    client = chromadb.PersistentClient(path=palace_path)
    try:
        return client.get_collection(collection_name)
    except ValueError:
        # Embedding function mismatch — the collection was created with a
        # different embedder (ONNX default vs sentence-transformers).
        # Fall back to the default and verify vector compatibility.
        logger.warning(
            "Collection '%s' was created with a different embedding function. "
            "Falling back to default embedder. Vector compatibility should be "
            "verified — call verify_embedding_compatibility() or re-mine the palace.",
            collection_name,
        )
        try:
            col = client.get_or_create_collection(collection_name)
        except Exception:
            return client.create_collection(collection_name)
        verify_embedding_compatibility(col)
        return col
    except Exception:
        return client.create_collection(collection_name)


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
            return abs(float(stored_mtime) - current_mtime) < 0.01
        return True
    except Exception:
        return False
