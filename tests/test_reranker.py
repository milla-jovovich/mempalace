"""
test_reranker.py — Tests for the Weibull decay and rerank pipeline.

Tests cover:
  - Weibull survival function math
  - Keyword extraction and overlap
  - Individual rerank stages
  - Pipeline composition and backward compatibility
"""

import math
from datetime import datetime, timedelta


from mempalace.reranker import (
    weibull_survival,
    apply_decay,
    _parse_age_days,
    extract_keywords,
    keyword_overlap,
    stage_weibull_decay,
    stage_keyword_boost,
    stage_importance_boost,
    rerank,
)


# ---------------------------------------------------------------------------
# Weibull survival function
# ---------------------------------------------------------------------------


class TestWeibullSurvival:
    def test_at_zero(self):
        """S(0) = 1.0 — brand new memory has full weight."""
        assert weibull_survival(0) == 1.0

    def test_at_lambda(self):
        """S(lambda) = exp(-1) ≈ 0.368 for any k."""
        result = weibull_survival(90, k=1.5, lam=90)
        expected = math.exp(-1)
        assert abs(result - expected) < 1e-10

    def test_very_old(self):
        """Very old memories approach 0."""
        result = weibull_survival(1000, k=1.5, lam=90)
        assert result < 0.001

    def test_negative_age(self):
        """Negative age returns 1.0 (treat as brand new)."""
        assert weibull_survival(-5) == 1.0

    def test_k_equals_one_is_exponential(self):
        """k=1 gives pure exponential decay."""
        result = weibull_survival(45, k=1.0, lam=90)
        expected = math.exp(-0.5)
        assert abs(result - expected) < 1e-10

    def test_higher_k_decays_faster_late(self):
        """Higher k means steeper decay for old memories."""
        s_low_k = weibull_survival(180, k=1.0, lam=90)
        s_high_k = weibull_survival(180, k=2.0, lam=90)
        assert s_high_k < s_low_k

    def test_zero_lambda_returns_one(self):
        """Lambda <= 0 should not crash."""
        assert weibull_survival(10, k=1.5, lam=0) == 1.0


class TestApplyDecay:
    def test_new_memory_full_score(self):
        """Brand new memory keeps full similarity."""
        result = apply_decay(0.9, age_days=0, k=1.5, lam=90, floor=0.3)
        assert result == 0.9

    def test_floor_guarantee(self):
        """Very old memory never drops below similarity * floor."""
        result = apply_decay(0.9, age_days=10000, k=1.5, lam=90, floor=0.3)
        assert result >= 0.9 * 0.3 - 1e-10

    def test_mid_age_decay(self):
        """90-day-old memory with default params."""
        result = apply_decay(1.0, age_days=90, k=1.5, lam=90, floor=0.3)
        # S(90) = exp(-1) ≈ 0.368
        # adjusted = 1.0 * (0.3 + 0.7 * 0.368) = 0.558
        assert 0.5 < result < 0.6


class TestParseAgeDays:
    def test_valid_iso_timestamp(self):
        ts = (datetime.now() - timedelta(days=10)).isoformat()
        age = _parse_age_days(ts)
        assert 9.9 < age < 10.1

    def test_none_returns_zero(self):
        assert _parse_age_days(None) == 0.0

    def test_empty_string_returns_zero(self):
        assert _parse_age_days("") == 0.0

    def test_invalid_string_returns_zero(self):
        assert _parse_age_days("not-a-date") == 0.0

    def test_future_date_returns_zero(self):
        ts = (datetime.now() + timedelta(days=5)).isoformat()
        assert _parse_age_days(ts) == 0.0


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------


class TestKeywordExtraction:
    def test_basic_extraction(self):
        kws = extract_keywords("What degree did I graduate with?")
        assert "degree" in kws
        assert "graduate" in kws
        # Stop words removed
        assert "what" not in kws
        assert "did" not in kws

    def test_short_words_excluded(self):
        """Words under 3 chars are excluded; stop words are excluded."""
        kws = extract_keywords("go to the big red car")
        assert "go" not in kws  # only 2 chars
        assert "to" not in kws  # only 2 chars
        assert "the" not in kws  # stop word
        assert "big" in kws  # 3+ chars, not a stop word
        assert "red" in kws
        assert "car" in kws

    def test_empty_input(self):
        assert extract_keywords("") == []


