"""Storage backend implementations for MemPalace."""

from .base import BaseCollection
from .chroma import ChromaBackend, ChromaCollection

# Conditional import for Qdrant backend (optional dependency)
try:
    from .qdrant import QdrantBackend, QdrantCollection

    __all__ = ["BaseCollection", "ChromaBackend", "ChromaCollection", "QdrantBackend", "QdrantCollection"]
except ImportError:
    __all__ = ["BaseCollection", "ChromaBackend", "ChromaCollection"]
