"""
Shared embedding function factory for MemPalace.

Creates a SentenceTransformer embedding function with CUDA support when available.
Falls back to ChromaDB's default ONNX embedder when sentence-transformers is not installed.
"""

import logging

logger = logging.getLogger("mempalace.embeddings")

DEFAULT_MODEL = "all-MiniLM-L6-v2"
BATCH_SIZE = 100

_cached_ef = None
_cached_device = None


def _detect_device(preference: str = "auto") -> str:
    if preference == "cpu":
        return "cpu"
    if preference in ("cuda", "auto"):
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
    return "cpu"


def get_embedding_function(device: str = "auto"):
    global _cached_ef, _cached_device
    if _cached_ef is not None and _cached_device == device:
        return _cached_ef

    try:
        from chromadb.utils import embedding_functions
        resolved = _detect_device(device)
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=DEFAULT_MODEL,
            device=resolved,
        )
        logger.info(f"Embeddings: SentenceTransformer on {resolved}")
        _cached_ef = ef
        _cached_device = device
        return ef
    except Exception:
        logger.info("Embeddings: ChromaDB default (ONNX/CPU)")
        _cached_ef = None
        _cached_device = device
        return None


def init(device: str = "auto"):
    get_embedding_function(device)


def get_collection(client, name: str, create: bool = False, device: str = "auto"):
    ef = get_embedding_function(device)
    kwargs = {"name": name}
    if ef is not None:
        kwargs["embedding_function"] = ef
    if create:
        return client.get_or_create_collection(**kwargs)
    return client.get_collection(**kwargs)


def flush_batch(collection, batch: list) -> int:
    if not batch:
        return 0
    try:
        collection.add(
            ids=[d["id"] for d in batch],
            documents=[d["document"] for d in batch],
            metadatas=[d["metadata"] for d in batch],
        )
        return len(batch)
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            added = 0
            for d in batch:
                try:
                    collection.add(ids=[d["id"]], documents=[d["document"]], metadatas=[d["metadata"]])
                    added += 1
                except Exception:
                    pass
            return added
        raise
