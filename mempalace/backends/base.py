"""Abstract collection interface for MemPalace storage backends.

This module defines the backend-agnostic contract that every storage
implementation (ChromaDB, Milvus Lite, etc.) must honor. Callers in the
rest of MemPalace only ever touch the typed methods on ``BaseCollection``
and the ``GetResult`` / ``QueryResult`` dataclasses returned here — they
never see Chroma- or Milvus-specific shapes.

Supported ``where`` DSL (the same subset on every backend):

    {"field": value}                 equality on a metadata field
    {"field": {"$in": [v1, v2]}}     membership
    {"$and": [clause, clause, ...]}  logical AND of nested clauses
    {"$or":  [clause, clause, ...]}  logical OR of nested clauses

A top-level dict with a single metadata key is a single equality clause.
Multiple top-level metadata keys must be wrapped in an explicit ``$and``.

Anything outside this subset (``$ne``, ``$gt``/``$lt``, regex, full-text
predicates, etc.) is NOT part of the portable contract and must not be
relied upon by callers. Backends may raise ``ValueError`` when asked to
translate an unsupported clause.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


# --- include flags ----------------------------------------------------------
# Modeled after ChromaDB's include kwarg. IDs are always returned; any
# combination of the three below can be requested explicitly.

INCLUDE_DOCUMENTS = "documents"
INCLUDE_METADATAS = "metadatas"
INCLUDE_DISTANCES = "distances"

DEFAULT_GET_INCLUDE: tuple = (INCLUDE_DOCUMENTS, INCLUDE_METADATAS)
DEFAULT_QUERY_INCLUDE: tuple = (INCLUDE_DOCUMENTS, INCLUDE_METADATAS, INCLUDE_DISTANCES)


# --- result dataclasses -----------------------------------------------------


@dataclass
class GetResult:
    """Result of a ``BaseCollection.get`` call.

    All fields are flat, single-query lists. ``documents``, ``metadatas``
    are empty when the caller did not request them via ``include=``.
    """

    ids: List[str] = field(default_factory=list)
    documents: List[str] = field(default_factory=list)
    metadatas: List[Dict[str, Any]] = field(default_factory=list)

    _FIELDS = ("ids", "documents", "metadatas")

    def __getitem__(self, key: str) -> Any:
        if key not in self._FIELDS:
            raise KeyError(key)
        return getattr(self, key)

    def __contains__(self, key: str) -> bool:
        return key in self._FIELDS

    def get(self, key: str, default: Any = None) -> Any:
        if key not in self._FIELDS:
            return default
        return getattr(self, key)


@dataclass
class QueryResult:
    """Result of a ``BaseCollection.query`` call.

    Collapses the batch dimension that Chroma uses natively. Every list is
    already the slice for a single query — callers should iterate fields
    directly, not index into ``[0]``.
    """

    ids: List[str] = field(default_factory=list)
    documents: List[str] = field(default_factory=list)
    metadatas: List[Dict[str, Any]] = field(default_factory=list)
    distances: List[float] = field(default_factory=list)

    _FIELDS = ("ids", "documents", "metadatas", "distances")

    def __getitem__(self, key: str) -> Any:
        if key not in self._FIELDS:
            raise KeyError(key)
        return getattr(self, key)

    def __contains__(self, key: str) -> bool:
        return key in self._FIELDS

    def get(self, key: str, default: Any = None) -> Any:
        if key not in self._FIELDS:
            return default
        return getattr(self, key)


# --- abstract interface -----------------------------------------------------


class BaseCollection(ABC):
    """Smallest collection contract the rest of MemPalace relies on."""

    @abstractmethod
    def add(
        self,
        *,
        ids: List[str],
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Insert new records. Raises if any ID already exists."""
        raise NotImplementedError

    @abstractmethod
    def upsert(
        self,
        *,
        ids: List[str],
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Insert new records, overwriting any with the same ID."""
        raise NotImplementedError

    @abstractmethod
    def update(
        self,
        *,
        ids: List[str],
        documents: Optional[List[str]] = None,
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Update existing records in place. Missing IDs raise."""
        raise NotImplementedError

    @abstractmethod
    def query(
        self,
        *,
        query_texts: List[str],
        n_results: int = 10,
        where: Optional[Dict[str, Any]] = None,
        include: Iterable[str] = DEFAULT_QUERY_INCLUDE,
    ) -> QueryResult:
        """Semantic (vector) search.

        ``query_texts`` is a list for API symmetry with Chroma but every
        MemPalace caller passes exactly one query. A :class:`QueryResult`
        is returned with flat lists (the per-query batch is collapsed).
        """
        raise NotImplementedError

    @abstractmethod
    def get(
        self,
        *,
        ids: Optional[List[str]] = None,
        where: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        include: Iterable[str] = DEFAULT_GET_INCLUDE,
    ) -> GetResult:
        """Fetch records by ID and/or filter, with optional pagination."""
        raise NotImplementedError

    @abstractmethod
    def delete(
        self,
        *,
        ids: Optional[List[str]] = None,
        where: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Remove records by ID list or filter (or both)."""
        raise NotImplementedError

    @abstractmethod
    def count(self) -> int:
        """Total number of records in the collection."""
        raise NotImplementedError
