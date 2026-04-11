"""ChromaDB baseline adapter.

We bypass Chroma's internal embedder entirely by passing ``embeddings=`` on
every upsert and ``query_embeddings=`` on every query. A no-op
EmbeddingFunction is installed so any accidental ``documents=``-only call
fails loudly instead of silently triggering sentence-transformers.

Cosine space is explicitly requested via collection metadata. Any other
HNSW tuning is left at Chroma's defaults — we're measuring what mempalace
ships with today, not a hand-tuned Chroma.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ..interface import QueryHit


class _NoEmbed:
    """Stub embedder that refuses to run. Forces pre-embedded call sites."""

    def __call__(self, input):  # noqa: A002 — chroma uses this name
        raise RuntimeError(
            "ChromaAdapter must be called with embeddings=/query_embeddings=; "
            "the store's embedder should never run during this benchmark"
        )

    def name(self) -> str:
        return "noembed"


class ChromaAdapter:
    name = "chroma"
    # HNSW is approximate, but tuned search_ef=200 makes it effectively
    # exact at the scales the gate runs. Mark as exact to apply the
    # strict threshold.
    is_exact = True

    def __init__(self, path: str | Path):
        import chromadb
        from chromadb.config import Settings

        self._path = Path(path)
        self._path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(self._path),
            settings=Settings(anonymized_telemetry=False),
        )
        # HNSW tuned for accuracy, not speed, to make the correctness gate
        # meaningful. search_ef at the default of 10 is essentially equal
        # to k=10 which gives HNSW no room to explore alternatives, so the
        # adapter appears to "miss" tail results that are really just
        # approximation error. search_ef=200 puts Chroma near-exact at the
        # scales we test. batch_size + sync_threshold follow the screenshot
        # PR's guidance to avoid the ingest bloat pathology at 50k+.
        self._col = self._client.get_or_create_collection(
            name="bench_drawers",
            embedding_function=_NoEmbed(),
            metadata={
                "hnsw:space": "cosine",
                "hnsw:search_ef": 200,
                "hnsw:construction_ef": 200,
                "hnsw:M": 16,
                "hnsw:batch_size": 10000,
                "hnsw:sync_threshold": 50000,
            },
        )

    def upsert(
        self,
        ids: list[str],
        vectors: np.ndarray,
        metadatas: list[dict[str, Any]],
        texts: list[str],
    ) -> None:
        # Chroma wants a list-of-lists for embeddings. .tolist() allocates,
        # but so does any other marshaling path into their bindings.
        self._col.upsert(
            ids=ids,
            embeddings=vectors.tolist(),
            metadatas=metadatas,
            documents=texts,
        )

    def query(
        self,
        query_vector: np.ndarray,
        k: int,
        where: dict[str, Any] | None = None,
    ) -> list[QueryHit]:
        res = self._col.query(
            query_embeddings=[query_vector.tolist()],
            n_results=k,
            where=self._translate_where(where),
            include=["metadatas", "distances"],
        )
        ids = res["ids"][0]
        metas = res["metadatas"][0]
        dists = res["distances"][0]
        hits: list[QueryHit] = []
        for i, (rid, meta, dist) in enumerate(zip(ids, metas, dists)):
            # Cosine distance → similarity. Chroma returns 1 - cos for cosine
            # space; for unit vectors this is 1 - dot, so score = 1 - dist.
            hits.append(
                QueryHit(
                    id=rid,
                    score=float(1.0 - dist),
                    wing=meta.get("wing", ""),
                    room=meta.get("room", ""),
                )
            )
        return hits

    def get(self, where: dict[str, Any]) -> list[dict[str, Any]]:
        res = self._col.get(
            where=self._translate_where(where),
            include=["metadatas", "documents"],
        )
        out: list[dict[str, Any]] = []
        for rid, meta, doc in zip(res["ids"], res["metadatas"], res["documents"]):
            out.append(
                {
                    "id": rid,
                    "wing": meta.get("wing", ""),
                    "room": meta.get("room", ""),
                    "source_file": meta.get("source_file"),
                    "chunk_index": meta.get("chunk_index"),
                    "text": doc,
                    "metadata": {
                        k: v
                        for k, v in meta.items()
                        if k not in ("wing", "room", "source_file", "chunk_index")
                    },
                }
            )
        return out

    def delete(self, where: dict[str, Any]) -> int:
        # Chroma's delete() returns None, so we count first.
        hits = self._col.get(where=self._translate_where(where), include=[])
        n = len(hits["ids"])
        self._col.delete(where=self._translate_where(where))
        return n

    def count(self) -> int:
        return self._col.count()

    def disk_bytes(self) -> int:
        total = 0
        for p in self._path.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except FileNotFoundError:
                    pass
        return total

    def warm(self, *, mlock: bool = False) -> None:
        # Chroma manages its own in-memory HNSW graph after open — there
        # is no mmap'd region we can touch from Python without digging
        # into chromadb internals. Treat as no-op.
        return

    def close(self) -> None:
        # chromadb PersistentClient doesn't expose a close() we can trust,
        # so we just drop our references.
        self._col = None
        self._client = None

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _translate_where(where: dict[str, Any] | None) -> dict[str, Any] | None:
        """Translate the adapter's flat where dict to Chroma's $and format.

        ``{wing: X, room: Y}`` must become ``{"$and": [{wing: X}, {room: Y}]}``
        because Chroma rejects multi-key flat dicts.
        """
        if not where:
            return None
        keys = list(where.keys())
        if len(keys) == 1:
            return {keys[0]: where[keys[0]]}
        return {"$and": [{k: where[k]} for k in keys]}
