"""
Shared embedding function factory for MemPalace.

Creates a SentenceTransformer embedding function with GPU support when available.
Supports NVIDIA (CUDA), AMD (ROCm), and Apple Silicon (MPS) GPUs.
Falls back to ChromaDB's default ONNX embedder when sentence-transformers is not installed.
"""

import logging

logger = logging.getLogger("mempalace.embeddings")

DEFAULT_MODEL = "all-MiniLM-L6-v2"
BATCH_SIZE = 100

_cached_ef = None
_cached_device = None
_compatibility_checked = set()


def _detect_gpu_vendor() -> str:
    """Detect GPU vendor. Returns 'nvidia', 'amd', 'apple', or 'none'."""
    try:
        import torch

        if torch.cuda.is_available():
            if hasattr(torch.version, "hip") and torch.version.hip is not None:
                return "amd"
            return "nvidia"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "apple"
        return "none"
    except ImportError:
        return "none"


def _detect_device(preference: str = "auto") -> str:
    """Detect the best available device for embeddings.

    Args:
        preference: 'auto' (detect best GPU), 'cuda', 'rocm', 'mps', or 'cpu'

    Returns:
        'cuda' (NVIDIA/AMD), 'mps' (Apple Silicon), or 'cpu'
    """
    if preference == "cpu":
        return "cpu"

    try:
        import torch
    except ImportError:
        return "cpu"

    # Explicit device requests
    if preference in ("cuda", "rocm"):
        if torch.cuda.is_available():
            return "cuda"
        return "cpu"

    if preference == "mps":
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    # Auto-detect: CUDA/ROCm > CPU (skip MPS — benchmarks show MPS is ~2x slower
    # than CPU for small embedding batches on Apple Silicon due to data transfer overhead)
    if preference == "auto":
        if torch.cuda.is_available():
            return "cuda"

    return "cpu"


_GPU_LABELS = {
    "nvidia": "NVIDIA CUDA",
    "amd": "AMD ROCm",
    "apple": "Apple MPS",
}


def get_embedding_function(device: str = "auto"):
    """Get or create a cached embedding function for ChromaDB.

    Supports NVIDIA (CUDA), AMD (ROCm), and Apple Silicon (MPS) GPUs.
    Returns SentenceTransformerEmbeddingFunction when available, None otherwise.
    """
    global _cached_ef, _cached_device
    resolved = _detect_device(device)
    if _cached_ef is not None and _cached_device == resolved:
        return _cached_ef

    try:
        from chromadb.utils import embedding_functions

        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=DEFAULT_MODEL,
            device=resolved,
        )
        if resolved in ("cuda", "mps"):
            vendor = _detect_gpu_vendor()
            label = _GPU_LABELS.get(vendor, resolved.upper())
            logger.info(f"Embeddings: SentenceTransformer on {label}")
        else:
            logger.info("Embeddings: SentenceTransformer on CPU")
        _cached_ef = ef
        _cached_device = resolved
        return ef
    except Exception:
        logger.info("Embeddings: ChromaDB default (ONNX/CPU)")
        _cached_ef = None
        _cached_device = resolved
        return None


def init(device: str = "auto"):
    """Pre-warm the embedding function cache. Call once at startup."""
    get_embedding_function(device)


def verify_embedding_compatibility(collection, device="auto"):
    """One-time check that the current embedder produces compatible vectors with the collection.

    Embeds a known test string, queries the collection for nearest neighbors,
    and checks if the L2 distance suggests compatible embedding spaces.
    Returns True if compatible (or collection is empty), False if mismatch detected.
    """
    test_text = "The quick brown fox jumps over the lazy dog"
    ef = get_embedding_function(device)
    if ef is None:
        return True  # Using default, always compatible

    try:
        current_vec = ef([test_text])[0]
    except Exception:
        return True  # Can't test, assume OK

    try:
        results = collection.query(query_embeddings=[current_vec], n_results=1)
    except Exception:
        return True  # Empty or broken collection

    if not results.get("distances") or not results["distances"][0]:
        return True  # Empty collection

    distance = results["distances"][0][0]
    if distance > 100.0:
        logger.warning(
            "Embedding compatibility check: nearest neighbor L2 distance %.2f suggests "
            "vectors may be in different embedding spaces. Search quality may be degraded. "
            "Consider re-mining with: mempalace mine <dir> --device %s",
            distance,
            device,
        )
        return False
    return True


def get_collection(client, name: str, create: bool = False, device: str = "auto"):
    """Get or create a ChromaDB collection with the shared embedding function."""
    ef = get_embedding_function(device)
    kwargs = {"name": name}
    if ef is not None:
        kwargs["embedding_function"] = ef
    if create:
        return client.get_or_create_collection(**kwargs)
    try:
        return client.get_collection(**kwargs)
    except ValueError:
        logger.warning(
            "Embedding function mismatch for collection %s — falling back to default. "
            "Search quality may be degraded if the collection was built with a different embedder.",
            name,
        )
        col = client.get_collection(name=name)
        if name not in _compatibility_checked:
            verify_embedding_compatibility(col, device)
            _compatibility_checked.add(name)
        return col


CHROMA_MAX_BATCH = 5000  # Safe margin under ChromaDB's 5,461 hard limit


def flush_batch(collection, batch: list) -> int:
    """Add a batch of drawers to ChromaDB, chunked to stay under ChromaDB's max batch size.

    Falls back to one-at-a-time on duplicate errors. Returns count added.
    """
    if not batch:
        return 0
    total_added = 0
    for i in range(0, len(batch), CHROMA_MAX_BATCH):
        chunk = batch[i : i + CHROMA_MAX_BATCH]
        total_added += _flush_chunk(collection, chunk)
    return total_added


def _flush_chunk(collection, chunk: list) -> int:
    """Add a single chunk (guaranteed <= CHROMA_MAX_BATCH) to ChromaDB."""
    try:
        collection.add(
            ids=[d["id"] for d in chunk],
            documents=[d["document"] for d in chunk],
            metadatas=[d["metadata"] for d in chunk],
        )
        return len(chunk)
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            added = 0
            for d in chunk:
                try:
                    collection.add(
                        ids=[d["id"]], documents=[d["document"]], metadatas=[d["metadata"]]
                    )
                    added += 1
                except Exception:
                    pass
            return added
        raise
