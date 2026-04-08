"""
test_searcher.py — Tests for the programmatic search_memories API.

Tests the library-facing search interface (not the CLI print variant).
"""

from mempalace.searcher import CHAT_SOURCE_MARKER, FETCH_MULTIPLIER, search_memories


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

    def test_filters_non_transcript_sources(self, monkeypatch):
        class FakeCollection:
            def query(self, **kwargs):
                return {
                    "documents": [["good hit", "bad hit"]],
                    "metadatas": [
                        [
                            {
                                "wing": "cursor",
                                "room": "technical",
                                "source_file": "/tmp/agent-transcripts/abc.jsonl",
                            },
                            {
                                "wing": "cursor",
                                "room": "technical",
                                "source_file": "/tmp/notes/manual.md",
                            },
                        ]
                    ],
                    "distances": [[0.2, 0.05]],
                }

        class FakeClient:
            def get_collection(self, _name):
                return FakeCollection()

        monkeypatch.setattr("mempalace.searcher.chromadb.PersistentClient", lambda path: FakeClient())

        result = search_memories("query", "/tmp/palace", cursor_source_filter=True)
        assert len(result["results"]) == 1
        assert result["results"][0]["text"] == "good hit"

    def test_filters_subagent_and_low_similarity_and_duplicates(self, monkeypatch):
        repeated = "same chunk"

        class FakeCollection:
            def query(self, **kwargs):
                return {
                    "documents": [[repeated, repeated, "subagent", "too weak", "valid"]],
                    "metadatas": [
                        [
                            {
                                "wing": "cursor",
                                "room": "technical",
                                "source_file": "/tmp/agent-transcripts/a.jsonl",
                            },
                            {
                                "wing": "cursor",
                                "room": "technical",
                                "source_file": "/tmp/agent-transcripts/b.jsonl",
                            },
                            {
                                "wing": "cursor",
                                "room": "technical",
                                "source_file": "/tmp/agent-transcripts/subagents/c.jsonl",
                            },
                            {
                                "wing": "cursor",
                                "room": "technical",
                                "source_file": "/tmp/agent-transcripts/d.jsonl",
                            },
                            {
                                "wing": "cursor",
                                "room": "technical",
                                "source_file": "/tmp/agent-transcripts/e.jsonl",
                            },
                        ]
                    ],
                    "distances": [[0.1, 0.1, 0.1, 0.95, 0.2]],
                }

        class FakeClient:
            def get_collection(self, _name):
                return FakeCollection()

        monkeypatch.setattr("mempalace.searcher.chromadb.PersistentClient", lambda path: FakeClient())

        result = search_memories("query", "/tmp/palace", n_results=5, cursor_source_filter=True)
        texts = [hit["text"] for hit in result["results"]]
        assert texts == [repeated, "valid"]

    def test_expands_query_candidates_for_post_filtering(self, monkeypatch):
        captured = {}

        class FakeCollection:
            def query(self, **kwargs):
                captured.update(kwargs)
                return {"documents": [[]], "metadatas": [[]], "distances": [[]]}

        class FakeClient:
            def get_collection(self, _name):
                return FakeCollection()

        monkeypatch.setattr("mempalace.searcher.chromadb.PersistentClient", lambda path: FakeClient())

        search_memories("query", "/tmp/palace", n_results=3, cursor_source_filter=True)
        assert captured["n_results"] == 3 * FETCH_MULTIPLIER

    def test_cursor_source_filter_returns_result_fields(self, monkeypatch):
        class FakeCollection:
            def query(self, **kwargs):
                return {
                    "documents": [["hello"]],
                    "metadatas": [[{"wing": "cursor", "room": "general", "source_file": f"/tmp{CHAT_SOURCE_MARKER}a.jsonl"}]],
                    "distances": [[0.1]],
                }

        class FakeClient:
            def get_collection(self, _name):
                return FakeCollection()

        monkeypatch.setattr("mempalace.searcher.chromadb.PersistentClient", lambda path: FakeClient())

        result = search_memories("authentication", "/tmp/palace", cursor_source_filter=True)
        hit = result["results"][0]
        assert "text" in hit
        assert "wing" in hit
        assert "room" in hit
        assert "source_file" in hit
        assert "similarity" in hit
        assert isinstance(hit["similarity"], float)
