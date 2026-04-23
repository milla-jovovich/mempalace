"""Tests for the hybrid closet+drawer retrieval in search_memories.

The hybrid path queries drawers directly (the floor) AND closets, applying a
rank-based boost to drawers whose source_file appears in top closet hits.
This avoids the "weak-closets regression" where low-signal closets (from
regex extraction on narrative content) could hide drawers that direct
search would have found.
"""

from mempalace.palace import (
    get_closets_collection,
    get_collection,
    upsert_closet_lines,
)
from mempalace.searcher import search_memories


def _seed_drawers(palace_path):
    """Insert 4 short drawers with deterministic content."""
    col = get_collection(palace_path, create=True)
    col.upsert(
        ids=["D1", "D2", "D3", "D4"],
        documents=[
            "We switched the auth service to use JWT tokens with a 24h expiry.",
            "Database migration to PostgreSQL 15 completed last Tuesday.",
            "The frontend team is debating whether to adopt TanStack Query.",
            "Kafka consumer rebalance timeout set to 45 seconds after incident.",
        ],
        metadatas=[
            {"wing": "backend", "room": "auth", "source_file": "fixture_D1.md"},
            {"wing": "backend", "room": "db", "source_file": "fixture_D2.md"},
            {"wing": "frontend", "room": "state", "source_file": "fixture_D3.md"},
            {"wing": "backend", "room": "queue", "source_file": "fixture_D4.md"},
        ],
    )


def _seed_strong_closet_for(palace_path, drawer_id, source_file, topics):
    """Insert a closet whose content strongly overlaps the query keywords."""
    col = get_closets_collection(palace_path)
    lines = [f"{t}||→{drawer_id}" for t in topics]
    upsert_closet_lines(
        col,
        closet_id_base=f"closet_{drawer_id}",
        lines=lines,
        metadata={
            "wing": "backend",
            "room": "auth",
            "source_file": source_file,
            "generated_by": "test",
        },
    )


# ── core invariant: closets can only HELP, never HIDE ─────────────────────


class TestHybridInvariant:
    def test_no_closets_degrades_to_direct_drawer_search(self, tmp_path):
        palace = str(tmp_path / "palace")
        _seed_drawers(palace)
        # No closets created.
        result = search_memories("Kafka rebalance timeout", palace, n_results=3)
        ids = [h["source_file"] for h in result["results"]]
        assert ids, "should return results"
        assert "fixture_D4.md" in ids, "direct drawer search alone should surface the Kafka drawer"

    def test_weak_closets_do_not_hide_direct_drawer_hits(self, tmp_path):
        """A closet that points at a wrong drawer must NOT suppress the
        drawer that direct search would have ranked first."""
        palace = str(tmp_path / "palace")
        _seed_drawers(palace)
        # Seed a misleading closet: it matches a generic phrase but points at D3.
        _seed_strong_closet_for(
            palace,
            drawer_id="D3",
            source_file="fixture_D3.md",
            topics=["Kafka queue tuning", "consumer rebalance config"],
        )
        result = search_memories("Kafka consumer rebalance timeout", palace, n_results=5)
        ids = [h["source_file"] for h in result["results"]]
        assert "fixture_D4.md" in ids, (
            "D4 must appear — direct drawer search alone would rank it first. "
            "Closet pointing to D3 should only boost D3, never hide D4."
        )

    def test_closet_boost_lifts_matching_drawer(self, tmp_path):
        """When a closet agrees with direct search, the matching drawer
        should be boosted to rank 1."""
        palace = str(tmp_path / "palace")
        _seed_drawers(palace)
        _seed_strong_closet_for(
            palace,
            drawer_id="D1",
            source_file="fixture_D1.md",
            topics=["JWT auth tokens", "session expiry", "authentication service"],
        )
        result = search_memories("JWT auth tokens expiry", palace, n_results=3)
        ids = [h["source_file"] for h in result["results"]]
        assert ids[0] == "fixture_D1.md"
        top = result["results"][0]
        assert top["matched_via"] == "drawer+closet"
        assert top["closet_boost"] > 0


# ── closet_boost metadata ────────────────────────────────────────────────


class TestClosetMetadata:
    def test_closet_preview_exposed_when_boosted(self, tmp_path):
        palace = str(tmp_path / "palace")
        _seed_drawers(palace)
        _seed_strong_closet_for(
            palace,
            drawer_id="D1",
            source_file="fixture_D1.md",
            topics=["JWT auth tokens", "24h expiry", "authentication"],
        )
        result = search_memories("JWT authentication", palace, n_results=2)
        top = result["results"][0]
        assert top["source_file"] == "fixture_D1.md"
        assert "closet_preview" in top

    def test_drawer_only_hits_have_no_closet_preview(self, tmp_path):
        palace = str(tmp_path / "palace")
        _seed_drawers(palace)
        # No closets
        result = search_memories("TanStack Query", palace, n_results=2)
        assert result["results"]
        for h in result["results"]:
            assert h["matched_via"] == "drawer"
            assert "closet_preview" not in h
            assert h["closet_boost"] == 0.0


# ── observability: _debug flag + final-sort invariant (Phase 5 / V1) ─────────


