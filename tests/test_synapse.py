"""
Tests for mempalace.synapse — SynapseDB retrieval logging and scoring.
"""

import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from mempalace.searcher import search_memories
from mempalace.synapse import DEFAULT_LTP_WINDOW_DAYS, SynapseDB


def _synapse_cfg(**overrides):
    base = dict(
        synapse_enabled=True,
        synapse_ltp_enabled=True,
        synapse_tagging_enabled=True,
        synapse_association_enabled=False,
        synapse_ltp_window_days=30,
        synapse_ltp_max_boost=2.0,
        synapse_tagging_window_hours=24,
        synapse_tagging_max_boost=1.5,
        synapse_log_retrievals=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def tmp_palace():
    d = tempfile.mkdtemp(prefix="mempalace_synapse_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


# --- SynapseDB 初期化 ---


def test_init_creates_db(tmp_palace):
    SynapseDB(tmp_palace)
    assert os.path.isfile(os.path.join(tmp_palace, "synapse.sqlite3"))


def test_init_creates_tables(tmp_palace):
    db = SynapseDB(tmp_palace)
    conn = sqlite3.connect(db.db_path)
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        names = {row[0] for row in cur.fetchall()}
    finally:
        conn.close()
    assert "co_retrieval" in names
    assert "retrieval_log" in names
    assert "synapse_stats" in names


def test_init_idempotent(tmp_palace):
    SynapseDB(tmp_palace)
    SynapseDB(tmp_palace)


# --- retrieval_log ---


def test_log_retrieval_single(tmp_palace):
    db = SynapseDB(tmp_palace)
    db.log_retrieval(["drawer_a"], "qh", "sess")
    conn = sqlite3.connect(db.db_path)
    try:
        n = conn.execute("SELECT COUNT(*) FROM retrieval_log").fetchone()[0]
        row = conn.execute("SELECT drawer_id FROM retrieval_log LIMIT 1").fetchone()
    finally:
        conn.close()
    assert n == 1
    assert row[0] == "drawer_a"


def test_log_retrieval_batch(tmp_palace):
    db = SynapseDB(tmp_palace)
    ids = [f"d{i}" for i in range(5)]
    db.log_retrieval(ids, "qh", "sess")
    conn = sqlite3.connect(db.db_path)
    try:
        n = conn.execute("SELECT COUNT(*) FROM retrieval_log").fetchone()[0]
    finally:
        conn.close()
    assert n == 5


def test_log_retrieval_empty_list(tmp_palace):
    db = SynapseDB(tmp_palace)
    db.log_retrieval([], "qh", "sess")
    conn = sqlite3.connect(db.db_path)
    try:
        n = conn.execute("SELECT COUNT(*) FROM retrieval_log").fetchone()[0]
    finally:
        conn.close()
    assert n == 0


def test_log_retrieval_exception_suppressed(tmp_palace):
    db = SynapseDB(tmp_palace)
    with patch("mempalace.synapse.sqlite3.connect", side_effect=sqlite3.OperationalError("readonly")):
        db.log_retrieval(["a"], "h", "s")


# --- LTP スコアリング ---


def test_ltp_no_retrievals(tmp_palace):
    db = SynapseDB(tmp_palace)
    assert db.get_ltp_score("missing") == 1.0


def test_ltp_single_retrieval(tmp_palace):
    db = SynapseDB(tmp_palace)
    db.log_retrieval(["x"], "q", "s")
    s = db.get_ltp_score("x")
    assert 1.0 < s <= 2.0


def test_ltp_high_frequency(tmp_palace):
    db = SynapseDB(tmp_palace)
    for _ in range(30):
        db.log_retrieval(["hf"], "q", "s")
    s = db.get_ltp_score("hf")
    assert s >= 1.99


def test_ltp_clamped_at_max(tmp_palace):
    db = SynapseDB(tmp_palace)
    for _ in range(1000):
        db.log_retrieval(["many"], "q", "s")
    assert db.get_ltp_score("many") <= 2.0


def test_ltp_outside_window(tmp_palace):
    db = SynapseDB(tmp_palace)
    old = (datetime.now(timezone.utc) - timedelta(days=DEFAULT_LTP_WINDOW_DAYS + 5)).isoformat()
    conn = sqlite3.connect(db.db_path)
    try:
        conn.execute(
            "INSERT INTO retrieval_log (drawer_id, retrieved_at, query_hash, session_id) VALUES (?,?,?,?)",
            ("old", old, "q", "s"),
        )
        conn.commit()
    finally:
        conn.close()
    assert db.get_ltp_score("old") == 1.0


def test_ltp_batch_consistency(tmp_palace):
    db = SynapseDB(tmp_palace)
    db.log_retrieval(["a", "b"], "q", "s")
    batch = db.get_ltp_scores_batch(["a", "b", "c"])
    assert batch["a"] == db.get_ltp_score("a")
    assert batch["b"] == db.get_ltp_score("b")
    assert batch["c"] == 1.0


# --- Tagging ---


def test_tagging_just_filed():
    t = datetime.now(timezone.utc)
    boost = SynapseDB.calculate_tagging_boost(t.isoformat())
    assert abs(boost - 1.5) < 0.02


def test_tagging_12_hours():
    t = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
    assert abs(SynapseDB.calculate_tagging_boost(t) - 1.25) < 0.01


def test_tagging_25_hours():
    t = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    assert SynapseDB.calculate_tagging_boost(t) == 1.0


def test_tagging_none_filed_at():
    assert SynapseDB.calculate_tagging_boost(None) == 1.0


# --- Synapse スコア合成 ---


def test_synapse_score_composition(tmp_palace):
    db = SynapseDB(tmp_palace)
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    r = db.calculate_synapse_score(
        similarity=0.8,
        decay=0.5,
        drawer_id="d1",
        filed_at=old,
        ltp_scores={"d1": 1.5},
        window_days=DEFAULT_LTP_WINDOW_DAYS,
    )
    assert abs(r["final_score"] - 0.6) < 1e-9
    assert r["association"] == 1.0
    assert r["similarity"] == 0.8
    assert r["decay"] == 0.5
    assert r["ltp"] == 1.5
    assert r["tagging"] == 1.0


# --- Consolidation ---


def test_consolidation_candidates_returns_inactive(tmp_palace):
    db = SynapseDB(tmp_palace)
    old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    conn = sqlite3.connect(db.db_path)
    try:
        conn.execute(
            "INSERT INTO retrieval_log (drawer_id, retrieved_at, query_hash, session_id) VALUES (?,?,?,?)",
            ("stale", old, "q", "s"),
        )
        conn.commit()
    finally:
        conn.close()
    cands = db.get_consolidation_candidates(inactive_days=180)
    ids = {c["drawer_id"] for c in cands}
    assert "stale" in ids


def test_consolidation_candidates_excludes_active(tmp_palace):
    db = SynapseDB(tmp_palace)
    recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    conn = sqlite3.connect(db.db_path)
    try:
        conn.execute(
            "INSERT INTO retrieval_log (drawer_id, retrieved_at, query_hash, session_id) VALUES (?,?,?,?)",
            ("active", recent, "q", "s"),
        )
        conn.commit()
    finally:
        conn.close()
    cands = db.get_consolidation_candidates(inactive_days=180)
    ids = {c["drawer_id"] for c in cands}
    assert "active" not in ids


# --- Config axis switches (search_memories integration) ---


def test_ltp_disabled_returns_neutral(palace_path, seeded_collection):
    cfg = _synapse_cfg(synapse_ltp_enabled=False)

    def fake_batch(self, drawer_ids, window_days=30, max_boost=2.0):
        return {d: 2.0 for d in drawer_ids}

    with patch("mempalace.config.MempalaceConfig", return_value=cfg):
        with patch.object(SynapseDB, "get_ltp_scores_batch", fake_batch):
            result = search_memories("JWT authentication", palace_path)
    assert result.get("synapse_enabled") is True
    for hit in result["hits"]:
        assert hit["synapse_factors"]["ltp"] == 1.0


def test_tagging_disabled_returns_neutral(palace_path, seeded_collection):
    cfg = _synapse_cfg(synapse_tagging_enabled=False)
    with patch("mempalace.config.MempalaceConfig", return_value=cfg):
        result = search_memories("JWT authentication", palace_path)
    assert result.get("synapse_enabled") is True
    for hit in result["hits"]:
        assert hit["synapse_factors"]["tagging"] == 1.0


# --- Log cleanup ---


def test_log_cleanup_removes_old_entries(tmp_palace):
    db = SynapseDB(tmp_palace)
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    new = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    conn = sqlite3.connect(db.db_path)
    try:
        conn.executemany(
            "INSERT INTO retrieval_log (drawer_id, retrieved_at, query_hash, session_id) VALUES (?,?,?,?)",
            [("a", old, "q", "s"), ("b", new, "q", "s")],
        )
        conn.commit()
    finally:
        conn.close()
    deleted = db.cleanup_old_logs(retention_days=30)
    assert deleted == 1
    conn = sqlite3.connect(db.db_path)
    try:
        rows = conn.execute("SELECT drawer_id FROM retrieval_log ORDER BY drawer_id").fetchall()
    finally:
        conn.close()
    assert [r[0] for r in rows] == ["b"]
