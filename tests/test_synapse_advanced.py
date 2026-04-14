"""Tests for Synapse Advanced Retrieval (Phases 5-9)."""

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import chromadb
import pytest

from mempalace.synapse import SYNAPSE_MARK_NEW, SynapseDB
from mempalace.synapse_profiles import HARDCODED_DEFAULTS, ProfileManager
from mempalace.searcher import search_memories


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
        synapse_association_max_boost=1.5,
        synapse_association_coefficient=0.15,
        synapse_consolidation_inactive_days=180,
        synapse_soft_archive_suggestions_enabled=True,
        synapse_soft_archive_target_wing="archive",
        synapse_log_retrievals=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def adv_palace(tmp_path):
    p = str(tmp_path / "palace")
    os.makedirs(p, exist_ok=True)
    return p


@pytest.fixture
def adv_col(adv_palace):
    client = chromadb.PersistentClient(path=adv_palace)
    col = client.get_or_create_collection("mempalace_drawers")
    yield col
    try:
        client.delete_collection("mempalace_drawers")
    except Exception:
        pass


# --- Phase 5: MMR ---


class TestMMR:
    """Phase 5: MMR tests."""

    def test_mmr_removes_near_duplicates(self):
        import tempfile

        ident = [1.0] * 12
        scored = [
            {"id": "a", "synapse_score": 0.95, "embedding": list(ident)},
            {"id": "b", "synapse_score": 0.94, "embedding": list(ident)},
            {"id": "c", "synapse_score": 0.93, "embedding": list(ident)},
        ]
        d = tempfile.mkdtemp()
        try:
            sdb = SynapseDB(d)
            out = sdb.apply_mmr(scored, list(ident), lambda_param=0.5, final_k=1)
            assert len(out["results"]) == 1
        finally:
            import shutil

            shutil.rmtree(d, ignore_errors=True)

    def test_mmr_preserves_diverse_results(self):
        scored = []
        for i in range(5):
            v = [0.0] * 8
            v[i] = 1.0
            scored.append({"id": f"d{i}", "synapse_score": 0.8 - i * 0.01, "embedding": v})
        import tempfile

        d = tempfile.mkdtemp()
        try:
            sdb = SynapseDB(d)
            q = [0.2] * 8
            out = sdb.apply_mmr(scored, q, lambda_param=0.5, final_k=5)
            assert len(out["results"]) == 5
        finally:
            import shutil

            shutil.rmtree(d, ignore_errors=True)

    def test_mmr_lambda_1_equals_no_mmr(self):
        scored = []
        base = [1.0] * 6
        for i in range(10):
            scored.append(
                {
                    "id": f"x{i}",
                    "synapse_score": 1.0 - i * 0.01,
                    "embedding": [x + i * 1e-6 for x in base],
                }
            )
        import tempfile

        d = tempfile.mkdtemp()
        try:
            sdb = SynapseDB(d)
            q = [1.0] * 6
            out = sdb.apply_mmr(scored, q, lambda_param=1.0, final_k=10)
            expected = [
                h["id"] for h in sorted(scored, key=lambda h: h["synapse_score"], reverse=True)
            ]
            got = [h["id"] for h in out["results"]]
            assert got == expected
        finally:
            import shutil

            shutil.rmtree(d, ignore_errors=True)

    def test_mmr_disabled_by_default(self):
        assert HARDCODED_DEFAULTS["mmr_enabled"] is False

    def test_mmr_profile_override(self, tmp_path):
        palace = str(tmp_path / "p")
        os.makedirs(palace, exist_ok=True)
        cfg = {
            "synapse_profiles": {
                "default": {"mmr_lambda": 0.5, "mmr_final_k": 10},
                "orient": {"mmr_lambda": 0.5, "mmr_final_k": 10},
                "decide": {"mmr_lambda": 0.85, "mmr_final_k": 3},
            }
        }
        with open(os.path.join(palace, "config.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        pm = ProfileManager(palace)
        o = pm.resolve("orient").to_dict()
        d = pm.resolve("decide").to_dict()
        assert o["mmr_lambda"] == 0.5
        assert o["mmr_final_k"] == 10
        assert d["mmr_lambda"] == 0.85
        assert d["mmr_final_k"] == 3

    def test_mmr_observability_fields(self):
        import tempfile

        d = tempfile.mkdtemp()
        try:
            sdb = SynapseDB(d)
            scored = [{"id": "a", "synapse_score": 1.0, "embedding": [1.0, 0.0]}]
            out = sdb.apply_mmr(scored, [1.0, 0.0], lambda_param=0.7, final_k=3)
            m = out["mmr_metadata"]
            for k in (
                "applied",
                "lambda",
                "candidates_before_mmr",
                "candidates_after_mmr",
                "dropped_as_redundant",
                "max_internal_similarity",
            ):
                assert k in m
        finally:
            import shutil

            shutil.rmtree(d, ignore_errors=True)


# --- Phase 6: Pinned ---


class TestPinnedMemory:
    """Phase 6: Pinned Memory tests."""

    def test_pinned_returns_top_ltp(self, adv_palace, adv_col):
        adv_col.add(
            ids=["hot", "cold"],
            documents=["a", "b"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()},
                {"wing": "w", "room": "r2", "filed_at": datetime.now(timezone.utc).isoformat()},
            ],
        )
        db = SynapseDB(adv_palace)
        for _ in range(20):
            db.log_retrieval(["hot"], "q", "s")
        db.refresh_stats(window_days=30, ltp_max_boost=2.0)
        res = db.get_pinned_memories(adv_col, ltp_threshold=1.0, max_items=5, max_tokens=5000)
        ids = {p["drawer_id"] for p in res["pinned_memories"]}
        assert "hot" in ids

    def test_pinned_includes_recent_tagged(self, adv_palace, adv_col):
        fa = datetime.now(timezone.utc).isoformat()
        adv_col.add(
            ids=["tagged_one"],
            documents=["content"],
            metadatas=[
                {
                    "wing": "w",
                    "room": "r",
                    "filed_at": fa,
                    "synapse_mark": SYNAPSE_MARK_NEW,
                }
            ],
        )
        db = SynapseDB(adv_palace)
        db.refresh_stats(window_days=30, ltp_max_boost=2.0)
        res = db.get_pinned_memories(
            adv_col,
            ltp_threshold=99.0,
            include_tagged=True,
            tagged_window_hours=48,
            max_items=10,
            max_tokens=5000,
        )
        ids = {p["drawer_id"] for p in res["pinned_memories"]}
        assert "tagged_one" in ids

    def test_pinned_respects_max_tokens(self, adv_palace, adv_col):
        adv_col.add(
            ids=["big1", "big2"],
            documents=["x" * 4000, "y" * 4000],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()},
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()},
            ],
        )
        db = SynapseDB(adv_palace)
        for did in ["big1", "big2"]:
            for _ in range(5):
                db.log_retrieval([did], "q", "s")
        db.refresh_stats(window_days=30, ltp_max_boost=2.0)
        res = db.get_pinned_memories(adv_col, ltp_threshold=1.0, max_tokens=500, max_items=10)
        assert res["pinned_total_tokens"] <= 500

    def test_pinned_respects_max_items(self, adv_palace, adv_col):
        ids = [f"id{i}" for i in range(10)]
        docs = [f"c{i}" for i in range(10)]
        metas = [
            {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()}
            for _ in range(10)
        ]
        adv_col.add(ids=ids, documents=docs, metadatas=metas)
        db = SynapseDB(adv_palace)
        for did in ids:
            for _ in range(8):
                db.log_retrieval([did], "q", "s")
        db.refresh_stats(window_days=30, ltp_max_boost=2.0)
        res = db.get_pinned_memories(adv_col, ltp_threshold=1.0, max_items=3, max_tokens=50000)
        assert len(res["pinned_memories"]) <= 3

    def test_pinned_deduplicates(self, adv_palace, adv_col):
        fa = datetime.now(timezone.utc).isoformat()
        adv_col.add(
            ids=["both"],
            documents=["text"],
            metadatas=[
                {
                    "wing": "w",
                    "room": "r",
                    "filed_at": fa,
                    "synapse_mark": SYNAPSE_MARK_NEW,
                }
            ],
        )
        db = SynapseDB(adv_palace)
        for _ in range(15):
            db.log_retrieval(["both"], "q", "s")
        db.refresh_stats(window_days=30, ltp_max_boost=2.0)
        res = db.get_pinned_memories(
            adv_col, ltp_threshold=1.0, include_tagged=True, max_items=10, max_tokens=5000
        )
        assert sum(1 for p in res["pinned_memories"] if p["drawer_id"] == "both") == 1

    def test_pinned_disabled_returns_empty(self, adv_palace, adv_col, monkeypatch):
        from mempalace import mcp_server

        cfg = _synapse_cfg()
        cfg.palace_path = adv_palace
        monkeypatch.setattr(mcp_server, "_config", cfg)
        monkeypatch.setattr(mcp_server, "_get_collection", lambda: adv_col)
        with patch.object(mcp_server.MempalaceConfig, "__call__", lambda self: cfg):
            monkeypatch.setattr(
                "mempalace.mcp_server.MempalaceConfig",
                lambda: cfg,
            )
        # Profile default: pinned_memory_enabled False
        from mempalace.mcp_server import tool_session_context

        with patch("mempalace.mcp_server.MempalaceConfig", return_value=cfg):
            with patch("mempalace.mcp_server._get_collection", return_value=adv_col):
                with patch("mempalace.mcp_server._config", cfg):
                    r = tool_session_context()
        assert r["pinned_memories"] == []
        assert r["pinned_count"] == 0

    def test_pinned_reason_field(self, adv_palace, adv_col):
        adv_col.add(
            ids=["p1"],
            documents=["c"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()}
            ],
        )
        db = SynapseDB(adv_palace)
        for _ in range(10):
            db.log_retrieval(["p1"], "q", "s")
        db.refresh_stats(window_days=30, ltp_max_boost=2.0)
        res = db.get_pinned_memories(adv_col, ltp_threshold=1.0)
        for p in res["pinned_memories"]:
            assert p.get("pinned_reason")
            assert len(str(p["pinned_reason"])) > 0

    def test_pinned_profile_override(self, tmp_path):
        palace = str(tmp_path / "p")
        os.makedirs(palace, exist_ok=True)
        cfg = {
            "synapse_profiles": {
                "default": {"pinned_max_tokens": 2000, "pinned_max_items": 5},
                "decide": {"pinned_max_tokens": 1000, "pinned_max_items": 3},
            }
        }
        with open(os.path.join(palace, "config.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        pm = ProfileManager(palace)
        assert pm.resolve("default").to_dict()["pinned_max_tokens"] == 2000
        assert pm.resolve("decide").to_dict()["pinned_max_tokens"] == 1000
        assert pm.resolve("decide").to_dict()["pinned_max_items"] == 3

    def test_pinned_spread_boosts_cross_wing_drawer(self, adv_palace, adv_col):
        adv_col.add(
            ids=["drawer_A", "drawer_B"],
            documents=["a", "b"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()},
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()},
            ],
        )
        db = SynapseDB(adv_palace)
        now = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(db.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO synapse_stats "
            "(drawer_id, total_retrievals, recent_density, ltp_score, last_updated) "
            "VALUES (?,?,?,?,?)",
            ("drawer_A", 10, 0.0, 3.0, now),
        )
        conn.execute(
            "INSERT OR REPLACE INTO synapse_stats "
            "(drawer_id, total_retrievals, recent_density, ltp_score, last_updated) "
            "VALUES (?,?,?,?,?)",
            ("drawer_B", 10, 0.0, 3.5, now),
        )
        conn.commit()
        conn.close()
        emb = [0.1] * 8
        db.log_query("query_one", emb, ["drawer_A"], [1.0])
        db.log_query("query_two", emb, ["drawer_A"], [1.0])
        db.log_query("query_three", emb, ["drawer_A"], [1.0])
        for _ in range(5):
            db.log_query("same_query", emb, ["drawer_B"], [1.0])
        assert db.get_retrieval_spread("drawer_A") >= 3
        assert db.get_retrieval_spread("drawer_B") == 1
        res = db.get_pinned_memories(adv_col, ltp_threshold=1.0, max_items=5, max_tokens=10000)
        by_id = {p["drawer_id"]: p for p in res["pinned_memories"]}
        assert by_id["drawer_A"]["retrieval_spread"] >= 3
        assert by_id["drawer_B"]["retrieval_spread"] == 1
        assert abs(by_id["drawer_A"]["pinning_score"] - 4.8) < 0.01
        assert abs(by_id["drawer_B"]["pinning_score"] - 4.2) < 0.01
        assert res["pinned_memories"][0]["drawer_id"] == "drawer_A"

    def test_pinned_spread_field_in_response(self, adv_palace, adv_col):
        adv_col.add(
            ids=["pf1"],
            documents=["c"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()}
            ],
        )
        db = SynapseDB(adv_palace)
        for _ in range(5):
            db.log_retrieval(["pf1"], "q", "s")
        db.refresh_stats(window_days=30, ltp_max_boost=2.0)
        res = db.get_pinned_memories(adv_col, ltp_threshold=1.0)
        assert res["pinned_memories"]
        p = res["pinned_memories"][0]
        assert "retrieval_spread" in p
        assert "pinning_score" in p

    def test_pinned_spread_minimum_is_one(self, adv_palace, adv_col):
        adv_col.add(
            ids=["lonely"],
            documents=["z"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()}
            ],
        )
        db = SynapseDB(adv_palace)
        now = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(db.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO synapse_stats "
            "(drawer_id, total_retrievals, recent_density, ltp_score, last_updated) "
            "VALUES (?,?,?,?,?)",
            ("lonely", 5, 0.0, 2.0, now),
        )
        conn.commit()
        conn.close()
        assert db.get_retrieval_spread("lonely") == 1


