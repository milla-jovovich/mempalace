"""ChromaDB-compatible shim backed by PalaceStore.

The goal of this module is a drop-in replacement for the narrow subset of
ChromaDB's API that mempalace actually uses. A caller can swap::

    import chromadb

for::

    from palace_store import compat as chromadb

and the rest of their code keeps working (provided it only touches the
methods listed below — see the full mempalace audit in the POC design
notes for what's covered).

Surface implemented:

    chromadb.PersistentClient(path=...)
        → get_collection(name)
        → get_or_create_collection(name, metadata=..., embedding_function=...)
        → delete_collection(name)
        → reset()
        → list_collections()

    Collection
        .add(ids=, documents=, metadatas=, embeddings=)
        .upsert(ids=, documents=, metadatas=, embeddings=)
        .query(query_texts=, query_embeddings=, n_results=, where=, include=)
        .get(ids=, where=, limit=, offset=, include=)
        .delete(ids=, where=)
        .count()
        .name

Things deliberately not covered because mempalace doesn't call them:
Where filtering with ``$or``, ``$gt``, etc.; ``where_document`` text
filtering; the ``peek()``, ``modify()``, and ``update()`` methods; client
reset/persist hooks.

Embedding model:
    By default we look for ``fastembed`` with the MiniLM model (~50MB,
    matches the default sentence-transformers output). If ``fastembed`` is
    not installed, we fall back to ``sentence-transformers``. Callers can
    override by passing ``embedding_function=...`` on collection creation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np

from .store import VECTOR_DIM, PalaceStore


# ── Chroma-compatible exception types ─────────────────────────────────


class InvalidCollectionException(Exception):
    """Raised by get_collection() when the named collection has never been
    created. Mirrors ``chromadb.errors.InvalidCollectionException`` which
    mempalace catches as a generic ``Exception`` at its call sites.
    """


# ── embedder loading (lazy) ───────────────────────────────────────────


Embedder = Callable[[Sequence[str]], np.ndarray]


def _load_default_embedder() -> Embedder:
    """Return an Embedder compatible with Chroma's all-MiniLM-L6-v2 output.

    Chroma's default embedder is ONNX MiniLM L6 v2 via their own runtime;
    the checkpoint matches ``sentence-transformers/all-MiniLM-L6-v2``, so
    any backend loading that model yields functionally-equivalent vectors
    for our purposes. We try fastembed first because it's lighter on
    disk than sentence-transformers, then fall back.

    Only ``ImportError`` is treated as "try the next backend" — any other
    exception from instantiation is re-raised so bugs surface loudly
    instead of silently falling through to a stub.
    """
    errors: list[str] = []

    # fastembed: small, fast, no PyTorch dependency
    try:
        from fastembed import TextEmbedding  # type: ignore

        model = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")

        def embed_fastembed(texts: Sequence[str]) -> np.ndarray:
            return np.asarray(list(model.embed(list(texts))), dtype=np.float32)

        return embed_fastembed
    except ImportError as e:
        errors.append(f"fastembed: {e}")

    # sentence-transformers: the canonical reference
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore

        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

        def embed_st(texts: Sequence[str]) -> np.ndarray:
            arr = model.encode(list(texts), normalize_embeddings=False)
            return np.asarray(arr, dtype=np.float32)

        return embed_st
    except ImportError as e:
        errors.append(f"sentence-transformers: {e}")

    # Last-resort: Chroma's own default embedder. Matches mempalace's
    # current default exactly (same ONNX MiniLM L6 v2 checkpoint), so
    # there's zero recall drift from this fallback. Only ImportError is
    # swallowed — a real instantiation bug must propagate.
    #
    # Note the explicit ``import chromadb`` first: chromadb 0.5.x has a
    # fragile import ordering where ``chromadb/__init__.py`` must fully
    # execute before anything from ``chromadb.utils.embedding_functions``
    # is touched, otherwise the ``ONNXMiniLM_L6_V2`` name is unbound
    # inside ``DefaultEmbeddingFunction``. Diving straight into the
    # submodule triggers that bug during subsequent nested imports.
    try:
        import chromadb  # noqa: F401  (prime chromadb's top-level init)
        from chromadb.utils.embedding_functions import (  # type: ignore
            DefaultEmbeddingFunction,
        )
    except ImportError as e:
        errors.append(f"chromadb: {e}")
        raise RuntimeError(
            "palace_store.compat needs an embedder. Install one of: "
            "`fastembed`, `sentence-transformers`, or `chromadb`. "
            "Or pass embedding_function=... when creating the collection. "
            f"Tried: {'; '.join(errors)}"
        )

    ef = DefaultEmbeddingFunction()

    def embed_chroma(texts: Sequence[str]) -> np.ndarray:
        return np.asarray(ef(list(texts)), dtype=np.float32)

    return embed_chroma


_DEFAULT_EMBEDDER: Embedder | None = None


def _get_default_embedder() -> Embedder:
    """Lazy-load and cache the default embedder.

    If loading fails, we do NOT cache the failure — a subsequent call
    will retry. This prevents a single flaky instantiation (common when
    tests run before a model file has been fully downloaded) from
    poisoning the rest of the test session.
    """
    global _DEFAULT_EMBEDDER
    if _DEFAULT_EMBEDDER is None:
        _DEFAULT_EMBEDDER = _load_default_embedder()
    return _DEFAULT_EMBEDDER


# ── where-clause translation ──────────────────────────────────────────


def _translate_where(where: dict[str, Any] | None) -> dict[str, Any] | None:
    """Translate Chroma's where syntax to PalaceStore's flat dict.

    Chroma supports ``{"a": 1}``, ``{"$and": [{"a": 1}, {"b": 2}]}``, and
    operator forms like ``{"a": {"$eq": 1}}``. PalaceStore takes a flat
    ``{key: value}`` mapping where all entries are AND-ed together.

    Anything we can't represent (``$or``, ``$in``, comparisons) raises —
    silently dropping would be a correctness regression and mempalace
    doesn't use those anyway.
    """
    if not where:
        return None
    if "$and" in where:
        merged: dict[str, Any] = {}
        for clause in where["$and"]:
            inner = _translate_where(clause)
            if inner:
                for k, v in inner.items():
                    if k in merged and merged[k] != v:
                        raise ValueError(
                            f"conflicting AND clauses on key {k!r}: " f"{merged[k]!r} vs {v!r}"
                        )
                    merged[k] = v
        return merged
    if "$or" in where:
        raise NotImplementedError("palace_store.compat doesn't support $or")
    # Plain {key: value} or {key: {"$eq": value}} form
    out: dict[str, Any] = {}
    for k, v in where.items():
        if isinstance(v, dict):
            if "$eq" in v:
                out[k] = v["$eq"]
            else:
                raise NotImplementedError(
                    f"palace_store.compat only supports $eq operator, got {v!r}"
                )
        else:
            out[k] = v
    return out


# ── helpers ───────────────────────────────────────────────────────────


def _l2_normalize(v: np.ndarray) -> np.ndarray:
    """In-place-safe L2 normalize. Zero rows pass through unchanged."""
    if v.ndim == 1:
        norm = float(np.linalg.norm(v))
        return (v / norm).astype(np.float32) if norm > 0 else v.astype(np.float32)
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (v / norms).astype(np.float32)


def _to_f32_matrix(embeddings: Any) -> np.ndarray:
    """Accept list-of-lists or numpy arrays; return C-contig f32 (N, D)."""
    arr = np.asarray(embeddings, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    if arr.shape[1] != VECTOR_DIM:
        raise ValueError(f"expected embedding dim {VECTOR_DIM}, got {arr.shape[1]}")
    return np.ascontiguousarray(arr)


_DEFAULT_WING = "_compat_default"
_DEFAULT_ROOM = "_compat_default"


def _inject_palace_defaults(
    metadatas: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Ensure every metadata dict has wing + room, copying if we need to
    avoid mutating caller state."""
    out: list[dict[str, Any]] = []
    for m in metadatas:
        if "wing" in m and "room" in m:
            out.append(m)
            continue
        copy = dict(m)
        copy.setdefault("wing", _DEFAULT_WING)
        copy.setdefault("room", _DEFAULT_ROOM)
        out.append(copy)
    return out