class TestDebugMode:
    """Guards the public contract of ``search_memories(..., _debug=...)``.

    This flag is the operator-facing hook for diagnosing ranking anomalies.
    If the keys or timings go missing, tuning work downstream breaks silently.
    """

    def test_debug_false_is_clean(self, tmp_path):
        palace = str(tmp_path / "palace")
        _seed_drawers(palace)
        result = search_memories("JWT", palace, n_results=3)
        # Internal keys and timings must not leak into non-debug responses.
        assert "timings" not in result
        for h in result["results"]:
            assert "_sort_key" not in h
            assert "_drawer_rank" not in h
            assert "_source_file_full" not in h
            assert "_chunk_index" not in h

    def test_debug_true_preserves_keys_and_timings(self, tmp_path):
        palace = str(tmp_path / "palace")
        _seed_drawers(palace)
        result = search_memories("JWT", palace, n_results=3, _debug=True)
        assert "timings" in result, "debug response must include the timings block"
        for key in ("drawer_query_ms", "hydrate_ms", "hybrid_rerank_ms", "total_ms"):
            assert key in result["timings"], f"missing timing key {key!r}"
            assert isinstance(result["timings"][key], (int, float))
            assert result["timings"][key] >= 0
        assert result["results"], "expected at least one hit"
        for h in result["results"]:
            assert "_sort_key" in h
            assert "_drawer_rank" in h
            assert isinstance(h["_drawer_rank"], int)
            # _source_file_full / _chunk_index are still stripped in debug — they
            # are implementation plumbing, not ranking signals.
            assert "_source_file_full" not in h
            assert "_chunk_index" not in h

    def test_timings_include_closet_when_closets_exist(self, tmp_path):
        palace = str(tmp_path / "palace")
        _seed_drawers(palace)
        _seed_strong_closet_for(
            palace,
            drawer_id="D1",
            source_file="fixture_D1.md",
            topics=["JWT auth", "token expiry"],
        )
        result = search_memories("JWT", palace, n_results=3, _debug=True)
        assert "closet_query_ms" in result["timings"]


class TestFinalSortInvariant:
    """Regression guard for V1 (search ordering anomaly documented during
    verification). The final order is Stage 2 — ``_hybrid_rank``'s convex
    combination of vector similarity and min-max-normalised BM25 — not the
    Stage 1 ``effective_distance`` ascending order.

    If someone swaps the two stages or drops ``_hybrid_rank``, this test fails.
    """

    @staticmethod
    def _expected_hybrid_scores(hits, vector_weight=0.6, bm25_weight=0.4):
        """Re-derive the hybrid score from the hit dicts using the same
        formula as ``_hybrid_rank``. Returns a list aligned with ``hits``.
        """
        bm25_raws = [h.get("bm25_score", 0.0) for h in hits]
        max_bm25 = max(bm25_raws) if bm25_raws else 0.0
        bm25_norm = (
            [s / max_bm25 for s in bm25_raws] if max_bm25 > 0 else [0.0] * len(bm25_raws)
        )
        scores = []
        for h, norm in zip(hits, bm25_norm):
            vec_sim = max(0.0, 1.0 - h.get("distance", 1.0))
            scores.append(vector_weight * vec_sim + bm25_weight * norm)
        return scores

    def test_final_order_matches_hybrid_rank_not_effective_distance(self, tmp_path):
        palace = str(tmp_path / "palace")
        _seed_drawers(palace)
        # Include a closet so the two stages can diverge.
        _seed_strong_closet_for(
            palace,
            drawer_id="D3",
            source_file="fixture_D3.md",
            topics=["database migration tooling", "schema upgrades"],
        )
        result = search_memories(
            "database migration PostgreSQL schema", palace, n_results=4, _debug=True
        )
        hits = result["results"]
        assert len(hits) >= 2, "need at least 2 hits to check ordering"

        scores = self._expected_hybrid_scores(hits)
        # Assert the returned order is non-increasing in the reconstructed
        # hybrid score — i.e. ``_hybrid_rank`` was the last ranking step.
        for a, b in zip(scores, scores[1:]):
            assert a + 1e-9 >= b, (
                "final results must be sorted descending by hybrid "
                "(0.6*vec_sim + 0.4*bm25_norm); drift here means Stage 2 "
                "(_hybrid_rank) was skipped or a third sort sneaked in "
                f"after it. Got scores: {scores}"
            )

    def test_effective_distance_is_not_guaranteed_monotonic(self, tmp_path):
        """Documents V1 as design: when hybrid rerank kicks in, the output
        order is allowed to diverge from ``effective_distance`` ascending.
        This test is informational — it simply confirms the old intuition
        ("must be sorted by effective_distance") is not a load-bearing
        invariant, so future readers don't re-file V1.
        """
        palace = str(tmp_path / "palace")
        _seed_drawers(palace)
        _seed_strong_closet_for(
            palace,
            drawer_id="D3",
            source_file="fixture_D3.md",
            topics=["database migration tooling", "schema upgrades"],
        )
        result = search_memories(
            "database migration PostgreSQL schema", palace, n_results=4
        )
        effs = [h["effective_distance"] for h in result["results"]]
        # Not an assertion that effs are unsorted — on a particular corpus
        # they might coincide with the hybrid order. The guarantee we make
        # is the *other* one (hybrid in TestFinalSortInvariant above).
        # Here we just assert the field is still present for observability.
        assert all(isinstance(e, float) for e in effs)