class TestKeywordOverlap:
    def test_full_overlap(self):
        kws = ["database", "migration"]
        doc = "The database migration was successful."
        assert keyword_overlap(kws, doc) == 1.0

    def test_no_overlap(self):
        kws = ["yoga", "meditation"]
        doc = "The car engine needs repair."
        assert keyword_overlap(kws, doc) == 0.0

    def test_partial_overlap(self):
        kws = ["database", "yoga", "chess"]
        doc = "The database query was slow."
        assert abs(keyword_overlap(kws, doc) - 1 / 3) < 0.01

    def test_empty_keywords(self):
        assert keyword_overlap([], "some document text") == 0.0


# ---------------------------------------------------------------------------
# Rerank stages
# ---------------------------------------------------------------------------


def _make_hits(ages_days=None, texts=None, weights=None):
    """Create test hit dicts with optional ages, texts, and emotional_weights."""
    n = max(len(ages_days or [1]), len(texts or ["x"]), len(weights or [None]))
    ages = ages_days or [0] * n
    txts = texts or ["test content"] * n
    wts = weights or [None] * n

    hits = []
    for i in range(n):
        filed_at = None
        if ages[i] > 0:
            filed_at = (datetime.now() - timedelta(days=ages[i])).isoformat()
        hits.append(
            {
                "drawer_id": f"drawer_{i}",
                "text": txts[i] if i < len(txts) else "test",
                "wing": "test",
                "room": "test",
                "source_file": "test.py",
                "similarity": round(0.8 - i * 0.05, 3),
                "distance": round(0.2 + i * 0.05, 4),
                "fused_distance": round(0.2 + i * 0.05, 4),
                "filed_at": filed_at,
                "emotional_weight": wts[i] if i < len(wts) else None,
            }
        )
    return hits


class TestStageWeibullDecay:
    def test_newer_ranked_higher(self):
        """Newer hit with same base distance should rank higher after decay."""
        hits = _make_hits(ages_days=[1, 180])
        # Give them equal base distance
        for h in hits:
            h["distance"] = 0.3
            h["fused_distance"] = 0.3

        config = {"weibull_decay": {"enabled": True, "k": 1.5, "lambda": 90, "floor": 0.3}}
        result = stage_weibull_decay(hits, "test query", config)

        # Newer (age=1) should have lower fused_distance than older (age=180)
        assert result[0]["fused_distance"] < result[1]["fused_distance"]

    def test_no_filed_at_unchanged(self):
        """Hits without filed_at should not be penalized."""
        hits = _make_hits(ages_days=[0])
        hits[0]["filed_at"] = None
        original_dist = hits[0]["fused_distance"]

        config = {"weibull_decay": {"enabled": True}}
        stage_weibull_decay(hits, "test", config)

        assert hits[0]["fused_distance"] == original_dist


class TestStageKeywordBoost:
    def test_keyword_match_boosts(self):
        """Hit with keyword overlap should get lower fused_distance."""
        hits = _make_hits(
            texts=[
                "JWT authentication tokens and session cookies",
                "The weather is sunny today with blue skies",
            ]
        )
        for h in hits:
            h["fused_distance"] = 0.4

        config = {"keyword_boost": {"enabled": True, "weight": 0.30}}
        stage_keyword_boost(hits, "JWT authentication security", config)

        # First hit has keyword overlap, should have lower fused_distance
        assert hits[0]["fused_distance"] < hits[1]["fused_distance"]

    def test_no_keywords_noop(self):
        """Query with only stop words should not change distances."""
        hits = _make_hits(texts=["some document"])
        original = hits[0]["fused_distance"]

        config = {"keyword_boost": {"enabled": True, "weight": 0.30}}
        stage_keyword_boost(hits, "the a an", config)

        assert hits[0]["fused_distance"] == original


