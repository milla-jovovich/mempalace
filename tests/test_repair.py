"""Tests for mempalace.repair — scan, prune, and rebuild HNSW index."""

import json
import os
import pickle
import sqlite3
import struct
from unittest.mock import MagicMock, patch

import pytest

from mempalace import repair


# ── helpers: synthesize a legacy-format HNSW segment on disk ──────────

_DIM = 8
_SIZE_PER_ELEMENT = 132 + _DIM * 4 + 8
_LABEL_OFFSET = 132 + _DIM * 4
_OFFSET_DATA = 132


def _pack_header(max_elements: int, cur_count: int) -> bytes:
    hdr = bytearray(100)
    struct.pack_into("<I", hdr, 0, 1)  # format_version
    struct.pack_into("<Q", hdr, 4, 0)  # offset_level0
    struct.pack_into("<Q", hdr, 12, max_elements)
    struct.pack_into("<Q", hdr, 20, cur_count)
    struct.pack_into("<Q", hdr, 28, _SIZE_PER_ELEMENT)
    struct.pack_into("<Q", hdr, 36, _LABEL_OFFSET)
    struct.pack_into("<Q", hdr, 44, _OFFSET_DATA)
    struct.pack_into("<i", hdr, 52, 0)
    struct.pack_into("<I", hdr, 56, 0)
    struct.pack_into("<Q", hdr, 60, 16)  # maxM
    struct.pack_into("<Q", hdr, 68, 32)  # maxM0
    struct.pack_into("<Q", hdr, 76, 16)  # M
    struct.pack_into("<d", hdr, 84, 1 / 0.693)
    struct.pack_into("<Q", hdr, 92, 100)  # ef_construction
    return bytes(hdr)


class _PickleMeta:
    """Minimal shim for ChromaDB's PersistentLocalHnswSegment pickle."""


