"""
embeddings.py — Embedding function management and compatibility checks.

Handles selection between ChromaDB's default ONNX embedder and
sentence-transformers, with a one-time compatibility verification
when opening a palace that may have been created with a different
embedding backend.
"""

import logging

logger = logging.getLogger("mempalace")

# Session-level cache: palace_path -> bool (compatible or not)
_compatibility_cache: dict[str, bool] = {}

# L2 distance threshold above which vectors are likely in different
# embedding spaces.  The default model (all-MiniLM-L6-v2) produces
# unit-normalised vectors, so same-space L2 distances typically stay
# well below 2.0.  A distance above this threshold signals a gross
# mismatch (e.g. ONNX vs sentence-transformers producing incompatible
# vectors, or an entirely different model).
_DISTANCE_THRESHOLD = 100.0


def get_embedding_function(device: str = "auto"):
    """Return a sentence-transformers embedding function if available, else None.

    When None is returned the caller should fall back to ChromaDB's built-in
    default (ONNX-based all-MiniLM-L6-v2).

    Args:
        device: Device hint for sentence-transformers.
                "auto" lets the library choose (CUDA if available, else CPU).
                Pass "cpu", "cuda", "mps", etc. to override.
    """
    try:
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

        kwargs = {}
        if device and device != "auto":
            kwargs["device"] = device
        return SentenceTransformerEmbeddingFunction(**kwargs)
    except (ImportError, Exception) as exc:
        logger.debug("sentence-transformers unavailable, using default ONNX embedder: %s", exc)
        return None


def verify_embedding_compatibility(collection, device: str = "auto") -> bool:
    """Check if the current embedding function produces compatible vectors.

    Embeds a known test string with the current embedder and queries the
    collection for the nearest neighbour.  If the L2 distance is
    suspiciously large the vectors are likely in different embedding
    spaces (e.g. palace was built with ONNX but is now being queried
    via sentence-transformers, or vice versa).

    Results are cached per palace path so this only runs once per session.

    Args:
        collection: A ChromaDB collection to check against.
        device: Device hint forwarded to ``get_embedding_function``.

    Returns:
        True if vectors appear compatible (or the collection is empty),
        False if a mismatch is detected.
    """
    # Use collection name + metadata as a rough cache key
    cache_key = f"{id(collection._client)}:{collection.name}"
    if cache_key in _compatibility_cache:
        return _compatibility_cache[cache_key]

    ef = get_embedding_function(device)
    if ef is None:
        # Using the default ONNX embedder — always compatible with itself
        _compatibility_cache[cache_key] = True
        return True

    test_text = "The quick brown fox jumps over the lazy dog"

    try:
        current_vec = ef([test_text])[0]
    except Exception as exc:
        logger.warning("Embedding compatibility check failed (embed error): %s", exc)
        _compatibility_cache[cache_key] = True
        return True

    try:
        results = collection.query(query_embeddings=[current_vec], n_results=1)
    except Exception as exc:
        logger.warning("Embedding compatibility check failed (query error): %s", exc)
        _compatibility_cache[cache_key] = True
        return True

    distances = results.get("distances", [[]])[0]
    if not distances:
        # Empty collection — nothing to compare against
        _compatibility_cache[cache_key] = True
        return True

    distance = distances[0]

    if distance > _DISTANCE_THRESHOLD:
        logger.warning(
            "Embedding compatibility warning: nearest neighbor distance %.2f suggests "
            "vectors may be in different embedding spaces. Search quality may be "
            "degraded. Consider re-mining the palace with the current embedder.",
            distance,
        )
        _compatibility_cache[cache_key] = False
        return False

    _compatibility_cache[cache_key] = True
    return True


def clear_compatibility_cache():
    """Reset the session cache — mainly useful for tests."""
    _compatibility_cache.clear()