class TestStageImportanceBoost:
    def test_high_weight_boosted(self):
        """Hit with high emotional_weight should get lower fused_distance."""
        hits = _make_hits(weights=[4.5, None])
        for h in hits:
            h["fused_distance"] = 0.4

        config = {"importance_boost": {"enabled": True, "weight": 0.15}}
        stage_importance_boost(hits, "test", config)

        assert hits[0]["fused_distance"] < hits[1]["fused_distance"]

    def test_no_weight_unchanged(self):
        """Hit without emotional_weight should not change."""
        hits = _make_hits(weights=[None])
        original = hits[0]["fused_distance"]

        config = {"importance_boost": {"enabled": True, "weight": 0.15}}
        stage_importance_boost(hits, "test", config)

        assert hits[0]["fused_distance"] == original


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class TestRerankPipeline:
    def test_empty_config_is_identity(self):
        """No config = no changes."""
        hits = _make_hits(ages_days=[1, 30, 90])
        original_order = [h["drawer_id"] for h in hits]

        result = rerank(hits, "test query", {})

        assert [h["drawer_id"] for h in result] == original_order

    def test_none_config_is_identity(self):
        """None config = no changes."""
        hits = _make_hits(ages_days=[1])
        result = rerank(hits, "test", None)
        assert result == hits

    def test_empty_hits_is_identity(self):
        """Empty hit list returns empty."""
        assert rerank([], "test", {"weibull_decay": {"enabled": True}}) == []

    def test_all_disabled_is_identity(self):
        """All stages explicitly disabled = no changes."""
        config = {
            "weibull_decay": {"enabled": False},
            "keyword_boost": {"enabled": False},
        }
        hits = _make_hits(ages_days=[1, 30])
        original_order = [h["drawer_id"] for h in hits]

        result = rerank(hits, "test", config)

        assert [h["drawer_id"] for h in result] == original_order

    def test_decay_reorders_by_age(self):
        """With only decay enabled, newer memories should rank higher."""
        # Create hits where the older one has better base distance
        hits = [
            {
                "drawer_id": "old",
                "text": "old content",
                "distance": 0.1,
                "similarity": 0.9,
                "filed_at": (datetime.now() - timedelta(days=365)).isoformat(),
                "emotional_weight": None,
            },
            {
                "drawer_id": "new",
                "text": "new content",
                "distance": 0.2,
                "similarity": 0.8,
                "filed_at": (datetime.now() - timedelta(days=1)).isoformat(),
                "emotional_weight": None,
            },
        ]

        config = {
            "weibull_decay": {"enabled": True, "k": 1.5, "lambda": 90, "floor": 0.3},
        }
        result = rerank(hits, "test", config)

        # The new hit (dist 0.2) should now rank above old hit (dist 0.1)
        # because the old hit's distance gets inflated by decay
        assert result[0]["drawer_id"] == "new"

    def test_adjusted_similarity_present(self):
        """Reranked hits should have adjusted_similarity field."""
        hits = _make_hits(ages_days=[1, 30])
        config = {"weibull_decay": {"enabled": True}}

        result = rerank(hits, "test", config)

        for hit in result:
            assert "adjusted_similarity" in hit
            assert "fused_distance" in hit

    def test_stages_compose(self):
        """Multiple stages should all apply."""
        hits = _make_hits(
            ages_days=[1, 180],
            texts=["JWT authentication tokens", "weather forecast sunny"],
            weights=[4.0, None],
        )
        # Give them equal base distance
        for h in hits:
            h["distance"] = 0.4
            h["similarity"] = 0.6

        config = {
            "weibull_decay": {"enabled": True, "k": 1.5, "lambda": 90, "floor": 0.3},
            "keyword_boost": {"enabled": True, "weight": 0.30},
            "importance_boost": {"enabled": True, "weight": 0.15},
        }
        result = rerank(hits, "JWT authentication", config)

        # First hit (newer, keyword match, high weight) should clearly win
        assert result[0]["drawer_id"] == "drawer_0"

    def test_llm_rerank_skipped_without_key(self):
        """LLM rerank should gracefully skip when no API key is set."""
        import os

        old_key = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            hits = _make_hits(ages_days=[1, 30])
            config = {"llm_rerank": {"enabled": True}}

            result = rerank(hits, "test", config)

            # Should return hits unchanged (no crash)
            assert len(result) == 2
        finally:
            if old_key:
                os.environ["ANTHROPIC_API_KEY"] = old_key


# ---------------------------------------------------------------------------
# Integration with search_memories
# ---------------------------------------------------------------------------


class TestSearchMemoriesRerank:
    def test_rerank_false_no_rerank_field(self, palace_path, seeded_collection):
        """search_memories with rerank=False should not add reranked flag."""
        from mempalace.searcher import search_memories

        result = search_memories("JWT", palace_path, rerank=False)
        assert "reranked" not in result

    def test_rerank_true_no_config_same_as_false(self, palace_path, seeded_collection):
        """rerank=True with no config should behave like rerank=False."""
        from mempalace.searcher import search_memories

        result_on = search_memories("JWT", palace_path, rerank=True)
        result_off = search_memories("JWT", palace_path, rerank=False)

        # Both should return same number of results
        assert len(result_on["results"]) == len(result_off["results"])

    def test_result_has_filed_at(self, palace_path, seeded_collection):
        """Hit dicts should include filed_at metadata for reranker access."""
        from mempalace.searcher import search_memories

        result = search_memories("JWT", palace_path)
        for hit in result["results"]:
            assert "filed_at" in hit
