"""Adapter interface shared by every storage candidate in the benchmark.

An adapter is the thinnest wrapper around a store that exposes:

    upsert(ids, vectors, metadatas, texts)       -- bulk write
    query(query_vector, k, where=None)           -- top-k cosine
    get(where)                                   -- metadata-only fetch
    delete(where)                                -- bulk delete
    count()                                      -- live row count
    disk_bytes()                                 -- on-disk size
    close()                                      -- release resources

All vectors passed in and out are ``numpy.float32`` with shape ``(N, 384)``
(ingest) or ``(384,)`` (query). Vectors are assumed to be L2-normalized by
the caller — no adapter is allowed to normalize on ingest, because that's a
compute cost we don't want blamed on the store.

Results from ``query()`` are a list of ``QueryHit`` dataclasses rather than
the native result type of any particular store. This keeps the correctness
gate (top-k set equality across adapters) trivial to write.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np


VECTOR_DIM = 384


@dataclass(frozen=True)
class QueryHit:
    id: str
    score: float
    wing: str
    room: str


class StoreAdapter(Protocol):
    """The contract every storage candidate must implement."""

    name: str  # e.g. "palace", "chroma"
    # True if the adapter computes exact cosine scores. Approximate
    # adapters (int8 quantization, ANN) set this to False so the
    # correctness gate applies a relaxed threshold.
    is_exact: bool

    def upsert(
        self,
        ids: list[str],
        vectors: np.ndarray,
        metadatas: list[dict[str, Any]],
        texts: list[str],
    ) -> None: ...

    def query(
        self,
        query_vector: np.ndarray,
        k: int,
        where: dict[str, Any] | None = None,
    ) -> list[QueryHit]: ...

    def get(self, where: dict[str, Any]) -> list[dict[str, Any]]: ...

    def delete(self, where: dict[str, Any]) -> int: ...

    def count(self) -> int: ...

    def disk_bytes(self) -> int: ...

    def warm(self, *, mlock: bool = False) -> None:
        """Optional: pre-warm any on-disk state into memory.

        PalaceStore implements this by touching every shard's mmap'd
        pages (and optionally pinning them with ``mlock``). Chroma is a
        no-op because its HNSW graph is already resident after open.
        Default implementation is a no-op so existing adapters compile.
        """
        return

    def close(self) -> None: ...