def _seed_hnsw_segment(
    palace_path: str,
    *,
    segment: str = "00000000-0000-0000-0000-000000000042",
    labels=(101, 202, 303, 404),
    extra_pickle_ids=("uid-stale",),
    space: str = "cosine",
    bloated_link_lists: int = 1024,
):
    """Write a synthetic HNSW segment + sqlite into ``palace_path``.

    Returns ``(segment_uuid, collection_uuid, healthy_uids, vectors)``.
    """
    import numpy as np

    os.makedirs(palace_path, exist_ok=True)
    seg_dir = os.path.join(palace_path, segment)
    os.makedirs(seg_dir)

    coll_uuid = "aaaa1111-2222-3333-4444-555566667777"
    db_path = os.path.join(palace_path, "chroma.sqlite3")
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE segments(id TEXT PRIMARY KEY, type TEXT, scope TEXT, collection TEXT);
        CREATE TABLE collection_metadata(collection_id TEXT, key TEXT, str_value TEXT);
        CREATE TABLE embeddings_queue(seq_id INTEGER PRIMARY KEY, topic TEXT, id TEXT);
        """
    )
    conn.execute(
        "INSERT INTO segments VALUES (?, 'urn:chroma:segment/vector/hnsw-local-persisted', 'VECTOR', ?)",
        (segment, coll_uuid),
    )
    if space is not None:
        conn.execute(
            "INSERT INTO collection_metadata VALUES (?, 'hnsw:space', ?)", (coll_uuid, space)
        )
    topic = f"persistent://default/default/{coll_uuid}"
    for i, uid in enumerate([f"uid{i}" for i in range(3)], start=1):
        conn.execute("INSERT INTO embeddings_queue VALUES (?, ?, ?)", (i, topic, uid))
    conn.commit()
    conn.close()

    cur_count = len(labels)
    max_elements = max(cur_count * 2, 10)
    header = _pack_header(max_elements=max_elements, cur_count=cur_count)
    with open(os.path.join(seg_dir, "header.bin"), "wb") as f:
        f.write(header)

    np.random.seed(1)
    vectors = np.random.rand(cur_count, _DIM).astype(np.float32)
    data = bytearray(max_elements * _SIZE_PER_ELEMENT)
    data[:100] = header
    for i, lbl in enumerate(labels):
        slot = i * _SIZE_PER_ELEMENT
        data[slot + _OFFSET_DATA : slot + _OFFSET_DATA + _DIM * 4] = vectors[i].tobytes()
        struct.pack_into("<Q", data, slot + _LABEL_OFFSET, int(lbl))
    with open(os.path.join(seg_dir, "data_level0.bin"), "wb") as f:
        f.write(bytes(data))

    # Build pickle: one mapped UUID per real label + any stale ones.
    meta = _PickleMeta()
    healthy_uids = [f"uid-{int(lbl)}" for lbl in labels]
    meta.label_to_id = dict(zip([int(lbl) for lbl in labels], healthy_uids))
    for idx, extra in enumerate(extra_pickle_ids, start=1000):
        meta.label_to_id[idx] = extra
    meta.id_to_label = {uid: lbl for lbl, uid in meta.label_to_id.items()}
    meta.id_to_seq_id = {uid: i for i, uid in enumerate(meta.label_to_id.values(), start=1)}
    meta.total_elements_added = len(meta.label_to_id)
    meta.dimensionality = _DIM
    with open(os.path.join(seg_dir, "index_metadata.pickle"), "wb") as f:
        pickle.dump(meta, f)

    # Simulate the bloat we're trying to clean.
    with open(os.path.join(seg_dir, "link_lists.bin"), "wb") as f:
        f.write(b"\x00" * bloated_link_lists)

    return segment, coll_uuid, healthy_uids, vectors


@pytest.fixture
def synthetic_segment(tmp_path):
    """Build a throwaway palace with one synthetic legacy-format HNSW segment."""
    pytest.importorskip("numpy")
    pytest.importorskip("hnswlib")
    palace = tmp_path / "palace"
    segment, coll, uids, vectors = _seed_hnsw_segment(str(palace))
    return {
        "palace": str(palace),
        "segment": segment,
        "collection": coll,
        "uids": uids,
        "vectors": vectors,
    }


# ── _get_palace_path ──────────────────────────────────────────────────


@patch("mempalace.repair.MempalaceConfig", create=True)
def test_get_palace_path_from_config(mock_config_cls):
    mock_config_cls.return_value.palace_path = "/configured/palace"
    with patch.dict("sys.modules", {}):
        # Force reimport to pick up the mock
        result = repair._get_palace_path()
    assert isinstance(result, str)


def test_get_palace_path_fallback():
    with patch("mempalace.repair._get_palace_path") as mock_get:
        mock_get.return_value = os.path.join(os.path.expanduser("~"), ".mempalace", "palace")
        result = mock_get()
        assert ".mempalace" in result


# ── _paginate_ids ─────────────────────────────────────────────────────


def test_paginate_ids_single_batch():
    col = MagicMock()
    col.get.return_value = {"ids": ["id1", "id2", "id3"]}
    ids = repair._paginate_ids(col)
    assert ids == ["id1", "id2", "id3"]


def test_paginate_ids_empty():
    col = MagicMock()
    col.get.return_value = {"ids": []}
    ids = repair._paginate_ids(col)
    assert ids == []


def test_paginate_ids_with_where():
    col = MagicMock()
    col.get.return_value = {"ids": ["id1"]}
    repair._paginate_ids(col, where={"wing": "test"})
    col.get.assert_called_with(where={"wing": "test"}, include=[], limit=1000, offset=0)


def test_paginate_ids_offset_exception_fallback():
    col = MagicMock()
    # First call raises, fallback returns ids, second fallback returns empty
    col.get.side_effect = [
        Exception("offset bug"),
        {"ids": ["id1", "id2"]},
        Exception("offset bug"),
        {"ids": ["id1", "id2"]},  # same ids = no new = break
    ]
    ids = repair._paginate_ids(col)
    assert "id1" in ids


# ── scan_palace ───────────────────────────────────────────────────────


def _install_mock_backend(mock_backend_cls, collection):
    """Wire mock_backend_cls so ChromaBackend().get_collection(...) returns *collection*."""
    mock_backend = MagicMock()
    mock_backend.get_collection.return_value = collection
    mock_backend_cls.return_value = mock_backend
    return mock_backend


@patch("mempalace.repair.ChromaBackend")
def test_scan_palace_no_ids(mock_backend_cls, tmp_path):
    mock_col = MagicMock()
    mock_col.count.return_value = 0
    mock_col.get.return_value = {"ids": []}
    _install_mock_backend(mock_backend_cls, mock_col)

    good, bad = repair.scan_palace(palace_path=str(tmp_path))
    assert good == set()
    assert bad == set()


@patch("mempalace.repair.ChromaBackend")
def test_scan_palace_all_good(mock_backend_cls, tmp_path):
    mock_col = MagicMock()
    mock_col.count.return_value = 2
    # _paginate_ids call
    mock_col.get.side_effect = [
        {"ids": ["id1", "id2"]},  # paginate
        {"ids": ["id1", "id2"]},  # probe batch — both returned
    ]
    _install_mock_backend(mock_backend_cls, mock_col)

    good, bad = repair.scan_palace(palace_path=str(tmp_path))
    assert "id1" in good
    assert "id2" in good
    assert len(bad) == 0


@patch("mempalace.repair.ChromaBackend")
def test_scan_palace_with_bad_ids(mock_backend_cls, tmp_path):
    mock_col = MagicMock()
    mock_col.count.return_value = 2

    def get_side_effect(**kwargs):
        ids = kwargs.get("ids", None)
        if ids is None:
            # paginate call
            return {"ids": ["good1", "bad1"]}
        if "bad1" in ids and len(ids) == 1:
            raise Exception("corrupt")
        if "good1" in ids and len(ids) == 1:
            return {"ids": ["good1"]}
        # batch probe — raise to force per-id
        raise Exception("batch fail")

    mock_col.get.side_effect = get_side_effect
    _install_mock_backend(mock_backend_cls, mock_col)

    good, bad = repair.scan_palace(palace_path=str(tmp_path))
    assert "good1" in good
    assert "bad1" in bad


@patch("mempalace.repair.ChromaBackend")
def test_scan_palace_with_wing_filter(mock_backend_cls, tmp_path):
    mock_col = MagicMock()
    mock_col.count.return_value = 1
    mock_col.get.side_effect = [
        {"ids": ["id1"]},  # paginate
        {"ids": ["id1"]},  # probe
    ]
    _install_mock_backend(mock_backend_cls, mock_col)

    repair.scan_palace(palace_path=str(tmp_path), only_wing="test_wing")
    # Verify where filter was passed
    first_call = mock_col.get.call_args_list[0]
    assert first_call.kwargs.get("where") == {"wing": "test_wing"}


# ── prune_corrupt ─────────────────────────────────────────────────────


@patch("mempalace.repair.ChromaBackend")
def test_prune_corrupt_no_file(mock_backend_cls, tmp_path):
    # Should print message and return without error
    repair.prune_corrupt(palace_path=str(tmp_path))


@patch("mempalace.repair.ChromaBackend")
def test_prune_corrupt_dry_run(mock_backend_cls, tmp_path):
    bad_file = tmp_path / "corrupt_ids.txt"
    bad_file.write_text("bad1\nbad2\n")
    repair.prune_corrupt(palace_path=str(tmp_path), confirm=False)
    # No backend calls in dry run
    mock_backend_cls.assert_not_called()


@patch("mempalace.repair.ChromaBackend")
def test_prune_corrupt_confirmed(mock_backend_cls, tmp_path):
    bad_file = tmp_path / "corrupt_ids.txt"
    bad_file.write_text("bad1\nbad2\n")

    mock_col = MagicMock()
    mock_col.count.side_effect = [10, 8]
    _install_mock_backend(mock_backend_cls, mock_col)

    repair.prune_corrupt(palace_path=str(tmp_path), confirm=True)
    mock_col.delete.assert_called_once()


@patch("mempalace.repair.ChromaBackend")
def test_prune_corrupt_delete_failure_fallback(mock_backend_cls, tmp_path):
    bad_file = tmp_path / "corrupt_ids.txt"
    bad_file.write_text("bad1\nbad2\n")

    mock_col = MagicMock()
    mock_col.count.side_effect = [10, 8]
    # Batch delete fails, per-id succeeds
    mock_col.delete.side_effect = [Exception("batch fail"), None, None]
    _install_mock_backend(mock_backend_cls, mock_col)

    repair.prune_corrupt(palace_path=str(tmp_path), confirm=True)
    assert mock_col.delete.call_count == 3  # 1 batch + 2 individual


# ── rebuild_index ─────────────────────────────────────────────────────


@patch("mempalace.repair.ChromaBackend")
def test_rebuild_index_no_palace(mock_backend_cls, tmp_path):
    nonexistent = str(tmp_path / "nope")
    repair.rebuild_index(palace_path=nonexistent)
    mock_backend_cls.assert_not_called()


@patch("mempalace.repair.shutil")
@patch("mempalace.repair.ChromaBackend")
def test_rebuild_index_empty_palace(mock_backend_cls, mock_shutil, tmp_path):
    mock_col = MagicMock()
    mock_col.count.return_value = 0
    mock_backend = _install_mock_backend(mock_backend_cls, mock_col)

    repair.rebuild_index(palace_path=str(tmp_path))
    mock_backend.delete_collection.assert_not_called()


@patch("mempalace.repair.shutil")
@patch("mempalace.repair.ChromaBackend")
def test_rebuild_index_success(mock_backend_cls, mock_shutil, tmp_path):
    # Create a fake sqlite file
    sqlite_path = tmp_path / "chroma.sqlite3"
    sqlite_path.write_text("fake")

    mock_col = MagicMock()
    mock_col.count.return_value = 2
    mock_col.get.return_value = {
        "ids": ["id1", "id2"],
        "documents": ["doc1", "doc2"],
        "metadatas": [{"wing": "a"}, {"wing": "b"}],
    }

    mock_new_col = MagicMock()
    mock_backend = _install_mock_backend(mock_backend_cls, mock_col)
    mock_backend.create_collection.return_value = mock_new_col

    repair.rebuild_index(palace_path=str(tmp_path))

    # Verify: backed up sqlite only (not copytree)
    mock_shutil.copy2.assert_called_once()
    assert "chroma.sqlite3" in str(mock_shutil.copy2.call_args)

    # Verify: deleted and recreated (cosine is the backend default)
    mock_backend.delete_collection.assert_called_once_with(str(tmp_path), "mempalace_drawers")
    mock_backend.create_collection.assert_called_once_with(str(tmp_path), "mempalace_drawers")

    # Verify: used upsert not add
    mock_new_col.upsert.assert_called_once()
    mock_new_col.add.assert_not_called()


@patch("mempalace.repair.shutil")
@patch("mempalace.repair.ChromaBackend")
def test_rebuild_index_error_reading(mock_backend_cls, mock_shutil, tmp_path):
    mock_backend = MagicMock()
    mock_backend.get_collection.side_effect = Exception("corrupt")
    mock_backend_cls.return_value = mock_backend

    repair.rebuild_index(palace_path=str(tmp_path))
    mock_backend.delete_collection.assert_not_called()


# ── #1208 truncation safety ───────────────────────────────────────────


def test_check_extraction_safety_passes_when_counts_match(tmp_path):
    """SQLite reports same count as extracted → no exception."""
    with patch("mempalace.repair.sqlite_drawer_count", return_value=500):
        repair.check_extraction_safety(str(tmp_path), 500)


def test_check_extraction_safety_passes_when_sqlite_unreadable_and_under_cap(tmp_path):
    """SQLite check fails (None) but extraction is well under the cap → safe."""
    with patch("mempalace.repair.sqlite_drawer_count", return_value=None):
        repair.check_extraction_safety(str(tmp_path), 5_000)


def test_check_extraction_safety_aborts_when_sqlite_higher(tmp_path):
    """SQLite reports more than extracted — the user-reported #1208 case."""
    with patch("mempalace.repair.sqlite_drawer_count", return_value=67_580):
        try:
            repair.check_extraction_safety(str(tmp_path), 10_000)
        except repair.TruncationDetected as e:
            assert e.sqlite_count == 67_580
            assert e.extracted == 10_000
            assert "67,580" in e.message
            assert "10,000" in e.message
            assert "57,580" in e.message  # the loss number
        else:
            raise AssertionError("expected TruncationDetected")


