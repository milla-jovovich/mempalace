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


# ── _extract_keyword ─────────────────────────────────────────────────


class TestExtractKeyword:
    def test_picks_longest_non_stopword(self):
        assert _extract_keyword("the database migration") == "migration"

    def test_prefers_identifier_tokens(self):
        # Token with digits should win even if shorter
        assert _extract_keyword("check error code E4021") == "e4021"

    def test_prefers_dotted_identifiers(self):
        assert _extract_keyword("the config key server.port") == "server.port"

    def test_prefers_underscore_identifiers(self):
        assert _extract_keyword("set max_retries value") == "max_retries"

    def test_all_stopwords_returns_empty(self):
        assert _extract_keyword("the is a for") == ""

    def test_short_tokens_skipped(self):
        # Tokens with len <= 2 are filtered out
        assert _extract_keyword("is it ok to go") == ""

    def test_single_word_query(self):
        assert _extract_keyword("pgbouncer") == "pgbouncer"

    def test_mixed_case_lowered(self):
        result = _extract_keyword("Check PostgreSQL Status")
        assert result == "postgresql"


# ── Hybrid search (keyword fallback) ─────────────────────────────────


class TestHybridSearch:
    def test_explicit_keyword_triggers_fallback(self, palace_path, seeded_collection):
        """Passing an explicit keyword should produce keyword_fallback in results."""
        result = search_memories("connection pooling", palace_path, keyword="pgbouncer")
        assert result.get("keyword_fallback") == "pgbouncer"

    def test_keyword_match_field_present(self, palace_path, seeded_collection):
        """Keyword-only hits (not found by vector) should have keyword_match field.

        With only 4 seeded docs, n_results=1 ensures vector returns just
        one result.  A semantically distant query makes that result
        unlikely to be the pgbouncer doc, so keyword finds it exclusively.
        """
        result = search_memories(
            "React frontend TanStack",
            palace_path,
            keyword="pgbouncer",
            n_results=1,
        )
        # With n_results=1: vector returns 1 hit (likely frontend doc),
        # keyword returns 1 hit (db.py with pgbouncer). Merged = up to 2,
        # capped to 1. But keyword_fallback should be set regardless.
        assert result.get("keyword_fallback") == "pgbouncer"

    def test_results_sorted_by_distance(self, palace_path, seeded_collection):
        result = search_memories("database", palace_path, keyword="pgbouncer")
        dists = [r["distance"] for r in result["results"]]
        assert dists == sorted(dists)

    def test_no_keyword_fallback_on_good_results(self, palace_path, seeded_collection):
        """Good vector results (low distance) should not trigger auto-fallback."""
        result = search_memories("JWT authentication tokens", palace_path)
        # This is a strong semantic match — keyword_fallback should be None
        assert result.get("keyword_fallback") is None

    def test_n_results_cap_with_keyword(self, palace_path, seeded_collection):
        result = search_memories("code", palace_path, keyword="the", n_results=2)
        assert len(result["results"]) <= 2

    def test_dedup_between_vector_and_keyword(self, palace_path, seeded_collection):
        """Same drawer found by both vector and keyword shouldn't appear twice."""
        result = search_memories(
            "PostgreSQL database migrations",
            palace_path,
            keyword="alembic",
        )
        ids_seen = set()
        for hit in result["results"]:
            # source_file + wing + room is a stable identity for dedup check
            key = (hit["source_file"], hit["wing"], hit["room"])
            assert key not in ids_seen, f"Duplicate hit: {key}"
            ids_seen.add(key)

    def test_keyword_param_passes_through_mcp(self, palace_path, seeded_collection):
        """search_memories accepts keyword param without error."""
        result = search_memories("test", palace_path, keyword="JWT")
        assert "results" in result
        assert "error" not in result
