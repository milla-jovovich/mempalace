"""Abstract base class for storage backends.

Return format mirrors ChromaDB's dict structure so callers need minimal changes:
    {"ids": [...], "documents": [...], "metadatas": [...], "distances": [...]}
"""

from abc import ABC, abstractmethod


class BaseCollection(ABC):
    """Abstract collection interface matching the ChromaDB collection API surface."""

    @abstractmethod
    def add(self, ids, documents, metadatas=None):
        """Add documents with IDs and optional metadata."""

    @abstractmethod
    def get(self, ids=None, where=None, include=None, limit=None, offset=None):
        """Retrieve documents by IDs or metadata filters.

        Returns dict with keys: ids, documents, metadatas (based on include).
        """

    @abstractmethod
    def query(self, query_texts, n_results=5, where=None, include=None):
        """Semantic search against the collection.

        Returns dict with keys: ids, documents, metadatas, distances
        (each a list-of-lists matching ChromaDB convention).
        """

    @abstractmethod
    def delete(self, ids):
        """Delete documents by IDs."""

    @abstractmethod
    def count(self):
        """Return total document count."""

    @abstractmethod
    def upsert(self, ids, documents, metadatas=None):
        """Insert or update documents."""
