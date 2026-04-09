"""Tests for time-decay scoring feature (#331)."""

from datetime import datetime, timezone, timedelta

import pytest

from mempalace.searcher import _apply_time_decay


class TestApplyTimeDecay:
    """Test the _apply_time_decay helper function."""

    def _make_hit(self, similarity, days_ago):
        """Create a hit dict with filed_at set to days_ago days in the past."""
        filed_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
        return {
            "text": f"content from {days_ago} days ago",
            "wing": "test",
            "room": "test",
            "source_file": "test.md",
            "similarity": similarity,
            "filed_at": filed_at.isoformat(),
        }

    def test_recent_beats_old_when_similarity_close(self):
        """A recent hit with slightly lower similarity should outrank an older hit."""
        hits = [
            self._make_hit(0.85, days_ago=180),  # old, higher similarity
            self._make_hit(0.82, days_ago=1),     # recent, lower similarity
        ]
        result = _apply_time_decay(hits, half_life_days=90)
        assert result[0]["text"] == "content from 1 days ago"

    def test_half_life_halves_score_at_exact_half_life(self):
        """At exactly half_life_days, decay should be ~0.5."""
        hits = [self._make_hit(1.0, days_ago=90)]
        result = _apply_time_decay(hits, half_life_days=90)
        assert abs(result[0]["decay"] - 0.5) < 0.01

    def test_zero_age_no_decay(self):
        """A hit from today should have decay ~1.0."""
        hits = [self._make_hit(0.9, days_ago=0)]
        result = _apply_time_decay(hits, half_life_days=90)
        assert result[0]["decay"] >= 0.99

    def test_disabled_when_half_life_zero(self):
        """half_life_days=0 should skip decay entirely."""
        hits = [
            self._make_hit(0.85, days_ago=180),
            self._make_hit(0.82, days_ago=1),
        ]
        result = _apply_time_decay(hits, half_life_days=0)
        # Original order preserved, no decay field added
        assert result[0]["similarity"] == 0.85
        assert "decay" not in result[0]

    def test_disabled_when_half_life_negative(self):
        """Negative half_life_days should skip decay."""
        hits = [self._make_hit(0.9, days_ago=30)]
        result = _apply_time_decay(hits, half_life_days=-1)
        assert result[0]["similarity"] == 0.9
        assert "decay" not in result[0]

    def test_preserves_original_similarity(self):
        """Original similarity should be saved in original_similarity field."""
        hits = [self._make_hit(0.9, days_ago=90)]
        result = _apply_time_decay(hits, half_life_days=90)
        assert result[0]["original_similarity"] == 0.9
        assert result[0]["similarity"] < 0.9

    def test_missing_filed_at_gets_zero_decay(self):
        """Hits without filed_at should get age=0 (no penalty)."""
        hits = [{
            "text": "no timestamp",
            "wing": "test",
            "room": "test",
            "source_file": "test.md",
            "similarity": 0.8,
            "filed_at": "",
        }]
        result = _apply_time_decay(hits, half_life_days=90)
        assert result[0]["decay"] >= 0.99

    def test_invalid_filed_at_gets_zero_decay(self):
        """Hits with invalid filed_at should get age=0 (no penalty)."""
        hits = [{
            "text": "bad timestamp",
            "wing": "test",
            "room": "test",
            "source_file": "test.md",
            "similarity": 0.8,
            "filed_at": "not-a-date",
        }]
        result = _apply_time_decay(hits, half_life_days=90)
        assert result[0]["decay"] >= 0.99

    def test_sort_order_after_decay(self):
        """Results should be sorted by decayed similarity, descending."""
        hits = [
            self._make_hit(0.95, days_ago=365),  # very old
            self._make_hit(0.70, days_ago=1),     # recent but low similarity
            self._make_hit(0.85, days_ago=30),    # middle
        ]
        result = _apply_time_decay(hits, half_life_days=90)
        scores = [h["similarity"] for h in result]
        assert scores == sorted(scores, reverse=True)

    def test_empty_hits(self):
        """Empty list should return empty list."""
        result = _apply_time_decay([], half_life_days=90)
        assert result == []
