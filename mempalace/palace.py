"""
palace.py — Shared palace operations.

Consolidates ChromaDB access patterns used by both miners and the MCP server.
"""

import os
import chromadb
from mempalace.config import MempalaceConfig

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


def _get_embedding_function():
    """Return a ChromaDB embedding function based on config, or None for the default.

    When ``embedding_model`` is set in ``~/.mempalace/config.json`` (or via the
    ``MEMPALACE_EMBEDDING_MODEL`` env var), a ``SentenceTransformerEmbeddingFunction``
    is returned so that any HuggingFace sentence-transformers model can be used.
    This is useful for non-English content — for example::

        # ~/.mempalace/config.json
        {"embedding_model": "paraphrase-multilingual-MiniLM-L12-v2"}

    Returns ``None`` to fall back to ChromaDB's built-in ONNX model
    (``all-MiniLM-L6-v2``), which is the default behaviour and requires no
    extra dependencies.
    """
    model_name = MempalaceConfig().embedding_model
    if not model_name:
        return None
    try:
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
        return SentenceTransformerEmbeddingFunction(model_name=model_name)
    except ImportError:
        raise ImportError(
            f"embedding_model is set to '{model_name}' but the 'sentence-transformers' "
            "package is not installed. Run: pip install sentence-transformers"
        )


def get_collection(palace_path: str, collection_name: str = "mempalace_drawers"):
    """Get or create the palace ChromaDB collection."""
    os.makedirs(palace_path, exist_ok=True)
    try:
        os.chmod(palace_path, 0o700)
    except (OSError, NotImplementedError):
        pass
    client = chromadb.PersistentClient(path=palace_path)
    ef = _get_embedding_function()
    kwargs = {"embedding_function": ef} if ef is not None else {}
    try:
        return client.get_collection(collection_name, **kwargs)
    except Exception:
        return client.create_collection(collection_name, **kwargs)


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
