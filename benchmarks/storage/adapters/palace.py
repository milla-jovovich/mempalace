"""PalaceStore adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from palace_store import PalaceStore

from ..interface import QueryHit


class PalaceAdapter:
    name = "palace"
    is_exact = True  # flat brute-force f32 cosine

    def __init__(self, path: str | Path, *, parallel_query: bool = False):
        self._store = PalaceStore(path, parallel_query=parallel_query)

    def upsert(
        self,
        ids: list[str],
        vectors: np.ndarray,
        metadatas: list[dict[str, Any]],
        texts: list[str],
    ) -> None:
        self._store.upsert(ids, vectors, metadatas, texts)

    def query(
        self,
        query_vector: np.ndarray,
        k: int,
        where: dict[str, Any] | None = None,
    ) -> list[QueryHit]:
        rows = self._store.query(query_vector, k, where=where)
        return [
            QueryHit(id=r.id, score=r.score, wing=r.wing, room=r.room) for r in rows
        ]

    def get(self, where: dict[str, Any]) -> list[dict[str, Any]]:
        return self._store.get(where)

    def delete(self, where: dict[str, Any]) -> int:
        return self._store.delete(where)

    def count(self) -> int:
        return self._store.count()

    def disk_bytes(self) -> int:
        return self._store.disk_bytes()["total"]

    def warm(self, *, mlock: bool = False) -> None:
        self._store.warm_pages(mlock=mlock)

    def close(self) -> None:
        self._store.close()
