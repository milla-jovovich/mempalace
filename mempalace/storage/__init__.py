"""Storage abstraction layer for MemPalace.

Provides a unified interface for different storage backends (ChromaDB, Elasticsearch).
"""

from .base import BaseCollection
from .factory import get_collection

__all__ = ["BaseCollection", "get_collection"]
