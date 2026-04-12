"""
test_searcher.py -- Tests for both search() (CLI) and search_memories() (API).

Uses the real ChromaDB fixtures from conftest.py for integration tests,
plus mock-based tests for error paths.
"""

from unittest.mock import MagicMock, patch

import pytest

from mempalace.searcher import SearchError, _extract_keyword, search, search_memories


# ── search_memories (API) ──────────────────────────────────────────────


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

    def test_search_memories_query_error(self):
        """search_memories returns error dict when query raises."""
        mock_col = MagicMock()
        mock_col.query.side_effect = RuntimeError("query failed")

        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            result = search_memories("test", "/fake/path")
        assert "error" in result
        assert "query failed" in result["error"]

    def test_search_memories_filters_in_result(self, palace_path, seeded_collection):
        result = search_memories("test", palace_path, wing="project", room="backend")
        assert result["filters"]["wing"] == "project"
        assert result["filters"]["room"] == "backend"


# ── search() (CLI print function) ─────────────────────────────────────


class TestSearchCLI:
    def test_search_prints_results(self, palace_path, seeded_collection, capsys):
        search("JWT authentication", palace_path)
        captured = capsys.readouterr()
        assert "JWT" in captured.out or "authentication" in captured.out

    def test_search_with_wing_filter(self, palace_path, seeded_collection, capsys):
        search("planning", palace_path, wing="notes")
        captured = capsys.readouterr()
        assert "Results for" in captured.out

    def test_search_with_room_filter(self, palace_path, seeded_collection, capsys):
        search("database", palace_path, room="backend")
        captured = capsys.readouterr()
        assert "Room:" in captured.out

    def test_search_with_wing_and_room(self, palace_path, seeded_collection, capsys):
        search("code", palace_path, wing="project", room="frontend")
        captured = capsys.readouterr()
        assert "Wing:" in captured.out
        assert "Room:" in captured.out

    def test_search_no_palace_raises(self, tmp_path):
        with pytest.raises(SearchError, match="No palace found"):
            search("anything", str(tmp_path / "missing"))

    def test_search_no_results(self, palace_path, collection, capsys):
        """Empty collection returns no results message."""
        # collection is empty (no seeded data)
        result = search("xyzzy_nonexistent_query", palace_path, n_results=1)
        captured = capsys.readouterr()
        # Either prints "No results" or returns None
        assert result is None or "No results" in captured.out

    def test_search_query_error_raises(self):
        """search raises SearchError when query fails."""
        mock_col = MagicMock()
        mock_col.query.side_effect = RuntimeError("boom")

        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            with pytest.raises(SearchError, match="Search error"):
                search("test", "/fake/path")

    def test_search_n_results(self, palace_path, seeded_collection, capsys):
        search("code", palace_path, n_results=1)
        captured = capsys.readouterr()
        # Should have output with at least one result block
        assert "[1]" in captured.out


# ── _extract_keyword ───────────────────────────────────────────────────


class TestExtractKeyword:
    def test_picks_longest_non_stopword(self):
        assert _extract_keyword("how do I use authentication") == "authentication"

    def test_prefers_identifier_token(self):
        # "pgbouncer" contains no digit/underscore/dot but "pg_pool_size" does
        kw = _extract_keyword("what is pg_pool_size for pgbouncer")
        assert kw == "pg_pool_size"

    def test_prefers_dotted_token(self):
        kw = _extract_keyword("where is config.json stored")
        assert kw == "config.json"

    def test_empty_query_returns_empty(self):
        assert _extract_keyword("") == ""

    def test_all_stopwords_returns_empty(self):
        assert _extract_keyword("what is it") == ""

    def test_short_tokens_skipped(self):
        # All tokens <= 2 chars or stopwords
        assert _extract_keyword("do it") == ""


# ── hybrid search fallback ─────────────────────────────────────────────


