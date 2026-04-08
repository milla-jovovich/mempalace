"""
test_searcher.py — Tests for the programmatic search_memories API.

Tests the library-facing search interface (not the CLI print variant).
"""

from unittest.mock import MagicMock

from mempalace.layers import Layer3
from mempalace.searcher import search_memories


class TestSearchMemories:
    def test_basic_search(self, palace_path, seeded_collection):
        result = search_memories("JWT authentication", palace_path)
        assert "results" in result
        assert len(result["results"]) > 0
        assert result["query"] == "JWT authentication"

    def test_wing_filter(self, palace_path, seeded_collection):
        result = search_memories("planning", palace_path, wing="notes")
        assert all(r["wing"] == "notes" for r in result["results"])

    def test_room_filter(self, palace_path, seeded_collection):
        result = search_memories("database", palace_path, room="backend")
        assert all(r["room"] == "backend" for r in result["results"])

    def test_wing_and_room_filter(self, palace_path, seeded_collection):
        result = search_memories("code", palace_path, wing="project", room="frontend")
        assert all(r["wing"] == "project" and r["room"] == "frontend" for r in result["results"])

    def test_n_results_limit(self, palace_path, seeded_collection):
        result = search_memories("code", palace_path, n_results=2)
        assert len(result["results"]) <= 2

    def test_no_palace_returns_error(self, tmp_path):
        result = search_memories("anything", str(tmp_path / "missing"))
        assert "error" in result

    def test_result_fields(self, palace_path, seeded_collection):
        result = search_memories("authentication", palace_path)
        hit = result["results"][0]
        assert "text" in hit
        assert "wing" in hit
        assert "room" in hit
        assert "source_file" in hit
        assert "similarity" in hit
        assert isinstance(hit["similarity"], float)


# Issue #195 — ChromaDB 1.x may return {documents: []} (no outer wrapper).
# Pre-fix code did `results["documents"][0]` and crashed with IndexError.
# These tests inject the buggy shape via mock to exercise the guard.

_EMPTY_OUTER = {"ids": [], "documents": [], "metadatas": [], "distances": []}


def _mock_empty_chromadb(monkeypatch, module):
    fake_col = MagicMock()
    fake_col.query.return_value = _EMPTY_OUTER
    fake_client = MagicMock()
    fake_client.get_collection.return_value = fake_col
    monkeypatch.setattr(
        f"{module}.chromadb.PersistentClient", lambda path: fake_client
    )


def test_search_memories_handles_empty_outer_list(monkeypatch, tmp_path):
    """Issue #195: ChromaDB 1.x empty-outer shape must not crash."""
    _mock_empty_chromadb(monkeypatch, "mempalace.searcher")
    result = search_memories("anything", str(tmp_path))
    assert result["results"] == []


def test_layer3_search_raw_handles_empty_outer_list(monkeypatch, tmp_path):
    """Issue #195: Layer3 also affected by the empty-outer shape."""
    _mock_empty_chromadb(monkeypatch, "mempalace.layers")
    result = Layer3(palace_path=str(tmp_path)).search_raw("anything")
    assert result == []