def test_check_extraction_safety_aborts_when_unreadable_and_at_cap(tmp_path):
    """SQLite unreadable but extraction == default get() cap → suspicious."""
    with patch("mempalace.repair.sqlite_drawer_count", return_value=None):
        try:
            repair.check_extraction_safety(str(tmp_path), repair.CHROMADB_DEFAULT_GET_LIMIT)
        except repair.TruncationDetected as e:
            assert e.sqlite_count is None
            assert e.extracted == repair.CHROMADB_DEFAULT_GET_LIMIT
            assert "10,000" in e.message
        else:
            raise AssertionError("expected TruncationDetected")


def test_check_extraction_safety_override_skips_check(tmp_path):
    """``confirm_truncation_ok=True`` short-circuits both signals."""
    with patch("mempalace.repair.sqlite_drawer_count", return_value=99_999):
        # Would normally abort — override allows through
        repair.check_extraction_safety(str(tmp_path), 10_000, confirm_truncation_ok=True)


def test_sqlite_drawer_count_returns_none_on_missing_file(tmp_path):
    """Palace dir exists but no chroma.sqlite3 → None, not crash."""
    assert repair.sqlite_drawer_count(str(tmp_path)) is None


def test_sqlite_drawer_count_returns_none_on_unreadable_schema(tmp_path):
    """File exists but isn't a chromadb sqlite → None, not crash."""
    sqlite_path = os.path.join(str(tmp_path), "chroma.sqlite3")
    with open(sqlite_path, "wb") as f:
        f.write(b"not a sqlite file at all")
    assert repair.sqlite_drawer_count(str(tmp_path)) is None


