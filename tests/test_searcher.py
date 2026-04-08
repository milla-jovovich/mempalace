"""
test_searcher.py — Tests for the programmatic search_memories API.

Tests the library-facing search interface (not the CLI print variant).
"""

from mempalace.searcher import search, search_memories


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

    def test_no_palace_returns_error(self):
        result = search_memories("anything", "/nonexistent/path")
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

    def test_handles_empty_query_payload(self, monkeypatch):
        class _FakeCollection:
            def query(self, **_kwargs):
                return {"documents": [], "metadatas": [], "distances": []}

        class _FakeClient:
            def __init__(self, path):
                self.path = path

            def get_collection(self, _name):
                return _FakeCollection()

        monkeypatch.setattr(
            "mempalace.searcher.chromadb.PersistentClient",
            _FakeClient,
        )

        result = search_memories("anything", "/tmp/fake-palace")
        assert result["results"] == []

    def test_cli_search_handles_empty_query_payload(self, monkeypatch, capsys):
        class _FakeCollection:
            def query(self, **_kwargs):
                return {"documents": [], "metadatas": [], "distances": []}

        class _FakeClient:
            def __init__(self, path):
                self.path = path

            def get_collection(self, _name):
                return _FakeCollection()

        monkeypatch.setattr(
            "mempalace.searcher.chromadb.PersistentClient",
            _FakeClient,
        )

        search("anything", "/tmp/fake-palace")
        out = capsys.readouterr().out
        assert 'No results found for: "anything"' in out
