"""Smoke tests for PalaceStore correctness.

These are correctness checks, not benchmarks. They verify that:

- upsert → query returns the planted needle in top-1
- wing filtering restricts the search space correctly
- room filtering further narrows results
- delete(where=source_file) hides rows without corrupting the shard
- re-opening a store recovers all committed data
- brute-force cosine matches a hand-computed reference

The performance work happens in benchmarks/storage/; this file just protects
us from shipping a store that returns wrong answers fast.
"""

from __future__ import annotations

import numpy as np
import pytest

from palace_store import VECTOR_DIM, PalaceStore, l2_normalize


# ── fixtures ──────────────────────────────────────────────────────────


def _random_vectors(n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    raw = rng.standard_normal((n, VECTOR_DIM), dtype=np.float32)
    return l2_normalize(raw)


@pytest.fixture
def store(tmp_path):
    s = PalaceStore(tmp_path / "palace.store")
    yield s
    s.close()


@pytest.fixture
def store_i8(tmp_path):
    """int8-quantized variant. Used to verify the int8 shard passes the
    same correctness invariants, with a relaxed tolerance on exact scores
    since quantization introduces small numeric error (<1% at k=10)."""
    s = PalaceStore(tmp_path / "palace_i8.store", dtype="int8")
    yield s
    s.close()


# ── tests ─────────────────────────────────────────────────────────────


def test_empty_store_returns_no_results(store):
    q = _random_vectors(1, seed=0)[0]
    assert store.query(q, k=5) == []
    assert store.count() == 0
    assert store.count_by_wing() == {}


def test_upsert_and_query_returns_self(store):
    """Querying with a stored vector returns that vector at score ≈ 1.0."""
    vecs = _random_vectors(10, seed=1)
    ids = [f"d{i}" for i in range(10)]
    metas = [{"wing": "alpha", "room": "r1"} for _ in range(10)]
    texts = [f"text_{i}" for i in range(10)]

    store.upsert(ids, vecs, metas, texts)
    assert store.count() == 10

    for i in range(10):
        results = store.query(vecs[i], k=1)
        assert len(results) == 1
        assert results[0].id == f"d{i}"
        assert results[0].score == pytest.approx(1.0, abs=1e-5)


def test_wing_filter_limits_shards(store):
    """A wing filter must not return drawers from other wings."""
    vecs = _random_vectors(20, seed=2)
    ids = [f"d{i}" for i in range(20)]
    metas = [{"wing": "alpha" if i < 10 else "beta", "room": "r1"} for i in range(20)]
    texts = [f"t{i}" for i in range(20)]
    store.upsert(ids, vecs, metas, texts)

    # Use a vector from beta; with the filter we should still get alpha rows.
    beta_vec = vecs[15]
    results = store.query(beta_vec, k=10, where={"wing": "alpha"})
    assert len(results) == 10
    assert all(r.wing == "alpha" for r in results)
    assert all(int(r.id[1:]) < 10 for r in results)


def test_room_filter_applies_post_shard(store):
    vecs = _random_vectors(30, seed=3)
    ids = [f"d{i}" for i in range(30)]
    metas = [{"wing": "alpha", "room": "r_even" if i % 2 == 0 else "r_odd"} for i in range(30)]
    texts = [f"t{i}" for i in range(30)]
    store.upsert(ids, vecs, metas, texts)

    results = store.query(vecs[0], k=5, where={"room": "r_odd"})
    assert len(results) == 5
    assert all(r.room == "r_odd" for r in results)
    # d0 is even, must not appear even though its self-vector is the query.
    assert all(r.id != "d0" for r in results)


def test_wing_and_room_filter_intersection(store):
    vecs = _random_vectors(40, seed=4)
    ids = [f"d{i}" for i in range(40)]
    metas = []
    for i in range(40):
        metas.append(
            {
                "wing": "alpha" if i < 20 else "beta",
                "room": "r_a" if i % 2 == 0 else "r_b",
            }
        )
    texts = [f"t{i}" for i in range(40)]
    store.upsert(ids, vecs, metas, texts)

    results = store.query(vecs[0], k=10, where={"wing": "beta", "room": "r_a"})
    assert len(results) == 10
    assert all(r.wing == "beta" and r.room == "r_a" for r in results)


def test_ranking_matches_exact_cosine(store):
    """PalaceStore ranking must match a hand-computed dot-product reference."""
    vecs = _random_vectors(50, seed=5)
    ids = [f"d{i}" for i in range(50)]
    metas = [{"wing": "alpha", "room": "r"} for _ in range(50)]
    texts = [f"t{i}" for i in range(50)]
    store.upsert(ids, vecs, metas, texts)

    q = _random_vectors(1, seed=99)[0]
    expected_scores = vecs @ q
    expected_order = np.argsort(-expected_scores)[:5]
    expected_ids = [f"d{i}" for i in expected_order]

    results = store.query(q, k=5)
    assert [r.id for r in results] == expected_ids
    for r, exp_i in zip(results, expected_order):
        assert r.score == pytest.approx(float(expected_scores[exp_i]), abs=1e-5)


def test_get_by_source_file(store):
    vecs = _random_vectors(5, seed=6)
    ids = [f"d{i}" for i in range(5)]
    metas = [{"wing": "alpha", "room": "r", "source_file": "/a.txt"} for _ in range(3)]
    metas += [{"wing": "alpha", "room": "r", "source_file": "/b.txt"} for _ in range(2)]
    texts = [f"t{i}" for i in range(5)]
    store.upsert(ids, vecs, metas, texts)

    rows = store.get({"source_file": "/a.txt"})
    assert len(rows) == 3
    assert {r["id"] for r in rows} == {"d0", "d1", "d2"}


def test_delete_by_source_file(store):
    vecs = _random_vectors(5, seed=7)
    ids = [f"d{i}" for i in range(5)]
    metas = [{"wing": "alpha", "room": "r", "source_file": "/a.txt"} for _ in range(3)]
    metas += [{"wing": "alpha", "room": "r", "source_file": "/b.txt"} for _ in range(2)]
    texts = [f"t{i}" for i in range(5)]
    store.upsert(ids, vecs, metas, texts)

    deleted = store.delete({"source_file": "/a.txt"})
    assert deleted == 3
    assert store.count() == 2

    # Deleted drawers must not appear in query results even though the
    # vectors are still physically present in the shard file.
    q = vecs[0]  # this belonged to /a.txt, which is now deleted
    results = store.query(q, k=5)
    assert all(r.id in {"d3", "d4"} for r in results)


def test_upsert_replaces_existing_id(store):
    """Re-upserting an id with new text must return the new text on query."""
    v = _random_vectors(1, seed=8)
    store.upsert(["x"], v, [{"wing": "alpha", "room": "r"}], ["original"])
    store.upsert(["x"], v, [{"wing": "alpha", "room": "r"}], ["updated"])

    results = store.query(v[0], k=1)
    assert len(results) == 1
    assert results[0].id == "x"
    assert results[0].text == "updated"
    assert store.count() == 1


def test_store_survives_reopen(tmp_path):
    """Close and reopen → all committed data must be recoverable."""
    path = tmp_path / "palace.store"
    vecs = _random_vectors(25, seed=9)
    ids = [f"d{i}" for i in range(25)]
    metas = [{"wing": "alpha" if i < 12 else "beta", "room": "r"} for i in range(25)]
    texts = [f"t{i}" for i in range(25)]

    s1 = PalaceStore(path)
    s1.upsert(ids, vecs, metas, texts)
    s1.close()

    s2 = PalaceStore(path)
    try:
        assert s2.count() == 25
        assert s2.count_by_wing() == {"alpha": 12, "beta": 13}

        # Query should still find the exact vector.
        results = s2.query(vecs[7], k=1)
        assert len(results) == 1
        assert results[0].id == "d7"
        assert results[0].score == pytest.approx(1.0, abs=1e-5)
    finally:
        s2.close()


# ── int8 variant smoke tests ──────────────────────────────────────────


def test_i8_upsert_and_query_returns_self(store_i8):
    """int8 quantization should keep the self-query as the top hit."""
    vecs = _random_vectors(50, seed=21)
    ids = [f"d{i}" for i in range(50)]
    metas = [{"wing": "alpha", "room": "r"} for _ in range(50)]
    texts = [f"t{i}" for i in range(50)]
    store_i8.upsert(ids, vecs, metas, texts)
    assert store_i8.count() == 50

    # Each stored vector should rank itself first. At per-vector scalar
    # quantization with random unit vectors, the self-score is ~1.0 but
    # rounded — tolerate a small drop from exact 1.0.
    for i in range(50):
        results = store_i8.query(vecs[i], k=1)
        assert len(results) == 1
        assert results[0].id == f"d{i}"
        assert results[0].score == pytest.approx(1.0, abs=5e-3)


def test_i8_ranking_matches_exact_at_top_k(store_i8):
    """Top-5 set match between int8 and exact cosine at modest scale.

    With per-vector int8 scalar quantization and random unit vectors,
    ranking ties are rare. Allow 1 divergence out of 5 as 'correct'.
    """
    vecs = _random_vectors(200, seed=22)
    ids = [f"d{i}" for i in range(200)]
    metas = [{"wing": "alpha", "room": "r"} for _ in range(200)]
    texts = [f"t{i}" for i in range(200)]
    store_i8.upsert(ids, vecs, metas, texts)

    q = _random_vectors(1, seed=98)[0]
    expected = np.argsort(-(vecs @ q))[:5]
    expected_ids = {f"d{i}" for i in expected}

    results = store_i8.query(q, k=5)
    got_ids = {r.id for r in results}
    assert len(got_ids & expected_ids) >= 4  # 4 of 5 match at quant precision


def test_i8_wing_filter_still_shard_scoped(store_i8):
    """wing filtering in the int8 path must not leak across shards."""
    vecs = _random_vectors(30, seed=23)
    ids = [f"d{i}" for i in range(30)]
    metas = [{"wing": "alpha" if i < 15 else "beta", "room": "r"} for i in range(30)]
    texts = [f"t{i}" for i in range(30)]
    store_i8.upsert(ids, vecs, metas, texts)

    results = store_i8.query(vecs[20], k=10, where={"wing": "alpha"})
    assert len(results) == 10
    assert all(r.wing == "alpha" for r in results)


def test_i8_reopen_recovers_state(tmp_path):
    path = tmp_path / "palace_i8.store"
    vecs = _random_vectors(20, seed=24)
    ids = [f"d{i}" for i in range(20)]
    metas = [{"wing": "alpha", "room": "r"} for _ in range(20)]
    texts = [f"t{i}" for i in range(20)]

    s1 = PalaceStore(path, dtype="int8")
    s1.upsert(ids, vecs, metas, texts)
    s1.close()

    s2 = PalaceStore(path, dtype="int8")
    try:
        assert s2.count() == 20
        # Self-query still returns self post-reopen
        results = s2.query(vecs[5], k=1)
        assert results[0].id == "d5"
    finally:
        s2.close()


def test_i8_disk_smaller_than_f32(tmp_path):
    """An int8 store holding N drawers should use ~4x less vector bytes."""
    vecs = _random_vectors(1000, seed=25)
    ids = [f"d{i}" for i in range(1000)]
    metas = [{"wing": "alpha", "room": "r"} for _ in range(1000)]
    texts = [f"t{i}" for i in range(1000)]

    f32_store = PalaceStore(tmp_path / "f32", dtype="float32")
    i8_store = PalaceStore(tmp_path / "i8", dtype="int8")
    try:
        f32_store.upsert(ids, vecs, metas, texts)
        i8_store.upsert(ids, vecs, metas, texts)
        f32_sizes = f32_store.disk_bytes()
        i8_sizes = i8_store.disk_bytes()
        # 1000 × (384 * 4) = 1,536,000 for f32 vectors
        # 1000 × (384 + 4) = 388,000 for int8 vectors (+scales)
        # Ratio: 1,536,000 / 388,000 ≈ 3.96
        assert f32_sizes["vectors"] == 1000 * 384 * 4
        assert i8_sizes["vectors"] == 1000 * (384 + 4)
        ratio = f32_sizes["vectors"] / i8_sizes["vectors"]
        assert 3.9 < ratio < 4.0
    finally:
        f32_store.close()
        i8_store.close()


# ── room id integer mapping ───────────────────────────────────────────


def test_room_ids_assigned_on_upsert(store):
    """Upserting new rooms must allocate stable int32 ids."""
    vecs = _random_vectors(4, seed=30)
    store.upsert(
        ["a", "b", "c", "d"],
        vecs,
        [
            {"wing": "alpha", "room": "r1"},
            {"wing": "alpha", "room": "r2"},
            {"wing": "alpha", "room": "r1"},
            {"wing": "alpha", "room": "r3"},
        ],
        ["t"] * 4,
    )
    # Three distinct room names → three distinct ids, stable and ≥ 1
    ids = {store._room_name_to_id[r] for r in ("r1", "r2", "r3")}
    assert len(ids) == 3
    assert all(i >= 1 for i in ids)
    # Shard array is int32 and matches the expected ids
    shard_ids = store._shard_room_ids["alpha"]
    assert shard_ids.dtype == np.int32
    assert shard_ids[0] == shard_ids[2]  # both r1
    assert shard_ids[0] != shard_ids[1]  # r1 != r2
    assert shard_ids[1] != shard_ids[3]  # r2 != r3


def test_room_ids_stable_across_reopen(tmp_path):
    """A reopened store must see the same int id for the same room name."""
    path = tmp_path / "palace.store"
    v = _random_vectors(2, seed=31)
    s1 = PalaceStore(path)
    s1.upsert(
        ["a", "b"],
        v,
        [
            {"wing": "alpha", "room": "first"},
            {"wing": "alpha", "room": "second"},
        ],
        ["t1", "t2"],
    )
    id_first = s1._room_name_to_id["first"]
    id_second = s1._room_name_to_id["second"]
    s1.close()

    s2 = PalaceStore(path)
    try:
        assert s2._room_name_to_id["first"] == id_first
        assert s2._room_name_to_id["second"] == id_second
        # Querying by name still works — the translation layer round-trips
        results = s2.query(v[0], k=1, where={"room": "first"})
        assert len(results) == 1
        assert results[0].id == "a"
        assert results[0].room == "first"
    finally:
        s2.close()


def test_room_filter_unknown_room_returns_empty(store):
    """Querying a room that was never ingested returns [], not an error."""
    vecs = _random_vectors(5, seed=32)
    store.upsert(
        [f"d{i}" for i in range(5)],
        vecs,
        [{"wing": "alpha", "room": "exists"} for _ in range(5)],
        ["t"] * 5,
    )
    results = store.query(vecs[0], k=5, where={"room": "does_not_exist"})
    assert results == []


def test_room_id_backfill_on_legacy_store(tmp_path):
    """A store opened with drawer rooms but no room_ids rows must backfill.

    This simulates migrating from a pre-int-id palace.store format:
    drawer rows exist but the room_ids table is empty. _load_room_id_map
    should allocate ids for every distinct room it finds.
    """
    path = tmp_path / "palace.store"
    v = _random_vectors(3, seed=33)

    s1 = PalaceStore(path)
    s1.upsert(
        ["a", "b", "c"],
        v,
        [
            {"wing": "alpha", "room": "auth"},
            {"wing": "alpha", "room": "db"},
            {"wing": "alpha", "room": "auth"},
        ],
        ["t1", "t2", "t3"],
    )
    s1.close()

    # Simulate legacy state: wipe the room_ids table on disk but keep drawers
    import sqlite3

    conn = sqlite3.connect(path / "meta.sqlite")
    conn.execute("DELETE FROM room_ids")
    conn.commit()
    conn.close()

    # Reopen → _load_room_id_map should backfill ids for "auth" and "db"
    s2 = PalaceStore(path)
    try:
        assert "auth" in s2._room_name_to_id
        assert "db" in s2._room_name_to_id
        # Room-filtered query must still find the right drawers
        results = s2.query(v[0], k=5, where={"room": "auth"})
        assert {r.id for r in results} == {"a", "c"}
    finally:
        s2.close()


# ── parallel query ────────────────────────────────────────────────────


def test_parallel_query_matches_sequential(tmp_path):
    """Opt-in parallel dispatch must return identical rankings to sequential."""
    # Need at least 4 wings to actually exercise the parallel path
    # (otherwise it falls through to the sequential branch).
    path_seq = tmp_path / "seq"
    path_par = tmp_path / "par"
    vecs = _random_vectors(200, seed=34)
    ids = [f"d{i}" for i in range(200)]
    metas = [{"wing": f"wing_{i % 5}", "room": f"room_{i % 7}"} for i in range(200)]
    texts = [f"t{i}" for i in range(200)]

    seq = PalaceStore(path_seq)
    par = PalaceStore(path_par, parallel_query=True, max_workers=4)
    try:
        seq.upsert(ids, vecs, metas, texts)
        par.upsert(ids, vecs, metas, texts)

        rng = np.random.default_rng(77)
        queries = l2_normalize(rng.standard_normal((20, VECTOR_DIM), dtype=np.float32))

        # Unfiltered: fans across all 5 wings → parallel path active
        for i, q in enumerate(queries):
            s_hits = seq.query(q, k=10)
            p_hits = par.query(q, k=10)
            assert [h.id for h in s_hits] == [
                h.id for h in p_hits
            ], f"unfiltered mismatch on query {i}"

        # Wing-filtered: single shard → still goes through _score_shard
        for i, q in enumerate(queries):
            s_hits = seq.query(q, k=10, where={"wing": "wing_2"})
            p_hits = par.query(q, k=10, where={"wing": "wing_2"})
            assert [h.id for h in s_hits] == [
                h.id for h in p_hits
            ], f"wing-filter mismatch on query {i}"

        # Wing + room: int-id comparison path
        for i, q in enumerate(queries):
            s_hits = seq.query(q, k=5, where={"wing": "wing_2", "room": "room_3"})
            p_hits = par.query(q, k=5, where={"wing": "wing_2", "room": "room_3"})
            assert [h.id for h in s_hits] == [
                h.id for h in p_hits
            ], f"wing+room mismatch on query {i}"
    finally:
        seq.close()
        par.close()


def test_parallel_query_executor_lazy(tmp_path):
    """Executor must not be created until a parallel-eligible query fires."""
    v = _random_vectors(2, seed=35)
    store = PalaceStore(tmp_path / "palace.store", parallel_query=True, max_workers=2)
    try:
        # No shards → no executor created yet
        assert store._executor is None
        store.upsert(
            ["a", "b"],
            v,
            [{"wing": "w1", "room": "r"}, {"wing": "w2", "room": "r"}],
            ["t", "t"],
        )
        # 2 wings < _PARALLEL_MIN_SHARDS → still no executor
        store.query(v[0], k=1)
        assert store._executor is None

        # Add more wings to cross the threshold
        v2 = _random_vectors(4, seed=36)
        store.upsert(
            ["c", "d", "e", "f"],
            v2,
            [{"wing": f"w{i}", "room": "r"} for i in range(3, 7)],
            ["t"] * 4,
        )
        # 6 wings >= 4 → executor should spin up on first unfiltered query
        store.query(v[0], k=1)
        assert store._executor is not None
    finally:
        store.close()
        # close() must tear the executor down cleanly
        assert store._executor is None


def test_disk_bytes_breakdown(store):
    vecs = _random_vectors(100, seed=10)
    ids = [f"d{i}" for i in range(100)]
    metas = [{"wing": "alpha" if i < 50 else "beta", "room": "r"} for i in range(100)]
    texts = ["t" for _ in range(100)]
    store.upsert(ids, vecs, metas, texts)

    sizes = store.disk_bytes()
    # 100 vectors × 1536 bytes = 153600, split across two shard files.
    assert sizes["vectors"] == 100 * 384 * 4
    assert sizes["meta"] > 0
    assert sizes["total"] == sizes["vectors"] + sizes["meta"]