@patch("mempalace.repair.shutil")
@patch("mempalace.repair.ChromaBackend")
def test_rebuild_index_aborts_on_truncation_signal(mock_backend_cls, mock_shutil, tmp_path):
    """rebuild_index honors the safety guard: SQLite says 67k, get() returns
    10k → no delete_collection, no upsert, no backup."""
    mock_backend = MagicMock()
    mock_col = MagicMock()
    mock_col.count.return_value = 10_000
    # Single page comes back with 10_000 ids
    mock_col.get.side_effect = [
        {
            "ids": [f"id{i}" for i in range(10_000)],
            "documents": ["x"] * 10_000,
            "metadatas": [{}] * 10_000,
        },
        {"ids": [], "documents": [], "metadatas": []},
    ]
    mock_backend.get_collection.return_value = mock_col
    mock_backend_cls.return_value = mock_backend

    with patch("mempalace.repair.sqlite_drawer_count", return_value=67_580):
        repair.rebuild_index(palace_path=str(tmp_path))

    # Guard fired: nothing destructive happened
    mock_backend.delete_collection.assert_not_called()
    mock_backend.create_collection.assert_not_called()
    mock_shutil.copy2.assert_not_called()


@patch("mempalace.repair.shutil")
@patch("mempalace.repair.ChromaBackend")
def test_rebuild_index_proceeds_with_override(mock_backend_cls, mock_shutil, tmp_path):
    """Override flag lets repair proceed even when the guard would fire."""
    mock_backend = MagicMock()
    mock_col = MagicMock()
    mock_col.count.return_value = 10_000
    mock_col.get.side_effect = [
        {
            "ids": [f"id{i}" for i in range(10_000)],
            "documents": ["x"] * 10_000,
            "metadatas": [{}] * 10_000,
        },
        {"ids": [], "documents": [], "metadatas": []},
    ]
    mock_new_col = MagicMock()
    mock_backend.get_collection.return_value = mock_col
    mock_backend.create_collection.return_value = mock_new_col
    mock_backend_cls.return_value = mock_backend

    with patch("mempalace.repair.sqlite_drawer_count", return_value=67_580):
        repair.rebuild_index(palace_path=str(tmp_path), confirm_truncation_ok=True)

    mock_backend.delete_collection.assert_called_once()
    mock_backend.create_collection.assert_called_once()
    mock_new_col.upsert.assert_called()


# ── repair_max_seq_id ─────────────────────────────────────────────────


# Realistic poisoned values from the 2026-04-20 incident — from the sysdb-10
# b'\x11\x11' + 6 ASCII digit format being misread as big-endian u64.
_POISON_VAL = 1_229_822_654_365_970_487


