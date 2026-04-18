"""
embedding.py — Centralized embedding model configuration.

Single source of truth for which embedding model the palace uses.
Resolves model from ChromaDB collection metadata (stamped at build time),
with fallback to legacy default for existing palaces.
"""

import os

# Legacy model — used by all palaces created before this feature.
# ChromaDB 0.6.3 uses this as its built-in default (384 dimensions).
DEFAULT_MODEL = "all-MiniLM-L6-v2"

# Model for newly created palaces — better search quality (768 dimensions).
NEW_PALACE_MODEL = "all-mpnet-base-v2"


def get_embedding_function(model_name: str):
    """Return a ChromaDB-compatible embedding function for the given model.

    Uses ChromaDB's built-in SentenceTransformerEmbeddingFunction which
    auto-downloads and caches the model on first use.
    """
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    return SentenceTransformerEmbeddingFunction(model_name=model_name)


def resolve_model_from_metadata(collection_metadata: dict) -> str:
    """Resolve which embedding model was used from collection metadata.

    Returns DEFAULT_MODEL if metadata is missing or doesn't contain the key —
    this means the palace was created before embedding model tracking existed.
    """
    if collection_metadata and "embedding_model" in collection_metadata:
        return collection_metadata["embedding_model"]
    return DEFAULT_MODEL


def new_palace_model(config=None) -> str:
    """Return the embedding model to use for new palace creation.

    Resolution: env var > config > NEW_PALACE_MODEL constant.
    """
    env = os.environ.get("MEMPALACE_EMBEDDING_MODEL")
    if env:
        return env
    if config is not None and hasattr(config, "embedding_model"):
        return config.embedding_model
    return NEW_PALACE_MODEL