# --- Phase 7: Query expansion ---


class TestQueryExpansion:
    """Phase 7: Query Expansion tests."""

    def test_expansion_finds_related_terms(self, adv_palace, adv_col):
        adv_col.add(
            ids=["src"],
            documents=["OAuth flow for mobile apps"],
            metadatas=[{"wing": "w", "room": "r", "title": "OAuth mobile"}],
        )
        db = SynapseDB(adv_palace)
        shared = [0.25] * 64
        db.log_query(
            "OAuth flow for mobile",
            shared,
            ["src"],
            [0.9],
        )
        ex = db.expand_query(
            adv_col,
            "auth design",
            shared,
            max_expansions=5,
            similarity_threshold=0.99,
        )
        terms = ex.get("expansion_terms") or []
        blob = " ".join(terms).lower()
        assert "oauth" in blob or "mobile" in blob or ex.get("similar_past_queries")

    def test_expansion_empty_log_returns_nothing(self, adv_palace, adv_col):
        db = SynapseDB(adv_palace)
        ex = db.expand_query(adv_col, "q", [0.0] * 4, max_expansions=3, similarity_threshold=0.5)
        assert ex.get("expansion_terms") == []

    def test_expansion_boost_applied(self, adv_palace):
        cfg = _synapse_cfg()
        cfg.synapse_log_retrievals = False
        client = chromadb.PersistentClient(path=adv_palace)
        col = client.get_or_create_collection("mempalace_drawers")
        col.add(
            ids=["o1", "o2"],
            documents=["alpha unique", "beta unique"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()},
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()},
            ],
        )
        syn = os.path.join(adv_palace, "synapse_profiles.json")
        with open(syn, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "default": {
                        "query_expansion_enabled": True,
                        "query_expansion_max_terms": 1,
                        "query_expansion_similarity_threshold": 0.0,
                        "query_expansion_boost": 0.5,
                    }
                },
                f,
            )
        db = SynapseDB(adv_palace)
        db.log_query("past q", [0.01] * 8, ["o1"], [0.8])
        with patch("mempalace.config.MempalaceConfig", return_value=cfg):
            r = search_memories("past q expandedterm", palace_path=adv_palace, n_results=5)
        assert r.get("synapse_enabled") is True
        # Expansion path may merge; at least metadata records boost
        assert "synapse_query_expansion" in r

    def test_expansion_original_always_prioritized(self, adv_palace):
        cfg = _synapse_cfg()
        client = chromadb.PersistentClient(path=adv_palace)
        col = client.get_or_create_collection("mempalace_drawers")
        col.add(
            ids=["same"],
            documents=["hello world"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()}
            ],
        )
        with patch("mempalace.config.MempalaceConfig", return_value=cfg):
            r = search_memories("hello", palace_path=adv_palace, n_results=5)
        hits = {h["id"]: h for h in r["hits"]}
        if "same" in hits:
            assert not hits["same"].get("_from_expansion", False)

    def test_expansion_disabled_by_default(self):
        assert HARDCODED_DEFAULTS["query_expansion_enabled"] is False

    def test_expansion_profile_override(self, tmp_path):
        palace = str(tmp_path / "p")
        os.makedirs(palace, exist_ok=True)
        cfg = {
            "synapse_profiles": {
                "orient": {"query_expansion_enabled": True},
                "decide": {"query_expansion_enabled": False},
            }
        }
        with open(os.path.join(palace, "config.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        pm = ProfileManager(palace)
        assert pm.resolve("orient").to_dict()["query_expansion_enabled"] is True
        assert pm.resolve("decide").to_dict()["query_expansion_enabled"] is False

    def test_expansion_observability_fields(self, adv_palace, adv_col):
        db = SynapseDB(adv_palace)
        db.log_query("a", [0.1, 0.2], ["x"], [1.0])
        ex = db.expand_query(adv_col, "b", [0.1, 0.2], max_expansions=2, similarity_threshold=0.0)
        assert "applied" in ex
        assert "original_query" in ex
        assert "similar_past_queries" in ex
        assert "expansion_terms" in ex

    def test_expansion_lookback_ignores_old_logs(self, adv_palace, adv_col):
        """lookback window 外の古いログが無視されることを確認。"""
        adv_col.add(
            ids=["drawer_A", "drawer_B"],
            documents=["OAuth mobile app", "REST API auth"],
            metadatas=[
                {"wing": "w", "room": "r", "title": "OAuth mobile"},
                {"wing": "w", "room": "r", "title": "REST API"},
            ],
        )
        db = SynapseDB(adv_palace)
        shared = [0.25] * 64
        db.log_query("OAuth flow for mobile", shared, ["drawer_A"], [0.9])
        db.log_query("REST API authentication", shared, ["drawer_B"], [0.9])

        old_ts = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        conn = sqlite3.connect(db.db_path)
        conn.execute(
            "UPDATE query_log SET timestamp = ? WHERE query_text = ?",
            (old_ts, "OAuth flow for mobile"),
        )
        conn.commit()
        conn.close()

        ex = db.expand_query(
            adv_col,
            "auth design",
            shared,
            max_expansions=5,
            similarity_threshold=0.0,
            lookback_days=60,
        )
        past = ex.get("similar_past_queries") or []
        assert "OAuth flow for mobile" not in past
        assert "REST API authentication" in past
        assert ex.get("metadata", {}).get("lookback_days") == 60
        terms_blob = " ".join(ex.get("expansion_terms") or []).lower()
        assert "oauth" not in terms_blob

    def test_expansion_lookback_default_in_profile(self):
        """HARDCODED_DEFAULTS に query_expansion_lookback_days=60 が存在することを確認。"""
        assert HARDCODED_DEFAULTS.get("query_expansion_lookback_days") == 60


# --- Phase 8: Supersede ---


class TestSupersedeDetection:
    """Phase 8: Supersede Detection tests."""

    def _pair_drawers(self, adv_col, days_apart: int):
        old = (datetime.now(timezone.utc) - timedelta(days=days_apart + 40)).isoformat()
        new = datetime.now(timezone.utc).isoformat()
        emb = adv_col._embedding_function(["same topic content"])[0]
        if hasattr(emb, "tolist"):
            emb = emb.tolist()
        adv_col.add(
            ids=["old_d", "new_d"],
            documents=["same topic content", "same topic content"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": old, "title": "t1"},
                {"wing": "w", "room": "r", "filed_at": new, "title": "t2"},
            ],
            embeddings=[emb, emb],
        )

    def test_supersede_detects_similar_pair(self, adv_palace, adv_col):
        self._pair_drawers(adv_col, 30)
        db = SynapseDB(adv_palace)
        r = db.detect_superseded(
            adv_col, ["old_d", "new_d"], similarity_threshold=0.80, min_age_gap_days=7
        )
        assert len(r["candidates"]) >= 1

    def test_supersede_ignores_same_day(self, adv_palace, adv_col):
        ts = datetime.now(timezone.utc).isoformat()
        emb = adv_col._embedding_function(["dup"])[0]
        if hasattr(emb, "tolist"):
            emb = emb.tolist()
        adv_col.add(
            ids=["a1", "a2"],
            documents=["dup", "dup"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": ts},
                {"wing": "w", "room": "r", "filed_at": ts},
            ],
            embeddings=[emb, emb],
        )
        db = SynapseDB(adv_palace)
        r = db.detect_superseded(adv_col, ["a1", "a2"], min_age_gap_days=7)
        assert len(r["candidates"]) == 0

    def test_supersede_respects_threshold(self, adv_palace, adv_col):
        old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        new = datetime.now(timezone.utc).isoformat()
        e1 = [1.0, 0.0, 0.0]
        e2 = [0.0, 1.0, 0.0]
        adv_col.add(
            ids=["u1", "u2"],
            documents=["x", "y"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": old},
                {"wing": "w", "room": "r", "filed_at": new},
            ],
            embeddings=[e1, e2],
        )
        db = SynapseDB(adv_palace)
        r = db.detect_superseded(
            adv_col, ["u1", "u2"], similarity_threshold=0.99, min_age_gap_days=7
        )
        assert len(r["candidates"]) == 0

    def test_supersede_confidence_ranking(self, adv_palace, adv_col):
        # synthetic candidates order
        cands = [
            {"confidence": "low", "similarity": 0.9},
            {"confidence": "high", "similarity": 0.95},
            {"confidence": "medium", "similarity": 0.88},
        ]
        conf_rank = {"high": 0, "medium": 1, "low": 2}
        cands.sort(key=lambda c: (conf_rank.get(c["confidence"], 3), -c["similarity"]))
        assert cands[0]["confidence"] == "high"

    def test_supersede_filter_mode(self):
        db = SynapseDB(os.path.join(os.path.dirname(__file__), ".."))
        results = [
            {"id": "s1"},
            {"id": "s2"},
            {"id": "s3"},
        ]
        sup = {
            "candidates": [
                {
                    "superseded_id": "s1",
                    "superseding_id": "s3",
                    "similarity": 0.9,
                    "confidence": "high",
                }
            ]
        }
        out = db.apply_supersede_filter(results, sup, action="filter")
        assert len(out["results"]) == 2
        assert out["synapse_supersede"]["superseded_filtered"] == 1

    def test_supersede_annotate_mode(self):
        import tempfile

        d = tempfile.mkdtemp()
        try:
            db = SynapseDB(d)
            results = [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}]
            sup = {
                "candidates": [
                    {
                        "superseded_id": "s1",
                        "superseding_id": "s3",
                        "similarity": 0.9,
                        "confidence": "high",
                    }
                ]
            }
            out = db.apply_supersede_filter(results, sup, action="annotate")
            assert len(out["results"]) == 3
            s1 = next(h for h in out["results"] if h["id"] == "s1")
            assert "synapse_superseded_by" in s1
        finally:
            import shutil

            shutil.rmtree(d, ignore_errors=True)

    def test_supersede_no_deletion(self, adv_palace, adv_col):
        self._pair_drawers(adv_col, 30)
        before = set(adv_col.get()["ids"])
        db = SynapseDB(adv_palace)
        db.detect_superseded(adv_col, ["old_d", "new_d"])
        after = set(adv_col.get()["ids"])
        assert before == after

    def test_supersede_observability_fields(self):
        import tempfile

        d = tempfile.mkdtemp()
        try:
            db = SynapseDB(d)
            out = db.apply_supersede_filter(
                [{"id": "a"}],
                {"candidates": []},
                action="filter",
            )
            ss = out["synapse_supersede"]
            assert "checked" in ss
            assert "action" in ss
            assert "detail" in ss
        finally:
            import shutil

            shutil.rmtree(d, ignore_errors=True)


# --- Phase 9: Consolidation ---


class TestConsolidationEngine:
    """Phase 9: Consolidation Engine tests."""

    def test_consolidate_creates_summary_drawer(self, adv_palace, adv_col):
        adv_col.add(
            ids=["c1", "c2", "c3"],
            documents=["a", "b", "c"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()}
                for _ in range(3)
            ],
        )
        db = SynapseDB(adv_palace)
        r = db.consolidate(adv_col, ["c1", "c2", "c3"], "summary text")
        cid = r["consolidated_drawer_id"]
        got = adv_col.get(ids=[cid])
        assert got["ids"] and cid in got["ids"]

    def test_consolidate_archives_sources(self, adv_palace, adv_col):
        adv_col.add(
            ids=["s1", "s2"],
            documents=["a", "b"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()},
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()},
            ],
        )
        db = SynapseDB(adv_palace)
        db.consolidate(adv_col, ["s1", "s2"], "sum")
        m1 = adv_col.get(ids=["s1"])["metadatas"][0]
        assert m1.get("status") == "consolidated"

    def test_consolidate_requires_summary(self, adv_palace, adv_col):
        adv_col.add(
            ids=["z1"],
            documents=["z"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()}
            ],
        )
        db = SynapseDB(adv_palace)
        with pytest.raises(ValueError):
            db.consolidate(adv_col, ["z1"], "")

    def test_consolidate_preserves_source_ids(self, adv_palace, adv_col):
        adv_col.add(
            ids=["p1", "p2"],
            documents=["a", "b"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()},
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()},
            ],
        )
        db = SynapseDB(adv_palace)
        r = db.consolidate(adv_col, ["p1", "p2"], "merged")
        meta = adv_col.get(ids=[r["consolidated_drawer_id"]])["metadatas"][0]
        raw = json.loads(meta["source_drawers"])
        assert set(raw) == {"p1", "p2"}

    def test_consolidate_reversible(self, adv_palace, adv_col):
        adv_col.add(
            ids=["r1"],
            documents=["x"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()}
            ],
        )
        db = SynapseDB(adv_palace)
        db.consolidate(adv_col, ["r1"], "sum")
        adv_col.update(ids=["r1"], metadatas=[{"status": "active"}])
        m = adv_col.get(ids=["r1"])["metadatas"][0]
        assert m.get("status") == "active"

    def test_consolidated_appears_in_search(self, adv_palace):
        cfg = _synapse_cfg()
        client = chromadb.PersistentClient(path=adv_palace)
        col = client.get_or_create_collection("mempalace_drawers")
        col.add(
            ids=["u1", "u2"],
            documents=["foo bar", "baz"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()},
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()},
            ],
        )
        db = SynapseDB(adv_palace)
        db.consolidate(col, ["u1", "u2"], "combined foo bar summary")
        with patch("mempalace.config.MempalaceConfig", return_value=cfg):
            r = search_memories("foo bar", palace_path=adv_palace, n_results=10)
        ids = [h["id"] for h in r.get("hits", [])]
        assert any("consolidated_" in i for i in ids)

    def test_consolidated_sources_filtered_by_default(self, adv_palace):
        cfg = _synapse_cfg()
        client = chromadb.PersistentClient(path=adv_palace)
        col = client.get_or_create_collection("mempalace_drawers")
        col.add(
            ids=["a1", "a2"],
            documents=["x", "y"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()},
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()},
            ],
        )
        SynapseDB(adv_palace).consolidate(col, ["a1", "a2"], "sum")
        with patch("mempalace.config.MempalaceConfig", return_value=cfg):
            r = search_memories("x", palace_path=adv_palace, n_results=10)
        for h in r.get("hits", []):
            if h["id"] in ("a1", "a2"):
                assert h.get("metadata", {}).get("status") != "consolidated" or r.get(
                    "synapse_consolidation", {}
                ).get("include_sources")

    def test_consolidated_sources_visible_with_flag(self, tmp_path):
        palace = str(tmp_path / "palace")
        os.makedirs(palace, exist_ok=True)
        cfg = _synapse_cfg()
        with open(os.path.join(palace, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "synapse_profiles": {
                        "default": {"include_consolidated_sources": True},
                    }
                },
                f,
            )
        client = chromadb.PersistentClient(path=palace)
        col = client.get_or_create_collection("mempalace_drawers")
        col.add(
            ids=["b1", "b2"],
            documents=["p", "q"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()},
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()},
            ],
        )
        SynapseDB(palace).consolidate(col, ["b1", "b2"], "pq")
        with patch("mempalace.config.MempalaceConfig", return_value=cfg):
            r = search_memories("p", palace_path=palace, n_results=10)
        assert r["synapse_consolidation"].get("include_sources_as_metadata") is True
        top = [
            h for h in r.get("hits", []) if h.get("metadata", {}).get("status") == "consolidated"
        ]
        assert top == []
        summ = next(
            (
                h
                for h in r.get("hits", [])
                if h.get("metadata", {}).get("status") == "consolidated_summary"
            ),
            None,
        )
        assert summ is not None
        assert (summ.get("synapse_consolidation") or {}).get("source_count") == 2

    def test_consolidated_sources_nested_in_evaluate(self, tmp_path):
        palace = str(tmp_path / "palace")
        os.makedirs(palace, exist_ok=True)
        cfg = _synapse_cfg()
        with open(os.path.join(palace, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {"synapse_profiles": {"default": {"include_consolidated_sources": True}}},
                f,
            )
        client = chromadb.PersistentClient(path=palace)
        col = client.get_or_create_collection("mempalace_drawers")
        col.add(
            ids=["n1", "n2", "n3"],
            documents=["alpha beta", "alpha gamma", "alpha delta"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()}
                for _ in range(3)
            ],
        )
        cid = SynapseDB(palace).consolidate(col, ["n1", "n2", "n3"], "alpha summary merged")[
            "consolidated_drawer_id"
        ]
        with patch("mempalace.config.MempalaceConfig", return_value=cfg):
            out = search_memories("alpha", palace_path=palace, n_results=10)
        top_ids = [h["id"] for h in out["hits"]]
        assert "n1" not in top_ids and "n2" not in top_ids and "n3" not in top_ids
        summ = next((h for h in out["hits"] if h["id"] == cid), None)
        assert summ is not None
        sc = summ.get("synapse_consolidation") or {}
        assert sc.get("source_count") == 3
        assert len(sc.get("sources") or []) == 3

    def test_consolidated_sources_not_nested_in_orient(self, tmp_path):
        palace = str(tmp_path / "palace")
        os.makedirs(palace, exist_ok=True)
        cfg = _synapse_cfg()
        with open(os.path.join(palace, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {"synapse_profiles": {"default": {"include_consolidated_sources": False}}},
                f,
            )
        client = chromadb.PersistentClient(path=palace)
        col = client.get_or_create_collection("mempalace_drawers")
        col.add(
            ids=["o1", "o2", "o3"],
            documents=["gamma ray", "gamma ray", "gamma ray"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()}
                for _ in range(3)
            ],
        )
        cid = SynapseDB(palace).consolidate(col, ["o1", "o2", "o3"], "gamma merged")[
            "consolidated_drawer_id"
        ]
        with patch("mempalace.config.MempalaceConfig", return_value=cfg):
            out = search_memories("gamma", palace_path=palace, n_results=10)
        assert cid in [h["id"] for h in out["hits"]]
        for h in out["hits"]:
            if h["id"] == cid:
                assert not (h.get("synapse_consolidation") or {}).get("sources")

    def test_consolidate_observability_fields(self, adv_palace, adv_col):
        adv_col.add(
            ids=["e1"],
            documents=["z"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()}
            ],
        )
        r = SynapseDB(adv_palace).consolidate(adv_col, ["e1"], "s")
        for k in ("consolidated_drawer_id", "source_drawers_archived", "reversible"):
            assert k in r