def _seed_poisoned_max_seq_id(
    palace_path: str,
    *,
    drawers_meta_max: int = 502607,
    closets_meta_max: int = 501418,
    drawers_vec_poison: int = _POISON_VAL,
    drawers_meta_poison: int = _POISON_VAL + 1,
    closets_vec_poison: int = _POISON_VAL + 2,
    closets_meta_poison: int = _POISON_VAL + 3,
):
    """Build a minimal palace with poisoned max_seq_id rows.

    Returns a dict with segment UUIDs and the expected clean values.
    """
    os.makedirs(palace_path, exist_ok=True)
    db_path = os.path.join(palace_path, "chroma.sqlite3")

    drawers_coll = "coll-drawers-0000-1111-2222-333344445555"
    closets_coll = "coll-closets-0000-1111-2222-333344445555"
    drawers_vec = "seg-drawers-vec-0000-1111-2222-333344445555"
    drawers_meta = "seg-drawers-meta-0000-1111-2222-33334444555"
    closets_vec = "seg-closets-vec-0000-1111-2222-333344445555"
    closets_meta = "seg-closets-meta-0000-1111-2222-33334444555"

    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE segments(
            id TEXT PRIMARY KEY, type TEXT, scope TEXT, collection TEXT
        );
        CREATE TABLE max_seq_id(segment_id TEXT PRIMARY KEY, seq_id);
        CREATE TABLE embeddings(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            segment_id TEXT,
            embedding_id TEXT,
            seq_id
        );
        CREATE TABLE embeddings_queue(seq_id INTEGER PRIMARY KEY, topic TEXT, id TEXT);
        CREATE TABLE collection_metadata(collection_id TEXT, key TEXT, str_value TEXT);
        """
    )
    conn.executemany(
        "INSERT INTO segments VALUES (?, ?, ?, ?)",
        [
            (drawers_vec, "urn:vector", "VECTOR", drawers_coll),
            (drawers_meta, "urn:metadata", "METADATA", drawers_coll),
            (closets_vec, "urn:vector", "VECTOR", closets_coll),
            (closets_meta, "urn:metadata", "METADATA", closets_coll),
        ],
    )
    conn.executemany(
        "INSERT INTO max_seq_id(segment_id, seq_id) VALUES (?, ?)",
        [
            (drawers_vec, drawers_vec_poison),
            (drawers_meta, drawers_meta_poison),
            (closets_vec, closets_vec_poison),
            (closets_meta, closets_meta_poison),
        ],
    )
    # Populate embeddings so the collection-MAX heuristic has data to work with.
    # drawers METADATA owns the max at drawers_meta_max; closets likewise.
    for i in range(1, drawers_meta_max + 1, max(drawers_meta_max // 5, 1)):
        conn.execute(
            "INSERT INTO embeddings(segment_id, embedding_id, seq_id) VALUES (?, ?, ?)",
            (drawers_meta, f"d-{i}", i),
        )
    conn.execute(
        "INSERT INTO embeddings(segment_id, embedding_id, seq_id) VALUES (?, ?, ?)",
        (drawers_meta, "d-max", drawers_meta_max),
    )
    for i in range(1, closets_meta_max + 1, max(closets_meta_max // 5, 1)):
        conn.execute(
            "INSERT INTO embeddings(segment_id, embedding_id, seq_id) VALUES (?, ?, ?)",
            (closets_meta, f"c-{i}", i),
        )
    conn.execute(
        "INSERT INTO embeddings(segment_id, embedding_id, seq_id) VALUES (?, ?, ?)",
        (closets_meta, "c-max", closets_meta_max),
    )
    conn.commit()
    conn.close()
    return {
        "drawers_vec": drawers_vec,
        "drawers_meta": drawers_meta,
        "closets_vec": closets_vec,
        "closets_meta": closets_meta,
        "drawers_meta_max": drawers_meta_max,
        "closets_meta_max": closets_meta_max,
        "poisoned_values": {
            drawers_vec: drawers_vec_poison,
            drawers_meta: drawers_meta_poison,
            closets_vec: closets_vec_poison,
            closets_meta: closets_meta_poison,
        },
    }


def test_max_seq_id_detects_poison_rows(tmp_path):
    palace = str(tmp_path / "palace")
    seg = _seed_poisoned_max_seq_id(palace)
    db_path = os.path.join(palace, "chroma.sqlite3")

    # Add one clean row to confirm the threshold actually filters.
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO segments VALUES ('seg-clean', 'urn:vector', 'VECTOR', 'coll-clean')"
        )
        conn.execute("INSERT INTO max_seq_id VALUES ('seg-clean', 1234)")
        conn.commit()

    found = repair._detect_poisoned_max_seq_ids(db_path)
    ids = {sid for sid, _ in found}
    assert ids == {
        seg["drawers_vec"],
        seg["drawers_meta"],
        seg["closets_vec"],
        seg["closets_meta"],
    }
    for sid, val in found:
        assert val > repair.MAX_SEQ_ID_SANITY_THRESHOLD
    assert "seg-clean" not in ids


def test_max_seq_id_heuristic_uses_collection_max(tmp_path):
    palace = str(tmp_path / "palace")
    seg = _seed_poisoned_max_seq_id(palace)

    result = repair.repair_max_seq_id(palace, dry_run=True)
    # Both drawers segments (VECTOR + METADATA) get the drawers collection max.
    assert result["after"][seg["drawers_vec"]] == seg["drawers_meta_max"]
    assert result["after"][seg["drawers_meta"]] == seg["drawers_meta_max"]
    # Both closets segments get the closets collection max.
    assert result["after"][seg["closets_vec"]] == seg["closets_meta_max"]
    assert result["after"][seg["closets_meta"]] == seg["closets_meta_max"]


def test_max_seq_id_from_sidecar_exact_restore(tmp_path):
    palace = str(tmp_path / "palace")
    seg = _seed_poisoned_max_seq_id(palace)

    # Craft a sidecar with known clean values that differ from the heuristic's
    # collection-max, so we can prove the sidecar path is preferred.
    sidecar_path = str(tmp_path / "chroma.sqlite3.sidecar")
    clean = {
        seg["drawers_vec"]: 499001,
        seg["drawers_meta"]: 499002,
        seg["closets_vec"]: 498001,
        seg["closets_meta"]: 498002,
    }
    with sqlite3.connect(sidecar_path) as conn:
        conn.execute("CREATE TABLE max_seq_id(segment_id TEXT PRIMARY KEY, seq_id INTEGER)")
        conn.executemany(
            "INSERT INTO max_seq_id VALUES (?, ?)",
            list(clean.items()),
        )
        conn.commit()

    result = repair.repair_max_seq_id(palace, from_sidecar=sidecar_path, assume_yes=True)
    assert result["segment_repaired"]
    db_path = os.path.join(palace, "chroma.sqlite3")
    with sqlite3.connect(db_path) as conn:
        rows = dict(conn.execute("SELECT segment_id, seq_id FROM max_seq_id").fetchall())
    for sid, val in clean.items():
        assert rows[sid] == val


def test_max_seq_id_dry_run_no_mutation(tmp_path):
    palace = str(tmp_path / "palace")
    seg = _seed_poisoned_max_seq_id(palace)
    db_path = os.path.join(palace, "chroma.sqlite3")

    with sqlite3.connect(db_path) as conn:
        before = dict(conn.execute("SELECT segment_id, seq_id FROM max_seq_id").fetchall())

    result = repair.repair_max_seq_id(palace, dry_run=True)
    assert result["dry_run"] is True
    assert result["segment_repaired"] == []

    with sqlite3.connect(db_path) as conn:
        after = dict(conn.execute("SELECT segment_id, seq_id FROM max_seq_id").fetchall())
    assert before == after
    # Nothing dropped into the palace dir either (no backup on dry-run).
    assert not any(fn.startswith("chroma.sqlite3.max-seq-id-backup-") for fn in os.listdir(palace))
    assert seg["drawers_vec"] in before  # sanity


def test_max_seq_id_segment_filter(tmp_path):
    palace = str(tmp_path / "palace")
    seg = _seed_poisoned_max_seq_id(palace)

    result = repair.repair_max_seq_id(palace, segment=seg["drawers_meta"], assume_yes=True)
    assert result["segment_repaired"] == [seg["drawers_meta"]]

    db_path = os.path.join(palace, "chroma.sqlite3")
    with sqlite3.connect(db_path) as conn:
        rows = dict(conn.execute("SELECT segment_id, seq_id FROM max_seq_id").fetchall())
    # Filtered segment is fixed; the other three remain poisoned.
    assert rows[seg["drawers_meta"]] == seg["drawers_meta_max"]
    for other in (seg["drawers_vec"], seg["closets_vec"], seg["closets_meta"]):
        assert rows[other] > repair.MAX_SEQ_ID_SANITY_THRESHOLD


def test_max_seq_id_no_poison_is_noop(tmp_path):
    palace = str(tmp_path / "palace")
    os.makedirs(palace)
    db_path = os.path.join(palace, "chroma.sqlite3")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE segments(
                id TEXT PRIMARY KEY, type TEXT, scope TEXT, collection TEXT
            );
            CREATE TABLE max_seq_id(segment_id TEXT PRIMARY KEY, seq_id);
            CREATE TABLE embeddings(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                segment_id TEXT, embedding_id TEXT, seq_id
            );
            INSERT INTO segments VALUES ('s1', 'urn:vector', 'VECTOR', 'coll');
            INSERT INTO max_seq_id VALUES ('s1', 12345);
            """
        )
        conn.commit()

    result = repair.repair_max_seq_id(palace, assume_yes=True)
    assert result["segment_repaired"] == []
    assert result["backup"] is None
    with sqlite3.connect(db_path) as conn:
        rows = dict(conn.execute("SELECT segment_id, seq_id FROM max_seq_id").fetchall())
    assert rows == {"s1": 12345}