class TestHybridSearchFallback:
    def test_keyword_fallback_triggered_on_poor_vector_results(self):
        """When best vector distance > 1.0, keyword fallback runs."""
        # Vector search returns one poor result; keyword search finds a better match
        mock_col = MagicMock()

        poor_vector = {
            "documents": [["some unrelated text"]],
            "metadatas": [[{"wing": "w", "room": "r", "source_file": "f.py"}]],
            "distances": [[1.5]],  # poor — triggers fallback
            "ids": [["vec_id_1"]],
        }
        keyword_hit = {
            "documents": [["pgbouncer connection pooling config"]],
            "metadatas": [[{"wing": "infra", "room": "db", "source_file": "db.md"}]],
            "distances": [[0.4]],
            "ids": [["kw_id_1"]],
        }

        # First call = vector search, second call = keyword fallback
        mock_col.query.side_effect = [poor_vector, keyword_hit]

        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            result = search_memories("pgbouncer config", "/fake/path")

        assert result.get("keyword_fallback") is not None
        # Keyword hit should appear in results (merged in)
        texts = [h["text"] for h in result["results"]]
        assert any("pgbouncer" in t for t in texts)

    def test_explicit_keyword_always_triggers_fallback(self):
        """Passing keyword= forces keyword search even with good vector results."""
        mock_col = MagicMock()

        good_vector = {
            "documents": [["some relevant text"]],
            "metadatas": [[{"wing": "w", "room": "r", "source_file": "f.py"}]],
            "distances": [[0.3]],  # good distance — no auto-fallback
            "ids": [["vec_id_1"]],
        }
        keyword_hit = {
            "documents": [["jwt_secret rotation schedule"]],
            "metadatas": [[{"wing": "infra", "room": "secrets", "source_file": "sec.md"}]],
            "distances": [[0.5]],
            "ids": [["kw_id_2"]],
        }

        mock_col.query.side_effect = [good_vector, keyword_hit]

        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            result = search_memories("authentication tokens", "/fake/path", keyword="jwt_secret")

        # keyword_fallback should be set since we passed keyword explicitly
        assert result.get("keyword_fallback") == "jwt_secret"

    def test_fallback_deduplicates_results(self):
        """IDs returned by both vector and keyword searches appear only once."""
        mock_col = MagicMock()

        shared_doc = "JWT tokens expire after 24 hours"
        shared_meta = {"wing": "project", "room": "backend", "source_file": "auth.py"}

        poor_vector = {
            "documents": [[shared_doc]],
            "metadatas": [[shared_meta]],
            "distances": [[1.2]],
            "ids": [["shared_id"]],
        }
        keyword_with_overlap = {
            "documents": [[shared_doc]],
            "metadatas": [[shared_meta]],
            "distances": [[1.2]],
            "ids": [["shared_id"]],  # same ID
        }

        mock_col.query.side_effect = [poor_vector, keyword_with_overlap]

        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            result = search_memories("jwt tokens", "/fake/path")

        # shared_id appears only once
        assert len(result["results"]) == 1

    def test_fallback_not_triggered_on_good_vector_results(self):
        """When best distance <= 1.0 and no explicit keyword, fallback is skipped."""
        mock_col = MagicMock()

        good_vector = {
            "documents": [["JWT tokens and authentication"]],
            "metadatas": [[{"wing": "project", "room": "backend", "source_file": "auth.py"}]],
            "distances": [[0.25]],
            "ids": [["vec_id_1"]],
        }

        mock_col.query.return_value = good_vector

        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            result = search_memories("jwt authentication", "/fake/path")

        # Only one query call — no keyword fallback
        assert mock_col.query.call_count == 1
        assert result.get("keyword_fallback") is None

    def test_result_includes_distance_field(self, palace_path, seeded_collection):
        """Results now expose a 'distance' field alongside 'similarity'."""
        result = search_memories("JWT authentication", palace_path)
        assert len(result["results"]) > 0
        hit = result["results"][0]
        assert "distance" in hit
        assert isinstance(hit["distance"], float)

    def test_keyword_fallback_is_best_effort(self):
        """A failing keyword query does not crash search_memories."""
        mock_col = MagicMock()

        poor_vector = {
            "documents": [["unrelated text"]],
            "metadatas": [[{"wing": "w", "room": "r", "source_file": "f.py"}]],
            "distances": [[1.8]],
            "ids": [["vid1"]],
        }

        def side_effect(**kwargs):
            if "where_document" in kwargs:
                raise RuntimeError("keyword query failed")
            return poor_vector

        mock_col.query.side_effect = side_effect

        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            result = search_memories("something obscure", "/fake/path")

        # Should still return vector results without crashing
        assert "results" in result
        assert len(result["results"]) == 1
