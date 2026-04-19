"""
test_searcher.py -- Tests for both search() (CLI) and search_memories() (API).

Uses the real ChromaDB fixtures from conftest.py for integration tests,
plus mock-based tests for error paths.
"""

from unittest.mock import MagicMock, patch

import pytest

from mempalace.searcher import SearchError, search, search_memories


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
        assert "created_at" in hit

    def test_created_at_contains_filed_at(self, palace_path, seeded_collection):
        """created_at surfaces the filed_at metadata from the drawer."""
        result = search_memories("JWT authentication", palace_path)
        hit = result["results"][0]
        assert hit["created_at"] == "2026-01-01T00:00:00"

    def test_created_at_fallback_when_filed_at_missing(self):
        """created_at defaults to 'unknown' when filed_at is absent."""
        mock_col = MagicMock()
        mock_col.count.return_value = 1
        mock_col.query.return_value = {
            "ids": [["drawer_no_date"]],
            "documents": [["Some text without a date"]],
            "metadatas": [[{"wing": "project", "room": "backend", "source_file": "x.py"}]],
            "distances": [[0.1]],
        }

        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            result = search_memories("test", "/fake/path")
        hit = result["results"][0]
        assert hit["created_at"] == "unknown"

    def test_search_memories_query_error_degrades_to_warning(self):
        """When the vector query raises, search_memories should degrade rather
        than hard-fail: surface the error as a warning and continue with the
        sqlite fallback so callers still see what's reachable. This is the
        "all info + why we can't get the rest" contract — a silent hit-miss
        would be worse than a crash because it makes the palace look empty
        when the data is actually there."""
        mock_col = MagicMock()
        mock_col.count.return_value = 0
        mock_col.query.side_effect = RuntimeError("query failed")
        # col.get is also called (for the sqlite fallback and pool count);
        # return an empty pool so the fallback finds nothing to promote.
        mock_col.get.return_value = {"documents": [], "metadatas": [], "ids": []}

        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            result = search_memories("test", "/fake/path")
        assert "error" not in result
        assert "warnings" in result
        assert any("query failed" in w for w in result["warnings"])
        assert result["results"] == []

    def test_search_memories_filters_in_result(self, palace_path, seeded_collection):
        result = search_memories("test", palace_path, wing="project", room="backend")
        assert result["filters"]["wing"] == "project"
        assert result["filters"]["room"] == "backend"

    def test_search_memories_handles_none_metadata(self):
        """API path: `None` entries in the drawer results' metadatas list must
        fall back to the sentinel strings (wing/room 'unknown', source '?')
        rather than raising `AttributeError: 'NoneType' object has no
        attribute 'get'` while the rest of the result set renders."""
        mock_col = MagicMock()
        mock_col.count.return_value = 2
        mock_col.query.return_value = {
            "documents": [["first doc", "second doc"]],
            "metadatas": [[{"source_file": "a.md", "wing": "w", "room": "r"}, None]],
            "distances": [[0.1, 0.2]],
            "ids": [["d1", "d2"]],
        }

        def mock_get_collection(path, create=False):
            # First call: drawers. Second call: closets — raise so hybrid
            # degrades to pure drawer search (the catch block covers it).
            if not hasattr(mock_get_collection, "_called"):
                mock_get_collection._called = True
                return mock_col
            raise RuntimeError("no closets")

        with patch("mempalace.searcher.get_collection", side_effect=mock_get_collection):
            result = search_memories("anything", "/fake/path")
        assert "results" in result
        assert len(result["results"]) == 2
        # The None-metadata hit renders with sentinel values, not a crash.
        none_hit = result["results"][1]
        assert none_hit["text"] == "second doc"
        assert none_hit["wing"] == "unknown"
        assert none_hit["room"] == "unknown"

    def test_search_memories_fills_from_sqlite_when_vector_underdelivers(self):
        """If vector returns fewer than n_results but sqlite has more drawers
        matching the scope, BM25-rank the leftover pool and fill the gap.
        This is the kiyo failure mode: vector returned 0 hits while sqlite
        had 5,243 drawers in the requested wing. After this change, the
        sqlite pool is BM25-ranked and the top keyword matches fill in."""
        mock_col = MagicMock()
        mock_col.count.return_value = 4
        # Vector returns only 1 result
        mock_col.query.return_value = {
            "documents": [["vector hit about kiyo"]],
            "metadatas": [
                [{"wing": "kiyo-xhci-fix", "room": "kiyo_xhci_fix", "source_file": "a.sh"}]
            ],
            "distances": [[0.2]],
            "ids": [["d1"]],
        }
        # Sqlite pool has 3 more drawers matching the scope — two mention kiyo
        mock_col.get.return_value = {
            "ids": ["d1", "d2", "d3", "d4"],
            "documents": [
                "vector hit about kiyo",
                "another kiyo xhci fix write-up",
                "unrelated content no match terms",
                "more kiyo pro usb crash investigation",
            ],
            "metadatas": [
                {"wing": "kiyo-xhci-fix", "room": "kiyo_xhci_fix", "source_file": "a.sh"},
                {"wing": "kiyo-xhci-fix", "room": "kiyo_xhci_fix", "source_file": "b.md"},
                {"wing": "kiyo-xhci-fix", "room": "kiyo_xhci_fix", "source_file": "c.md"},
                {"wing": "kiyo-xhci-fix", "room": "kiyo_xhci_fix", "source_file": "d.log"},
            ],
        }

        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            result = search_memories("kiyo xhci", "/fake/path", wing="kiyo-xhci-fix", n_results=5)

        # Vector gave 1, sqlite fill promoted 2 more (the ones with "kiyo" or
        # "xhci" tokens); the unrelated drawer is skipped because BM25=0.
        assert len(result["results"]) >= 2
        vector_hits = [h for h in result["results"] if h.get("matched_via") == "drawer"]
        fallback_hits = [
            h for h in result["results"] if h.get("matched_via") == "sqlite_bm25_fallback"
        ]
        assert len(vector_hits) == 1
        assert len(fallback_hits) >= 1
        # Authoritative scope count reflects sqlite, not HNSW
        assert result["available_in_scope"] == 4
        # Warnings explain the top-up
        assert any("sqlite+BM25" in w for w in result["warnings"])

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

    def test_search_query_error_degrades_to_warning(self, capsys):
        """CLI search no longer raises when the vector query fails — it
        delegates to search_memories which degrades to a warning + sqlite
        fallback. The warning is printed so the user sees why the palace
        is returning fewer results than expected."""
        mock_col = MagicMock()
        mock_col.count.return_value = 0
        mock_col.query.side_effect = RuntimeError("boom")
        mock_col.get.return_value = {"documents": [], "metadatas": [], "ids": []}

        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            search("test", "/fake/path")
        captured = capsys.readouterr()
        assert "vector search unavailable" in captured.out
        assert "boom" in captured.out

    def test_search_n_results(self, palace_path, seeded_collection, capsys):
        search("code", palace_path, n_results=1)
        captured = capsys.readouterr()
        # Should have output with at least one result block
        assert "[1]" in captured.out

    def test_search_handles_none_metadata_without_crash(self, capsys):
        """ChromaDB can return `None` entries in the metadatas list when a
        drawer has no metadata. The CLI print path must not crash on them
        mid-render — it used to raise `AttributeError: 'NoneType' object has
        no attribute 'get'` after printing earlier results."""
        mock_col = MagicMock()
        mock_col.count.return_value = 2
        mock_col.query.return_value = {
            "documents": [["first doc", "second doc"]],
            "metadatas": [[{"source_file": "a.md", "wing": "w", "room": "r"}, None]],
            "distances": [[0.1, 0.2]],
        }
        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            search("anything", "/fake/path")
        captured = capsys.readouterr()
        assert "[1]" in captured.out
        assert "[2]" in captured.out
        # Second result renders with fallback '?' values instead of crashing
        assert "second doc" in captured.out
