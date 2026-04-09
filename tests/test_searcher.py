"""
test_searcher.py — Tests for the programmatic search_memories API.

Tests the library-facing search interface (not the CLI print variant).
"""

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

    def test_min_similarity_filters_low_scores(self, palace_path, seeded_collection):
        # A very high threshold should return fewer (or zero) results than no threshold.
        result_all = search_memories("authentication", palace_path, n_results=5)
        result_high = search_memories("authentication", palace_path, n_results=5, min_similarity=0.9999)
        assert len(result_high["results"]) <= len(result_all["results"])

    def test_min_similarity_zero_returns_all(self, palace_path, seeded_collection):
        result = search_memories("authentication", palace_path, n_results=5, min_similarity=0.0)
        assert len(result["results"]) > 0

    def test_min_similarity_respected_on_results(self, palace_path, seeded_collection):
        result = search_memories("authentication", palace_path, n_results=10, min_similarity=0.3)
        for hit in result["results"]:
            assert hit["similarity"] >= 0.3
