"""Tests for the ChromaDB compat shim.

These exercise the narrow Chroma API surface that mempalace actually
calls (upsert/add/query/get/delete/count, PersistentClient,
get_collection / get_or_create_collection). We inject a deterministic
stub embedder so tests don't require fastembed or sentence-transformers
to be installed.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from palace_store import compat as cdb
from palace_store.store import VECTOR_DIM


# ── stub embedder ─────────────────────────────────────────────────────


def _hash_vec(text: str) -> np.ndarray:
    """Deterministic pseudo-embedding: expand a stable hash to 384 floats.

    Two identical strings produce bit-identical vectors; different strings
    produce different vectors. Not semantically meaningful, but the shim
    doesn't care — it just passes vectors through to the store.
    """
    h = hashlib.sha256(text.encode("utf-8")).digest()
    # Seed a generator from the hash, draw D floats
    seed = int.from_bytes(h[:8], "big")
    rng = np.random.default_rng(seed)
    return rng.standard_normal(VECTOR_DIM, dtype=np.float32)


def stub_embedder(texts):
    return np.stack([_hash_vec(t) for t in texts])


# ── fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def client(tmp_path):
    c = cdb.PersistentClient(path=tmp_path / "palace_compat")
    yield c


@pytest.fixture
def col(client):
    return client.get_or_create_collection(
        "mempalace_drawers",
        embedding_function=stub_embedder,
    )


# ── basic API round-trips ─────────────────────────────────────────────


def test_client_open_and_count_empty(client):
    col = client.get_or_create_collection("mempalace_drawers", embedding_function=stub_embedder)
    assert col.count() == 0


def test_upsert_then_count(col):
    col.upsert(
        ids=["a", "b", "c"],
        documents=["alpha", "beta", "gamma"],
        metadatas=[
            {"wing": "w1", "room": "r1", "source_file": "f1.txt", "chunk_index": 0},
            {"wing": "w1", "room": "r1", "source_file": "f1.txt", "chunk_index": 1},
            {"wing": "w2", "room": "r2", "source_file": "f2.txt", "chunk_index": 0},
        ],
    )
    assert col.count() == 3


def test_add_is_alias_for_upsert(col):
    col.add(
        ids=["a"],
        documents=["alpha"],
        metadatas=[{"wing": "w1", "room": "r1"}],
    )
    assert col.count() == 1


def test_query_returns_chroma_shape(col):
    col.upsert(
        ids=["a", "b", "c"],
        documents=["alpha", "beta", "gamma"],
        metadatas=[
            {"wing": "w1", "room": "r1"},
            {"wing": "w1", "room": "r1"},
            {"wing": "w2", "room": "r2"},
        ],
    )
    res = col.query(query_texts=["alpha"], n_results=3)
    # Chroma's shape: {"ids": [[...]], "documents": [[...]], ...}
    assert "ids" in res
    assert "documents" in res
    assert "distances" in res
    assert "metadatas" in res
    assert len(res["ids"]) == 1  # 1 query
    assert len(res["ids"][0]) == 3  # 3 results
    # "alpha" self-query should hit "a" first (same embedding)
    assert res["ids"][0][0] == "a"
    # Distances are [0, 2] for cosine
    assert all(0.0 <= d <= 2.0 for d in res["distances"][0])


def test_query_with_where_single_key(col):
    col.upsert(
        ids=["a", "b", "c"],
        documents=["alpha", "beta", "gamma"],
        metadatas=[
            {"wing": "w1", "room": "r1"},
            {"wing": "w2", "room": "r2"},
            {"wing": "w1", "room": "r2"},
        ],
    )
    res = col.query(query_texts=["anything"], n_results=5, where={"wing": "w1"})
    assert set(res["ids"][0]) == {"a", "c"}


def test_query_with_where_compound_and(col):
    col.upsert(
        ids=["a", "b", "c", "d"],
        documents=["w1r1", "w1r2", "w2r1", "w2r2"],
        metadatas=[
            {"wing": "w1", "room": "r1"},
            {"wing": "w1", "room": "r2"},
            {"wing": "w2", "room": "r1"},
            {"wing": "w2", "room": "r2"},
        ],
    )
    res = col.query(
        query_texts=["anything"],
        n_results=5,
        where={"$and": [{"wing": "w1"}, {"room": "r2"}]},
    )
    assert res["ids"][0] == ["b"]


def test_get_by_ids(col):
    col.upsert(
        ids=["a", "b", "c"],
        documents=["alpha", "beta", "gamma"],
        metadatas=[
            {"wing": "w1", "room": "r1", "source_file": "f1.txt"},
            {"wing": "w1", "room": "r2", "source_file": "f2.txt"},
            {"wing": "w2", "room": "r1", "source_file": "f3.txt"},
        ],
    )
    res = col.get(ids=["a", "c"])
    assert set(res["ids"]) == {"a", "c"}
    assert len(res["documents"]) == 2
    # metadatas should round-trip source_file
    srcs = {m["source_file"] for m in res["metadatas"]}
    assert srcs == {"f1.txt", "f3.txt"}


def test_get_by_where_source_file(col):
    """Mempalace uses this for its existence check in miner.py."""
    col.upsert(
        ids=["a", "b"],
        documents=["alpha", "beta"],
        metadatas=[
            {"wing": "w1", "room": "r1", "source_file": "/abs/f1.txt", "chunk_index": 0},
            {"wing": "w1", "room": "r1", "source_file": "/abs/f1.txt", "chunk_index": 1},
        ],
    )
    res = col.get(where={"source_file": "/abs/f1.txt"}, limit=1)
    assert len(res["ids"]) == 1


def test_get_with_limit_and_offset(col):
    # Zero-pad so lexicographic and numeric order coincide — mempalace
    # itself uses hash-suffixed ids, so this is realistic.
    col.upsert(
        ids=[f"d{i:02d}" for i in range(20)],
        documents=[f"t{i}" for i in range(20)],
        metadatas=[{"wing": "w", "room": "r"} for _ in range(20)],
    )
    res = col.get(limit=5, offset=10)
    assert len(res["ids"]) == 5
    assert res["ids"] == [f"d{i:02d}" for i in range(10, 15)]

    # Total paginated walk should cover every id exactly once
    all_ids: list[str] = []
    offset = 0
    while True:
        batch = col.get(limit=7, offset=offset)
        if not batch["ids"]:
            break
        all_ids.extend(batch["ids"])
        offset += 7
    assert sorted(all_ids) == sorted(f"d{i:02d}" for i in range(20))


def test_delete_by_ids(col):
    col.upsert(
        ids=["a", "b", "c"],
        documents=["alpha", "beta", "gamma"],
        metadatas=[
            {"wing": "w", "room": "r"},
            {"wing": "w", "room": "r"},
            {"wing": "w", "room": "r"},
        ],
    )
    col.delete(ids=["b"])
    assert col.count() == 2
    res = col.get(ids=["a", "b", "c"])
    assert set(res["ids"]) == {"a", "c"}


def test_delete_by_where_source_file(col):
    """Mempalace's re-mine flow uses this — miner.py:445."""
    col.upsert(
        ids=["a", "b", "c"],
        documents=["alpha", "beta", "gamma"],
        metadatas=[
            {"wing": "w", "room": "r", "source_file": "f1.txt", "chunk_index": 0},
            {"wing": "w", "room": "r", "source_file": "f1.txt", "chunk_index": 1},
            {"wing": "w", "room": "r", "source_file": "f2.txt", "chunk_index": 0},
        ],
    )
    col.delete(where={"source_file": "f1.txt"})
    assert col.count() == 1
    res = col.get(ids=["a", "b", "c"])
    assert res["ids"] == ["c"]


def test_get_or_create_is_idempotent(client):
    a = client.get_or_create_collection("x", embedding_function=stub_embedder)
    b = client.get_or_create_collection("x", embedding_function=stub_embedder)
    assert a is b


def test_compound_where_conflict_raises(col):
    """Confliciting AND clauses on the same key should fail loudly."""
    with pytest.raises(ValueError):
        col.query(
            query_texts=["x"],
            n_results=5,
            where={"$and": [{"wing": "a"}, {"wing": "b"}]},
        )


def test_query_with_precomputed_embeddings_bypasses_embedder(col):
    """Passing query_embeddings should not invoke the embedder."""

    def raising_embedder(texts):
        raise AssertionError("embedder should not run when embeddings are given")

    c = cdb.PersistentClient(path=col._store.root).get_or_create_collection(
        "mempalace_drawers", embedding_function=raising_embedder
    )
    v = stub_embedder(["query"])
    # First ingest something using the stub so there's data to query
    col.upsert(
        ids=["a"],
        documents=["alpha"],
        metadatas=[{"wing": "w", "room": "r"}],
    )
    res = c.query(query_embeddings=v, n_results=1)
    assert len(res["ids"]) == 1