def test_max_seq_id_backup_created(tmp_path):
    palace = str(tmp_path / "palace")
    seg = _seed_poisoned_max_seq_id(palace)

    result = repair.repair_max_seq_id(palace, assume_yes=True)
    assert result["backup"] is not None
    assert os.path.isfile(result["backup"])

    with sqlite3.connect(result["backup"]) as conn:
        rows = dict(conn.execute("SELECT segment_id, seq_id FROM max_seq_id").fetchall())
    # Backup preserves the poisoned values from before the repair.
    assert rows[seg["drawers_vec"]] == seg["poisoned_values"][seg["drawers_vec"]]
    assert rows[seg["drawers_meta"]] == seg["poisoned_values"][seg["drawers_meta"]]


def test_max_seq_id_rollback_on_verification_failure(tmp_path, monkeypatch):
    """If the post-update detector still sees poison, raise and leave a backup."""
    palace = str(tmp_path / "palace")
    _seed_poisoned_max_seq_id(palace)

    real_detect = repair._detect_poisoned_max_seq_ids
    calls = {"n": 0}

    def flaky_detect(*args, **kwargs):
        calls["n"] += 1
        # First call (pre-repair) returns the real set so the repair proceeds.
        if calls["n"] == 1:
            return real_detect(*args, **kwargs)
        # Second call (post-repair verification) claims poison still exists.
        return [("seg-fake-still-poisoned", repair.MAX_SEQ_ID_SANITY_THRESHOLD + 1)]

    monkeypatch.setattr(repair, "_detect_poisoned_max_seq_ids", flaky_detect)

    with pytest.raises(repair.MaxSeqIdVerificationError):
        repair.repair_max_seq_id(palace, assume_yes=True)

    # A backup file is still present — caller can roll back from it.
    leftover = [fn for fn in os.listdir(palace) if "max-seq-id-backup-" in fn]
    assert leftover


# ── rebuild_hnsw_segment (issue #1046) ────────────────────────────────


def test_rebuild_hnsw_missing_segment_dir(tmp_path, capsys):
    palace = tmp_path / "palace"
    palace.mkdir()
    (palace / "chroma.sqlite3").write_text("db")
    result = repair.rebuild_hnsw_segment(str(palace), segment="missing-uuid", assume_yes=True)
    assert result["aborted"] is True
    assert result["reason"] == "segment-missing"
    assert "Segment directory not found" in capsys.readouterr().out


def test_rebuild_hnsw_missing_palace(tmp_path, capsys):
    result = repair.rebuild_hnsw_segment(
        str(tmp_path / "does-not-exist"), segment="abc", assume_yes=True
    )
    assert result["aborted"] is True
    assert result["reason"] == "palace-missing"


def test_rebuild_hnsw_missing_db(tmp_path, capsys):
    palace = tmp_path / "palace"
    palace.mkdir()
    result = repair.rebuild_hnsw_segment(str(palace), segment="abc", assume_yes=True)
    assert result["aborted"] is True
    assert result["reason"] == "db-missing"


def test_rebuild_hnsw_dry_run_no_mutation(synthetic_segment):
    palace = synthetic_segment["palace"]
    segment = synthetic_segment["segment"]
    seg_dir = os.path.join(palace, segment)

    before = {
        name: os.stat(os.path.join(seg_dir, name)).st_mtime_ns for name in os.listdir(seg_dir)
    }
    palace_before = sorted(os.listdir(palace))

    result = repair.rebuild_hnsw_segment(palace, segment=segment, dry_run=True, assume_yes=True)
    assert result["aborted"] is False
    assert result["dry_run"] is True
    assert result["healthy_labels"] == 4
    assert result["space"] == "cosine"

    after = {name: os.stat(os.path.join(seg_dir, name)).st_mtime_ns for name in os.listdir(seg_dir)}
    assert before == after
    assert sorted(os.listdir(palace)) == palace_before


def test_rebuild_hnsw_smoke(synthetic_segment):
    import hnswlib

    palace = synthetic_segment["palace"]
    segment = synthetic_segment["segment"]
    vectors = synthetic_segment["vectors"]

    result = repair.rebuild_hnsw_segment(palace, segment=segment, assume_yes=True, max_elements=500)
    assert result["aborted"] is False
    assert result["healthy_labels"] == 4
    assert result["max_elements"] == 500
    assert result["backup"] and os.path.isdir(result["backup"])

    seg_dir = os.path.join(palace, segment)
    idx = hnswlib.Index(space="cosine", dim=_DIM)
    idx.load_index(seg_dir, is_persistent_index=True, max_elements=500)
    labels_got, _ = idx.knn_query(vectors, k=1)
    assert list(labels_got.flatten()) == [101, 202, 303, 404]

    # link_lists.bin is rebuilt from scratch; should be much smaller than the 1 KB we seeded
    link_lists_size = os.path.getsize(os.path.join(seg_dir, "link_lists.bin"))
    assert link_lists_size < 1024


