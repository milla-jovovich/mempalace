"""
palace.py — Shared palace operations.

Consolidates ChromaDB access patterns used by both miners and the MCP server.
"""

import hashlib
import logging
import os
import re
from typing import Optional

import chromadb
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

logger = logging.getLogger("mempalace_palace")

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


_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_EMBEDDING_FUNCTION: Optional[EmbeddingFunction[Documents]] = None


class _HashEmbeddingFunction(EmbeddingFunction[Documents]):
    """Simple local embedding fallback that never needs network access."""

    def __init__(self, dimensions: int = 256):
        self.dimensions = dimensions

    def __call__(self, input: Documents) -> Embeddings:
        embeddings = []
        for text in input:
            embeddings.append(self._embed_text(text or ""))
        return embeddings

    def _embed_text(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        normalized = text.lower()
        tokens = _TOKEN_RE.findall(normalized)

        if len(tokens) > 1:
            tokens.extend(f"{left}_{right}" for left, right in zip(tokens, tokens[1:]))

        if not tokens:
            stripped = normalized.strip()
            tokens = [stripped] if stripped else ["<empty>"]

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            primary = int.from_bytes(digest[:4], "little") % self.dimensions
            secondary = int.from_bytes(digest[4:8], "little") % self.dimensions
            sign = -1.0 if digest[8] & 1 else 1.0

            vector[primary] += sign
            vector[secondary] += 0.5 * sign

        return vector


class _SafeEmbeddingFunction(EmbeddingFunction[Documents]):
    """Prefer Chroma's default model, but fall back locally when it cannot load."""

    def __init__(self):
        self._delegate: Optional[EmbeddingFunction[Documents]] = None
        self._fallback = _HashEmbeddingFunction()
        self._fallback_warned = False
        self._delegate_disabled = False

    def __call__(self, input: Documents) -> Embeddings:
        if not self._delegate_disabled and self._delegate is None:
            try:
                self._delegate = DefaultEmbeddingFunction()
                if self._delegate is None:
                    self._delegate_disabled = True
            except Exception as exc:
                self._delegate_disabled = True
                self._warn_once(exc)

        if self._delegate is not None:
            try:
                return self._delegate(input)
            except Exception as exc:
                self._delegate = None
                self._delegate_disabled = True
                self._warn_once(exc)

        return self._fallback(input)

    def _warn_once(self, exc: Exception) -> None:
        if not self._fallback_warned:
            logger.warning(
                "Default Chroma embeddings unavailable; using local hash embeddings instead: %s",
                exc,
            )
            self._fallback_warned = True


def get_embedding_function() -> EmbeddingFunction[Documents]:
    """Return the shared embedding function used across collection access."""
    global _EMBEDDING_FUNCTION
    if _EMBEDDING_FUNCTION is None:
        _EMBEDDING_FUNCTION = _SafeEmbeddingFunction()
    return _EMBEDDING_FUNCTION


def get_client(palace_path: str, ensure_path: bool = True):
    """Create a PersistentClient, optionally creating the palace directory first."""
    if ensure_path:
        os.makedirs(palace_path, exist_ok=True)
        try:
            os.chmod(palace_path, 0o700)
        except (OSError, NotImplementedError):
            pass
    return chromadb.PersistentClient(path=palace_path)


def get_collection(
    palace_path: str,
    collection_name: str = "mempalace_drawers",
    create: bool = True,
):
    """Open a palace collection with the shared embedding function."""
    client = get_client(palace_path, ensure_path=create)
    embedding_function = get_embedding_function()
    if create:
        return client.get_or_create_collection(
            collection_name,
            embedding_function=embedding_function,
        )
    return client.get_collection(
        collection_name,
        embedding_function=embedding_function,
    )


def distance_to_similarity(distance: float) -> float:
    """Convert a Chroma distance into a stable 0.0-1.0 similarity score."""
    try:
        similarity = 1.0 - float(distance)
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, min(1.0, similarity)), 3)


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