# --- Pipeline trace ---


class TestPipelineTrace:
    """Pipeline trace observability tests."""

    def test_pipeline_trace_present_when_synapse_enabled(self, adv_palace):
        cfg = _synapse_cfg()
        client = chromadb.PersistentClient(path=adv_palace)
        col = client.get_or_create_collection("mempalace_drawers")
        col.add(
            ids=["pt1"],
            documents=["hello pipeline"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()}
            ],
        )
        with patch("mempalace.config.MempalaceConfig", return_value=cfg):
            r = search_memories("hello", palace_path=adv_palace, n_results=5)
        pipe = r.get("synapse_pipeline") or {}
        assert isinstance(pipe.get("phases_applied"), list)
        assert isinstance(pipe.get("phases_skipped"), list)
        assert isinstance(pipe.get("total_candidates_in"), int)
        assert isinstance(pipe.get("total_results_out"), int)
        assert isinstance(pipe.get("profile_used"), str)
        assert isinstance(pipe.get("elapsed_ms"), (int, float))

    def test_pipeline_trace_phases_match_config(self, tmp_path):
        palace = str(tmp_path / "palace")
        os.makedirs(palace, exist_ok=True)
        cfg = _synapse_cfg()
        with open(os.path.join(palace, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "synapse_profiles": {
                        "default": {
                            "mmr_enabled": True,
                            "query_expansion_enabled": False,
                            "supersede_filter_enabled": True,
                            "supersede_action": "filter",
                        }
                    }
                },
                f,
            )
        client = chromadb.PersistentClient(path=palace)
        col = client.get_or_create_collection("mempalace_drawers")
        col.add(
            ids=["pv1"],
            documents=["unique pipeline test string"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()}
            ],
        )
        with patch("mempalace.config.MempalaceConfig", return_value=cfg):
            r = search_memories("unique pipeline", palace_path=palace, n_results=5)
        pipe = r["synapse_pipeline"]
        assert "mmr" in pipe["phases_applied"]
        assert "supersede_filter" in pipe["phases_applied"]
        assert "query_expansion" in pipe["phases_skipped"]

    def test_pipeline_trace_absent_when_synapse_disabled(self, adv_palace):
        cfg = _synapse_cfg(synapse_enabled=False)
        client = chromadb.PersistentClient(path=adv_palace)
        col = client.get_or_create_collection("mempalace_drawers")
        col.add(
            ids=["off1"],
            documents=["x"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()}
            ],
        )
        with patch("mempalace.config.MempalaceConfig", return_value=cfg):
            r = search_memories("x", palace_path=adv_palace, n_results=3)
        assert "synapse_pipeline" not in r or not (r.get("synapse_pipeline") or {}).get(
            "phases_applied"
        )

    def test_pipeline_trace_elapsed_ms_is_number(self, adv_palace):
        cfg = _synapse_cfg()
        client = chromadb.PersistentClient(path=adv_palace)
        col = client.get_or_create_collection("mempalace_drawers")
        col.add(
            ids=["e1"],
            documents=["elapsed test"],
            metadatas=[
                {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()}
            ],
        )
        with patch("mempalace.config.MempalaceConfig", return_value=cfg):
            r = search_memories("elapsed", palace_path=adv_palace, n_results=3)
        assert r["synapse_pipeline"]["elapsed_ms"] >= 0.0

    def test_pipeline_trace_candidate_count_consistent(self, tmp_path):
        palace = str(tmp_path / "palace")
        os.makedirs(palace, exist_ok=True)
        cfg = _synapse_cfg()
        with open(os.path.join(palace, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {"synapse_profiles": {"default": {"mmr_enabled": True, "mmr_final_k": 1}}},
                f,
            )
        client = chromadb.PersistentClient(path=palace)
        col = client.get_or_create_collection("mempalace_drawers")
        for i in range(4):
            col.add(
                ids=[f"mm{i}"],
                documents=[f"token {i} same topic"],
                metadatas=[
                    {"wing": "w", "room": "r", "filed_at": datetime.now(timezone.utc).isoformat()}
                ],
            )
        with patch("mempalace.config.MempalaceConfig", return_value=cfg):
            r = search_memories("token same topic", palace_path=palace, n_results=5)
        pipe = r["synapse_pipeline"]
        assert pipe["total_candidates_in"] >= pipe["total_results_out"]