def test_rebuild_hnsw_purge_queue(synthetic_segment):
    palace = synthetic_segment["palace"]
    segment = synthetic_segment["segment"]
    db_path = os.path.join(palace, "chroma.sqlite3")

    before = sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM embeddings_queue").fetchone()[0]
    assert before > 0

    result = repair.rebuild_hnsw_segment(palace, segment=segment, assume_yes=True, purge_queue=True)
    assert result["queue_rows_purged"] == before

    after = sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM embeddings_queue").fetchone()[0]
    assert after == 0


def test_rebuild_hnsw_quarantine_orphans_writes_sidecar(synthetic_segment):
    palace = synthetic_segment["palace"]
    segment = synthetic_segment["segment"]
    sidecar = os.path.join(palace, "quarantined_orphans.json")
    assert not os.path.exists(sidecar)

    repair.rebuild_hnsw_segment(palace, segment=segment, assume_yes=True, quarantine_orphans=True)

    assert os.path.isfile(sidecar)
    with open(sidecar) as f:
        data = json.load(f)
    assert isinstance(data, list) and len(data) == 1
    assert "uid-stale" in data[0]["stale_pickle_ids"]


def test_rebuild_hnsw_max_elements_override(synthetic_segment):
    palace = synthetic_segment["palace"]
    segment = synthetic_segment["segment"]
    seg_dir = os.path.join(palace, segment)

    result = repair.rebuild_hnsw_segment(palace, segment=segment, assume_yes=True, max_elements=500)
    assert result["max_elements"] == 500

    with open(os.path.join(seg_dir, "header.bin"), "rb") as f:
        hdr = repair._parse_hnsw_header(f.read(100))
    assert hdr.max_elements == 500


def test_rebuild_hnsw_max_elements_override_below_count(synthetic_segment):
    palace = synthetic_segment["palace"]
    segment = synthetic_segment["segment"]
    with pytest.raises(ValueError, match="smaller than healthy"):
        repair.rebuild_hnsw_segment(palace, segment=segment, assume_yes=True, max_elements=2)


def test_rebuild_hnsw_rollback_on_build_failure(synthetic_segment, monkeypatch):
    palace = synthetic_segment["palace"]
    segment = synthetic_segment["segment"]
    seg_dir = os.path.join(palace, segment)
    pre_contents = sorted(os.listdir(seg_dir))
    pre_sizes = {name: os.path.getsize(os.path.join(seg_dir, name)) for name in pre_contents}

    def _boom(*args, **kwargs):
        raise RuntimeError("synthetic build failure")

    monkeypatch.setattr(repair, "_build_persistent_index", _boom)

    with pytest.raises(RuntimeError, match="synthetic build failure"):
        repair.rebuild_hnsw_segment(palace, segment=segment, assume_yes=True)

    assert os.path.isdir(seg_dir), "live segment dir must survive a failed build"
    assert sorted(os.listdir(seg_dir)) == pre_contents
    for name in pre_contents:
        assert (
            os.path.getsize(os.path.join(seg_dir, name)) == pre_sizes[name]
        ), f"{name} was modified despite rollback"
    # No stray .old-* dirs left around
    assert not any(n.startswith(segment + ".old-") for n in os.listdir(palace))


def test_rebuild_hnsw_no_backup_flag(synthetic_segment):
    palace = synthetic_segment["palace"]
    segment = synthetic_segment["segment"]

    result = repair.rebuild_hnsw_segment(palace, segment=segment, assume_yes=True, backup=False)
    assert result["backup"] is None
    assert not any(n.startswith(segment + ".hnsw-backup-") for n in os.listdir(palace))


def test_detect_space_fallback_when_missing(tmp_path):
    palace = tmp_path / "palace"
    palace.mkdir()
    db_path = palace / "chroma.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE segments(id TEXT PRIMARY KEY, type TEXT, scope TEXT, collection TEXT);
        CREATE TABLE collection_metadata(collection_id TEXT, key TEXT, str_value TEXT);
        INSERT INTO segments VALUES ('seg-x', 'VECTOR', 'VECTOR', 'coll-x');
        """
    )
    conn.commit()
    conn.close()

    assert repair._detect_space(str(palace), "seg-x") == "l2"


def test_detect_space_returns_configured_value(tmp_path):
    palace = tmp_path / "palace"
    palace.mkdir()
    db_path = palace / "chroma.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE segments(id TEXT PRIMARY KEY, type TEXT, scope TEXT, collection TEXT);
        CREATE TABLE collection_metadata(collection_id TEXT, key TEXT, str_value TEXT);
        INSERT INTO segments VALUES ('seg-x', 'VECTOR', 'VECTOR', 'coll-x');
        INSERT INTO collection_metadata VALUES ('coll-x', 'hnsw:space', 'ip');
        """
    )
    conn.commit()
    conn.close()

    assert repair._detect_space(str(palace), "seg-x") == "ip"


def test_parse_hnsw_header_round_trip():
    header = _pack_header(max_elements=1000, cur_count=42)
    hdr = repair._parse_hnsw_header(header)
    assert hdr.max_elements == 1000
    assert hdr.cur_count == 42
    assert hdr.dim == _DIM
    assert hdr.size_per_element == _SIZE_PER_ELEMENT


def test_parse_hnsw_header_too_short():
    with pytest.raises(ValueError, match="too short"):
        repair._parse_hnsw_header(b"\x00" * 20)