def _metadata_full(r: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct Chroma-shaped metadata from a PalaceStore row.

    Compat-injected defaults are stripped from the output so callers only
    see the keys they originally set — otherwise ``list(meta.keys())``
    assertions in mempalace's tests pick up phantom wing/room entries.
    """
    m: dict[str, Any] = {}
    if r["wing"] != _DEFAULT_WING:
        m["wing"] = r["wing"]
    if r["room"] != _DEFAULT_ROOM:
        m["room"] = r["room"]
    if r.get("source_file") is not None:
        m["source_file"] = r["source_file"]
    if r.get("chunk_index") is not None:
        m["chunk_index"] = r["chunk_index"]
    extra = r.get("metadata") or {}
    for k, v in extra.items():
        m[k] = v
    return m


# ── Collection ────────────────────────────────────────────────────────


class Collection:
    """ChromaDB-compatible collection backed by a single PalaceStore."""

    def __init__(
        self,
        name: str,
        store: PalaceStore,
        embedder: Embedder,
        metadata: dict[str, Any] | None = None,
    ):
        self.name = name
        self.metadata = metadata or {}
        self._store = store
        self._embed = embedder

    # ── writes ────────────────────────────────────────────────────────

    def add(self, **kwargs: Any) -> None:
        """Chroma's ``add`` is effectively ``upsert`` for our purposes.

        Real Chroma errors on duplicate ids; we treat add() as upsert().
        """
        return self.upsert(**kwargs)

    def upsert(
        self,
        *,
        ids: list[str],
        documents: list[str] | None = None,
        metadatas: list[dict[str, Any]] | None = None,
        embeddings: Any | None = None,
    ) -> None:
        n = len(ids)
        if n == 0:
            return
        if documents is None:
            documents = [""] * n
        if metadatas is None:
            metadatas = [{} for _ in range(n)]
        if len(documents) != n or len(metadatas) != n:
            raise ValueError("ids/documents/metadatas length mismatch")

        if embeddings is None:
            embeddings = self._embed(documents)
        vectors = _l2_normalize(_to_f32_matrix(embeddings))

        # PalaceStore requires wing + room (they're the shard/subshard keys).
        # Chroma doesn't enforce a metadata schema, so mempalace has call
        # sites (notably unit tests and some internal paths) that upsert
        # with only source_file/source_mtime. Inject defaults so those
        # rows still land in a well-defined shard.
        normalized_metas = _inject_palace_defaults(metadatas)

        self._store.upsert(ids, vectors, normalized_metas, documents)

    # ── reads ─────────────────────────────────────────────────────────

    def query(
        self,
        *,
        query_texts: list[str] | None = None,
        query_embeddings: Any | None = None,
        n_results: int = 10,
        where: dict[str, Any] | None = None,
        where_document: dict[str, Any] | None = None,
        include: list[str] | None = None,
    ) -> dict[str, list[Any]]:
        if where_document is not None:
            raise NotImplementedError("palace_store.compat does not support where_document")

        if query_embeddings is None:
            if query_texts is None:
                raise ValueError("need query_texts or query_embeddings")
            query_embeddings = self._embed(query_texts)

        qmat = _l2_normalize(_to_f32_matrix(query_embeddings))
        palace_where = _translate_where(where)

        # Chroma returns results as per-query lists of lists, e.g.
        # {"ids": [[id1, id2, ...]], "distances": [[d1, d2, ...]]}
        all_ids: list[list[str]] = []
        all_docs: list[list[str]] = []
        all_metas: list[list[dict[str, Any]]] = []
        all_dists: list[list[float]] = []
        all_embs: list[list[list[float]]] = []

        want_docs = include is None or "documents" in include
        want_meta = include is None or "metadatas" in include
        want_dist = include is None or "distances" in include
        want_emb = include is not None and "embeddings" in include

        for qv in qmat:
            rows = self._store.query(qv, n_results, where=palace_where)
            all_ids.append([r.id for r in rows])
            all_docs.append([r.text for r in rows] if want_docs else [])
            all_metas.append(
                [
                    _metadata_full(
                        {
                            "wing": r.wing,
                            "room": r.room,
                            "source_file": None,
                            "chunk_index": None,
                            "metadata": r.metadata,
                        }
                    )
                    for r in rows
                ]
                if want_meta
                else []
            )
            # Chroma reports cosine DISTANCE (1 - sim) for cosine space.
            all_dists.append([1.0 - r.score for r in rows] if want_dist else [])
            if want_emb:
                # Embeddings not stored after ingest; we'd have to re-read
                # the shard. mempalace never asks for them, so we stub.
                all_embs.append([[0.0] * VECTOR_DIM for _ in rows])

        out: dict[str, Any] = {"ids": all_ids}
        if want_docs:
            out["documents"] = all_docs
        if want_meta:
            out["metadatas"] = all_metas
        if want_dist:
            out["distances"] = all_dists
        if want_emb:
            out["embeddings"] = all_embs
        return out

    def get(
        self,
        ids: list[str] | None = None,
        *,
        where: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int = 0,
        include: list[str] | None = None,
        where_document: dict[str, Any] | None = None,
    ) -> dict[str, list[Any]]:
        if where_document is not None:
            raise NotImplementedError("palace_store.compat does not support where_document")

        palace_where = _translate_where(where)
        rows = self._store.get(palace_where, ids=ids, limit=limit, offset=offset)

        want_docs = include is None or "documents" in include
        want_meta = include is None or "metadatas" in include

        out: dict[str, Any] = {"ids": [r["id"] for r in rows]}
        if want_docs:
            out["documents"] = [r["text"] for r in rows]
        if want_meta:
            out["metadatas"] = [_metadata_full(r) for r in rows]
        return out

    def delete(
        self,
        ids: list[str] | None = None,
        *,
        where: dict[str, Any] | None = None,
    ) -> None:
        if ids is not None:
            self._store.delete(ids=ids)
            return
        palace_where = _translate_where(where)
        if palace_where:
            self._store.delete(palace_where)

    def count(self) -> int:
        return self._store.count()


# ── Client ────────────────────────────────────────────────────────────


class PersistentClient:
    """Drop-in for ``chromadb.PersistentClient``.

    One ``PalaceStore`` backs the entire client. Each named collection
    gets its own ``Collection`` wrapper; since mempalace only ever uses
    one collection (``mempalace_drawers``), we don't shard the underlying
    store by collection name.
    """

    def __init__(
        self,
        path: str | Path,
        settings: Any = None,
        *,
        dtype: str = "float32",
        parallel_query: bool = False,
        max_workers: int | None = None,
        blas_threads: int | None = 1,
    ):
        # Chroma's Settings are ignored — we don't implement telemetry,
        # auth, or multi-tenancy. The PalaceStore-specific kwargs
        # (parallel_query, max_workers, blas_threads) are passed
        # through so callers going through the shim can still tune the
        # underlying store.
        _ = settings
        self._path = Path(path)
        self._path.mkdir(parents=True, exist_ok=True)
        self._store = PalaceStore(
            self._path,
            dtype=dtype,
            parallel_query=parallel_query,
            max_workers=max_workers,
            blas_threads=blas_threads,
        )
        self._collections: dict[str, Collection] = {}
        # Persisted across process restarts. Chroma distinguishes between
        # "collection doesn't exist" and "collection is empty"; mempalace
        # (at searcher.py and palace.py) relies on that distinction to
        # surface "No palace found" errors. We track created collection
        # names in a tiny JSON file so get_collection() can raise for a
        # collection that has never been written to.
        self._existing_collections_file = self._path / ".compat_collections.json"
        self._existing: set[str] = set()
        if self._existing_collections_file.exists():
            try:
                self._existing = set(json.loads(self._existing_collections_file.read_text()))
            except Exception:
                self._existing = set()

    def _mark_existing(self, name: str) -> None:
        if name in self._existing:
            return
        self._existing.add(name)
        try:
            self._existing_collections_file.write_text(json.dumps(sorted(self._existing)))
        except Exception:
            # Non-fatal: worst case get_collection will raise until we
            # successfully persist on a later create call.
            pass

    def _build_collection(
        self,
        name: str,
        embedding_function: Embedder | None,
        metadata: dict[str, Any] | None,
    ) -> Collection:
        embedder = embedding_function or _get_default_embedder()
        return Collection(name, self._store, embedder, metadata)

    def get_or_create_collection(
        self,
        name: str,
        *,
        metadata: dict[str, Any] | None = None,
        embedding_function: Embedder | None = None,
        **kwargs: Any,
    ) -> Collection:
        self._mark_existing(name)
        if name not in self._collections:
            self._collections[name] = self._build_collection(name, embedding_function, metadata)
        return self._collections[name]

    def get_collection(
        self,
        name: str,
        *,
        embedding_function: Embedder | None = None,
        **kwargs: Any,
    ) -> Collection:
        if name not in self._existing:
            raise InvalidCollectionException(
                f"Collection {name!r} does not exist. Create it with "
                f"get_or_create_collection() first."
            )
        if name not in self._collections:
            self._collections[name] = self._build_collection(name, embedding_function, None)
        return self._collections[name]

    def create_collection(
        self,
        name: str,
        *,
        metadata: dict[str, Any] | None = None,
        embedding_function: Embedder | None = None,
        **kwargs: Any,
    ) -> Collection:
        return self.get_or_create_collection(
            name, metadata=metadata, embedding_function=embedding_function
        )

    def delete_collection(self, name: str) -> None:
        """Drop the named collection and wipe its backing data.

        We don't physically separate collections in the backing store —
        one ``PalaceStore`` holds everything. So "delete collection" ==
        "wipe the store". The ephemeral benchmark path (LongMemEval)
        relies on this to get a clean slate between questions.
        """
        if name in self._collections:
            del self._collections[name]
        self._existing.discard(name)
        try:
            self._existing_collections_file.write_text(json.dumps(sorted(self._existing)))
        except Exception:
            pass
        self._store.truncate()

    def list_collections(self) -> list[Collection]:
        return list(self._collections.values())

    def reset(self) -> bool:
        # Chroma requires allow_reset=True in settings; we don't enforce
        # because mempalace never calls reset() at runtime.
        self._collections.clear()
        self._existing.clear()
        self._store.truncate()
        return True


class EphemeralClient(PersistentClient):
    """Chroma-compat in-memory client, backed by a tempdir.

    LongMemEval's benchmark harness creates one ``EphemeralClient`` at
    module import and uses ``delete_collection`` + ``create_collection``
    to get a clean slate between each of its 500 questions. We mirror
    that semantics by allocating a tempdir on construction and letting
    ``delete_collection`` call ``PalaceStore.truncate()``.

    The tempdir is removed on ``close()`` or garbage collection.
    """

    def __init__(
        self,
        settings: Any = None,
        *,
        dtype: str = "float32",
        **_kwargs: Any,
    ):
        import tempfile

        self._tmpdir = tempfile.mkdtemp(prefix="palace_store_ephemeral_")
        super().__init__(path=self._tmpdir, settings=settings, dtype=dtype)

    def close(self) -> None:
        import shutil

        try:
            self._store.close()
        except Exception:
            pass
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


# ── module-level surface matching ``chromadb`` ────────────────────────


__all__ = [
    "PersistentClient",
    "EphemeralClient",
    "Collection",
    "Embedder",
    "InvalidCollectionException",
]
