"""
test_searcher.py -- Tests for both search() (CLI) and search_memories() (API).

Uses the real ChromaDB fixtures from conftest.py for integration tests,
plus mock-based tests for error paths.
"""

from datetime import datetime, timedelta
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

    def test_search_memories_hybrid_keyword_rerank(self):
        """Raw_v2 should promote exact keyword matches over a slightly closer generic hit."""
        mock_col = MagicMock()
        mock_col.query.return_value = {
            "ids": [["doc_generic", "doc_exact"]],
            "documents": [[
                "We talked generally about graduation plans and future work.",
                "You graduated with a Business Administration degree and minored in design.",
            ]],
            "metadatas": [[
                {"wing": "notes", "room": "general", "source_file": "generic.txt"},
                {"wing": "notes", "room": "general", "source_file": "degree.txt"},
            ]],
            "distances": [[0.31, 0.39]],
        }

        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            result = search_memories(
                "What degree in business administration did I graduate with?",
                "/fake/path",
                n_results=2,
                strategy="raw_v2",
            )

        assert result["strategy"] == "raw_v2"
        assert result["results"][0]["source_file"] == "degree.txt"
        assert result["results"][0]["rank_distance"] < result["results"][0]["distance"]
        assert result["results"][0]["keyword_overlap"] > result["results"][1]["keyword_overlap"]

    def test_search_memories_hybrid_temporal_boost(self):
        """Relative-time questions should favor drawers whose metadata date matches the window."""
        recent_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        old_date = (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d")

        mock_col = MagicMock()
        mock_col.query.return_value = {
            "ids": [["doc_old", "doc_recent"]],
            "documents": [[
                "We discussed the launch plan and next steps for the release.",
                "We discussed the launch plan and next steps for the release.",
            ]],
            "metadatas": [[
                {"wing": "notes", "room": "planning", "source_file": f"session_{old_date}.txt"},
                {"wing": "notes", "room": "planning", "source_file": f"session_{recent_date}.txt"},
            ]],
            "distances": [[0.30, 0.34]],
        }

        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            result = search_memories(
                "What were we discussing a week ago?",
                "/fake/path",
                n_results=2,
                strategy="raw_v2",
            )

        assert result["results"][0]["source_file"] == f"session_{recent_date}.txt"
        assert result["results"][0]["temporal_boost"] > 0.0

    def test_search_memories_hybrid_assistant_second_pass(self):
        """Assistant-reference queries should search deeper inside the top transcript files."""

        def query_side_effect(**kwargs):
            where = kwargs.get("where")
            if where == {"source_file": "convo_a.txt"}:
                return {
                    "ids": [["doc_a_seed", "doc_a_assistant"]],
                    "documents": [[
                        "> I need auth help\nWe can revisit that tomorrow.",
                        "> I need auth help\nI suggest passkeys for the login flow.",
                    ]],
                    "metadatas": [[
                        {"wing": "convos", "room": "technical", "source_file": "convo_a.txt"},
                        {"wing": "convos", "room": "technical", "source_file": "convo_a.txt"},
                    ]],
                    "distances": [[0.30, 0.33]],
                }
            if where == {"source_file": "convo_b.txt"}:
                return {
                    "ids": [["doc_b_seed"]],
                    "documents": [["> misc\nWe talked about unrelated chores."]],
                    "metadatas": [[
                        {"wing": "convos", "room": "general", "source_file": "convo_b.txt"}
                    ]],
                    "distances": [[0.32]],
                }
            return {
                "ids": [["doc_a_seed", "doc_b_seed"]],
                "documents": [[
                    "> I need auth help\nWe can revisit that tomorrow.",
                    "> misc\nWe talked about unrelated chores.",
                ]],
                "metadatas": [[
                    {"wing": "convos", "room": "technical", "source_file": "convo_a.txt"},
                    {"wing": "convos", "room": "general", "source_file": "convo_b.txt"},
                ]],
                "distances": [[0.30, 0.32]],
            }

        mock_col = MagicMock()
        mock_col.query.side_effect = query_side_effect

        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            result = search_memories(
                "What did you suggest for the login flow?",
                "/fake/path",
                n_results=2,
                strategy="raw_v2",
            )

        assert result["results"][0]["text"].endswith("I suggest passkeys for the login flow.")
        assert mock_col.query.call_count >= 2

    def test_search_memories_legacy_hybrid_v2_alias_reports_raw_v2(self):
        mock_col = MagicMock()
        mock_col.query.return_value = {
            "ids": [["doc_exact"]],
            "documents": [["> tea\nTry oolong."]],
            "metadatas": [[{"wing": "notes", "room": "general", "source_file": "tea.txt"}]],
            "distances": [[0.2]],
        }

        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            result = search_memories("What tea did you suggest?", "/fake/path", strategy="hybrid_v2")

        assert result["strategy"] == "raw_v2"

    def test_search_memories_hybrid_v3_uses_support_docs_for_preference_queries(self):
        """Hybrid_v3 should map support hits back to the raw drawer they explain."""

        def raw_query_side_effect(**kwargs):
            return {
                "ids": [["raw_generic", "raw_target"]],
                "documents": [[
                    "We discussed several laptop models for travel and portability.",
                    "I have been struggling with battery life on my laptop lately.",
                ]],
                "metadatas": [[
                    {"wing": "notes", "room": "gear", "source_file": "generic.txt", "hall": "hall_general"},
                    {
                        "wing": "notes",
                        "room": "gear",
                        "source_file": "battery.txt",
                        "hall": "hall_preferences",
                    },
                ]],
                "distances": [[0.24, 0.42]],
            }

        mock_raw = MagicMock()
        mock_raw.query.side_effect = raw_query_side_effect
        mock_raw.get.return_value = {
            "ids": ["raw_target"],
            "documents": ["I have been struggling with battery life on my laptop lately."],
            "metadatas": [[
                {
                    "wing": "notes",
                    "room": "gear",
                    "source_file": "battery.txt",
                    "hall": "hall_preferences",
                }
            ][0]],
        }

        mock_support = MagicMock()
        mock_support.query.return_value = {
            "ids": [["support_target"]],
            "documents": [["User has mentioned: battery life on my laptop lately"]],
            "metadatas": [[
                {
                    "parent_drawer_id": "raw_target",
                    "support_kind": "preference",
                    "wing": "notes",
                    "room": "gear",
                    "hall": "hall_preferences",
                }
            ]],
            "distances": [[0.12]],
        }

        with (
            patch("mempalace.searcher.get_collection", return_value=mock_raw),
            patch("mempalace.searcher.get_support_collection", return_value=mock_support),
        ):
            result = search_memories(
                "What battery life issues have I mentioned lately?",
                "/fake/path",
                n_results=2,
                strategy="hybrid_v3",
            )

        assert result["strategy"] == "hybrid_v3"
        assert result["results"][0]["source_file"] == "battery.txt"
        assert result["results"][0]["retrieval_source"] == "support_preference"
        assert result["results"][0]["support_boost"] > 0.0

    def test_search_memories_hybrid_v3_skips_support_docs_for_non_preference_queries(self):
        """Hybrid_v3 should not pay the support-doc lookup cost on unrelated queries."""
        mock_raw = MagicMock()
        mock_raw.query.return_value = {
            "ids": [["doc_fact"]],
            "documents": [["You graduated with a Business Administration degree."]],
            "metadatas": [[
                {
                    "wing": "notes",
                    "room": "profile",
                    "source_file": "degree.txt",
                    "hall": "hall_facts",
                }
            ]],
            "distances": [[0.2]],
        }
        mock_support = MagicMock()
        mock_support.query.side_effect = AssertionError("support collection should not be queried")

        with (
            patch("mempalace.searcher.get_collection", return_value=mock_raw),
            patch("mempalace.searcher.get_support_collection", return_value=mock_support),
        ):
            result = search_memories(
                "What degree did I study?",
                "/fake/path",
                n_results=1,
                strategy="hybrid_v3",
            )

        assert result["results"][0]["source_file"] == "degree.txt"
        assert result["results"][0]["retrieval_source"] == "raw"

    def test_search_memories_palace_boosts_hall_validated_results(self):
        """Palace mode should let hall routing outrank a generic but slightly closer hit."""

        def raw_query_side_effect(**kwargs):
            where = kwargs.get("where")
            if where == {"hall": "hall_facts"}:
                return {
                    "ids": [["doc_fact"]],
                    "documents": [["You graduated with a Business Administration degree."]],
                    "metadatas": [[
                        {
                            "wing": "notes",
                            "room": "profile",
                            "source_file": "degree.txt",
                            "hall": "hall_facts",
                        }
                    ]],
                    "distances": [[0.42]],
                }
            return {
                "ids": [["doc_generic", "doc_fact"]],
                "documents": [[
                    "We talked generally about planning next semester coursework.",
                    "You graduated with a Business Administration degree.",
                ]],
                "metadatas": [[
                    {
                        "wing": "notes",
                        "room": "planning",
                        "source_file": "generic.txt",
                        "hall": "hall_general",
                    },
                    {
                        "wing": "notes",
                        "room": "profile",
                        "source_file": "degree.txt",
                        "hall": "hall_facts",
                    },
                ]],
                "distances": [[0.24, 0.42]],
            }

        mock_raw = MagicMock()
        mock_raw.query.side_effect = raw_query_side_effect
        mock_support = MagicMock()

        with (
            patch("mempalace.searcher.get_collection", return_value=mock_raw),
            patch("mempalace.searcher.get_support_collection", return_value=mock_support),
        ):
            result = search_memories(
                "What degree did I study?",
                "/fake/path",
                n_results=2,
                strategy="PALACE",
            )

        assert result["strategy"] == "palace"
        assert result["results"][0]["source_file"] == "degree.txt"
        assert result["results"][0]["hall"] == "hall_facts"
        assert result["results"][0]["hall_boost"] > 0.0
        assert result["results"][0]["validation_boost"] > 0.0

    def test_search_memories_hybrid_v3_tolerates_missing_support_collection(self):
        """Older palaces without the support collection should still search cleanly."""
        mock_raw = MagicMock()
        mock_raw.query.return_value = {
            "ids": [["doc_fact"]],
            "documents": [["You graduated with a Business Administration degree."]],
            "metadatas": [[
                {
                    "wing": "notes",
                    "room": "profile",
                    "source_file": "degree.txt",
                    "hall": "hall_facts",
                }
            ]],
            "distances": [[0.2]],
        }

        with (
            patch("mempalace.searcher.get_collection", return_value=mock_raw),
            patch("mempalace.searcher.get_support_collection", side_effect=RuntimeError("missing")),
        ):
            result = search_memories(
                "What degree did I study?",
                "/fake/path",
                n_results=1,
                strategy="hybrid_v3",
            )

        assert result["results"][0]["source_file"] == "degree.txt"
        assert result["results"][0]["retrieval_source"] == "raw"

    def test_search_memories_unknown_strategy(self):
        """Unknown strategies should fail closed with an error dict."""
        mock_col = MagicMock()

        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            result = search_memories("test", "/fake/path", strategy="unknown_mode")

        assert "error" in result
        assert "Unknown search strategy" in result["error"]


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

    def test_search_prints_normalized_strategy_hall_and_retrieval_source(self, capsys):
        mock_raw = MagicMock()
        mock_raw.query.return_value = {
            "ids": [["raw_target"]],
            "documents": [["I have been struggling with battery life on my laptop lately."]],
            "metadatas": [[
                {
                    "wing": "notes",
                    "room": "gear",
                    "source_file": "battery.txt",
                    "hall": "hall_preferences",
                }
            ]],
            "distances": [[0.42]],
        }
        mock_raw.get.return_value = {
            "ids": ["raw_target"],
            "documents": ["I have been struggling with battery life on my laptop lately."],
            "metadatas": [
                {
                    "wing": "notes",
                    "room": "gear",
                    "source_file": "battery.txt",
                    "hall": "hall_preferences",
                }
            ],
        }
        mock_support = MagicMock()
        mock_support.query.return_value = {
            "ids": [["support_target"]],
            "documents": [["User has mentioned: battery life on my laptop lately"]],
            "metadatas": [[
                {
                    "parent_drawer_id": "raw_target",
                    "support_kind": "preference",
                    "wing": "notes",
                    "room": "gear",
                    "hall": "hall_preferences",
                }
            ]],
            "distances": [[0.12]],
        }

        with (
            patch("mempalace.searcher.get_collection", return_value=mock_raw),
            patch("mempalace.searcher.get_support_collection", return_value=mock_support),
        ):
            search(
                "What battery life issues have I mentioned lately?",
                "/fake/path",
                strategy="HYBRID_V3",
            )

        out = capsys.readouterr().out
        assert "Strategy: hybrid_v3" in out
        assert "Hall:" in out
        assert "Via:" in out