def test_extract_vectors_accepts_cur_count_sized_file():
    np = pytest.importorskip("numpy")
    cur_count, max_elements = 5, 100
    header = _pack_header(max_elements=max_elements, cur_count=cur_count)
    hdr = repair._parse_hnsw_header(header)

    data = bytearray(cur_count * _SIZE_PER_ELEMENT)
    data[:100] = header
    vectors = np.arange(cur_count * _DIM, dtype=np.float32).reshape(cur_count, _DIM)
    for i in range(cur_count):
        slot = i * _SIZE_PER_ELEMENT
        data[slot + _OFFSET_DATA : slot + _OFFSET_DATA + _DIM * 4] = vectors[i].tobytes()
        struct.pack_into("<Q", data, slot + _LABEL_OFFSET, i + 1)

    labels, out_vectors = repair._extract_vectors(bytes(data), hdr)
    assert len(labels) == cur_count
    assert out_vectors.shape == (cur_count, _DIM)
    assert list(int(x) for x in labels) == [1, 2, 3, 4, 5]


def test_sanitize_vectors_drops_zeros_and_dedups():
    np = pytest.importorskip("numpy")
    labels = np.array([5, 5, 0, 7, 3], dtype=np.uint64)
    vectors = np.arange(5 * 4, dtype=np.float32).reshape(5, 4)
    out_labels, out_vectors = repair._sanitize_vectors(labels, vectors)
    # Zero dropped; duplicate 5 deduplicated keeping the later row.
    assert 0 not in set(int(x) for x in out_labels)
    assert sorted(int(x) for x in out_labels) == [3, 5, 7]
    # The second occurrence of label 5 (index 1) has row [4,5,6,7]; that's what survives.
    row_for_5 = out_vectors[list(out_labels).index(5)]
    assert list(row_for_5) == [4.0, 5.0, 6.0, 7.0]


def test_compute_max_elements_default():
    assert repair._compute_max_elements(100, None) == 200_000
    assert repair._compute_max_elements(500_000, None) == 650_000


def test_compute_max_elements_override_rejects_below_count():
    with pytest.raises(ValueError):
        repair._compute_max_elements(100, 50)


def test_atomic_swap_rollback(tmp_path):
    live = tmp_path / "seg"
    live.mkdir()
    (live / "marker").write_text("live-v1")

    tmpdir = tmp_path / "tmp-new"
    tmpdir.mkdir()
    (tmpdir / "marker").write_text("new-v1")

    # Sabotage os.replace so the swap fails after the live dir was renamed aside.
    original_replace = os.replace
    call_count = {"n": 0}

    def failing_replace(src, dst):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise OSError("synthetic replace failure")
        return original_replace(src, dst)

    with patch("mempalace.repair.os.replace", side_effect=failing_replace):
        with pytest.raises(OSError):
            repair._atomic_swap_segment(str(tmpdir), str(live))

    assert live.exists(), "rollback must restore live dir"
    assert (live / "marker").read_text() == "live-v1"


def test_purge_segment_queue_deletes_only_matching(tmp_path):
    palace = tmp_path / "palace"
    palace.mkdir()
    db_path = palace / "chroma.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE segments(id TEXT PRIMARY KEY, type TEXT, scope TEXT, collection TEXT);
        CREATE TABLE embeddings_queue(seq_id INTEGER PRIMARY KEY, topic TEXT, id TEXT);
        INSERT INTO segments VALUES ('seg-x', 'VECTOR', 'VECTOR', 'coll-x');
        INSERT INTO embeddings_queue VALUES (1, 'persistent://default/default/coll-x', 'a');
        INSERT INTO embeddings_queue VALUES (2, 'persistent://default/default/coll-x', 'b');
        INSERT INTO embeddings_queue VALUES (3, 'persistent://default/default/coll-other', 'c');
        """
    )
    conn.commit()
    conn.close()

    deleted = repair._purge_segment_queue(str(palace), "seg-x")
    assert deleted == 2

    remaining = sqlite3.connect(str(db_path)).execute("SELECT id FROM embeddings_queue").fetchall()
    assert [r[0] for r in remaining] == ["c"]


def test_quarantine_orphans_appends(tmp_path):
    palace = str(tmp_path / "palace")
    os.makedirs(palace)
    sidecar = repair._quarantine_orphans(palace, ["uid-1"], [999])
    sidecar = repair._quarantine_orphans(palace, ["uid-2"], [1001])
    with open(sidecar) as f:
        data = json.load(f)
    assert len(data) == 2
    assert data[0]["stale_pickle_ids"] == ["uid-1"]
    assert data[1]["orphan_hnsw_labels"] == [1001]


# ── status() integration: capacity-divergence fix-it hint (#1046 + #1222) ──


def test_status_suggests_hnsw_segment_mode_when_diverged(tmp_path, monkeypatch, capsys):
    """When hnsw_capacity_status reports divergence, status() should print
    the actionable `--mode hnsw --segment <uuid>` recovery command alongside
    the legacy full-rebuild option, with the segment UUID inline.
    """
    palace = tmp_path / "palace"
    palace.mkdir()
    seg_uuid = "deadbeef-1111-2222-3333-444455556666"

    def _fake_status(_palace, collection):
        if collection == "mempalace_drawers":
            return {
                "segment_id": seg_uuid,
                "sqlite_count": 200_000,
                "hnsw_count": 16_384,
                "divergence": 183_616,
                "diverged": True,
                "status": "diverged",
                "message": "HNSW frozen at stale max_elements",
            }
        return {
            "segment_id": None,
            "sqlite_count": 0,
            "hnsw_count": None,
            "divergence": None,
            "diverged": False,
            "status": "ok",
            "message": "",
        }

    monkeypatch.setattr(repair, "hnsw_capacity_status", _fake_status)
    result = repair.status(palace_path=str(palace))
    out = capsys.readouterr().out

    assert result["drawers"]["diverged"] is True
    assert "--mode hnsw --segment" in out
    assert seg_uuid in out
    assert "mempalace repair" in out  # legacy full-rebuild path also surfaced
