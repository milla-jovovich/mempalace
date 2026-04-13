"""Direct coverage for search helper branches introduced by mined signals."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from mempalace import searcher


def test_where_filter_and_clause_helpers_cover_all_fields():
    where = searcher.build_where_filter(
        wing="wing",
        room="room",
        source_file="source.txt",
        hall="hall_facts",
        support_kind="preference",
    )

    assert where == {
        "$and": [
            {"wing": "wing"},
            {"room": "room"},
            {"source_file": "source.txt"},
            {"hall": "hall_facts"},
            {"support_kind": "preference"},
        ]
    }
    assert searcher._append_where_clause({"$and": [{"wing": "wing"}]}, {"room": "room"}) == {
        "$and": [{"wing": "wing"}, {"room": "room"}]
    }
    assert searcher._append_where_clause({"wing": "wing"}, {"room": "room"}) == {
        "$and": [{"wing": "wing"}, {"room": "room"}]
    }
    assert searcher._keyword_overlap([], "any document") == 0.0


def test_datetime_parsers_cover_edge_cases_and_partial_temporal_boost():
    now = datetime(2026, 1, 2, 3, 4, 5)

    assert searcher._parse_datetime_value(None) is None
    assert searcher._parse_datetime_value("") is None
    assert searcher._parse_datetime_value("   ") is None
    assert searcher._parse_datetime_value(now) == now
    assert searcher._parse_datetime_value("2026/01/02") == datetime(2026, 1, 2)
    assert searcher._parse_datetime_value("not-a-date") is None
    assert searcher._parse_datetime_value(10**30) is None
    assert searcher._parse_datetime_from_source_file("") is None
    assert searcher._parse_datetime_from_source_file("session_2026-13-40.txt") is None
    assert searcher._parse_datetime_from_source_file("March-4-2026.txt") == datetime(2026, 3, 4)
    assert searcher._parse_datetime_from_source_file("March-40-2026.txt") is None
    assert searcher._extract_candidate_datetime({"timestamp": "2026-01-02"}) == datetime(2026, 1, 2)
    assert searcher._extract_candidate_datetime({"source_file": "session_2026-01-03.txt"}) == datetime(
        2026, 1, 3
    )

    distance, boost = searcher._apply_temporal_boost(0.5, {}, "What happened last week?")
    assert (distance, boost) == (0.5, 0.0)

    partial_date = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    distance, boost = searcher._apply_temporal_boost(
        0.5,
        {"source_file": f"session_{partial_date}.txt"},
        "What happened last week?",
    )
    assert 0.0 < boost < 0.4
    assert distance < 0.5


def test_support_mapping_helpers_cover_empty_missing_and_none_collection():
    raw_collection = MagicMock()

    assert searcher._map_support_rows_to_raw(raw_collection, [{"meta": {}, "distance": 0.1}]) == []

    raw_collection.get.return_value = {
        "ids": ["drawer_present"],
        "documents": ["Raw drawer text"],
        "metadatas": [{"wing": "wing", "room": "room"}],
    }
    mapped = searcher._map_support_rows_to_raw(
        raw_collection,
        [
            {
                "meta": {"parent_drawer_id": "drawer_present", "support_kind": "preference"},
                "distance": 0.1,
                "retrieval_source": "support_preference",
            },
            {
                "meta": {"parent_drawer_id": "drawer_missing", "support_kind": "preference"},
                "distance": 0.2,
                "retrieval_source": "support_preference",
            },
        ],
    )

    assert mapped == [
        {
            "id": "drawer_present",
            "display_id": "drawer_present",
            "text": "Raw drawer text",
            "meta": {"wing": "wing", "room": "room"},
            "distance": 0.1,
            "retrieval_source": "support_preference",
            "support_kind": "preference",
        }
    ]
    assert searcher._query_support_rows(raw_collection, None, "query", 5, {}, "preference") == []


def test_assistant_second_pass_skips_missing_duplicate_and_limits_to_three():
    raw_collection = MagicMock()
    raw_collection.query.return_value = {
        "ids": [["drawer"]],
        "documents": [["assistant expansion"]],
        "metadatas": [[{"source_file": "a.txt"}]],
        "distances": [[0.2]],
    }
    seed_rows = [
        {"meta": {"source_file": ""}},
        {"meta": {"source_file": "a.txt"}},
        {"meta": {"source_file": "a.txt"}},
        {"meta": {"source_file": "b.txt"}},
        {"meta": {"source_file": "c.txt"}},
        {"meta": {"source_file": "d.txt"}},
    ]

    rows = searcher._assistant_second_pass(
        raw_collection,
        "What did you suggest for the login flow?",
        {},
        seed_rows,
    )

    assert len(rows) == 3
    assert raw_collection.query.call_count == 3


def test_run_search_strategy_raw_and_palace_specific_branches():
    raw_collection = MagicMock()
    raw_collection.query.return_value = {
        "ids": [["raw_doc"]],
        "documents": [["Raw drawer text"]],
        "metadatas": [[{"wing": "wing", "room": "room", "hall": "hall_general"}]],
        "distances": [[0.25]],
    }

    rows = searcher._run_search_strategy(raw_collection, None, "query", {}, 1, "raw")
    assert rows[0]["rank_distance"] == rows[0]["distance"]
    assert rows[0]["validation_boost"] == 0.0

    def palace_raw_query_side_effect(**kwargs):
        where = kwargs.get("where")
        if where == {"hall": "hall_preferences"}:
            return {
                "ids": [["drawer_pref"]],
                "documents": [["I have been struggling with battery life on my laptop lately."]],
                "metadatas": [[
                    {
                        "wing": "wing",
                        "room": "gear",
                        "source_file": "battery.txt",
                        "hall": "hall_preferences",
                    }
                ]],
                "distances": [[0.45]],
            }
        if where == {"hall": "hall_events"}:
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
        return {
            "ids": [["drawer_fact", "drawer_pref"]],
            "documents": [[
                "You graduated with a Business Administration degree.",
                "I have been struggling with battery life on my laptop lately.",
            ]],
            "metadatas": [[
                {
                    "wing": "wing",
                    "room": "profile",
                    "source_file": "degree.txt",
                    "hall": "hall_facts",
                },
                {
                    "wing": "wing",
                    "room": "gear",
                    "source_file": "battery.txt",
                    "hall": "hall_preferences",
                },
            ]],
            "distances": [[0.35, 0.45]],
        }

    support_collection = MagicMock()
    support_collection.query.return_value = {
        "ids": [["support_pref"]],
        "documents": [["User has mentioned: battery life on my laptop lately"]],
        "metadatas": [[
            {
                "parent_drawer_id": "drawer_pref",
                "support_kind": "preference",
                "hall": "hall_preferences",
            }
        ]],
        "distances": [[0.12]],
    }

    raw_collection.query.side_effect = palace_raw_query_side_effect
    raw_collection.get.return_value = {
        "ids": ["drawer_pref"],
        "documents": ["I have been struggling with battery life on my laptop lately."],
        "metadatas": [
            {
                "wing": "wing",
                "room": "gear",
                "source_file": "battery.txt",
                "hall": "hall_preferences",
            }
        ],
    }

    preference_rows = searcher._search_palace(
        raw_collection,
        support_collection,
        "What battery issues have I mentioned lately?",
        {},
        2,
    )
    assert support_collection.query.call_count == 2
    assert preference_rows[0]["hall_boost"] > 0.0

    event_rows = searcher._search_palace(
        raw_collection,
        support_collection,
        "What happened last month?",
        {},
        1,
    )
    assert event_rows[0]["hall_boost"] == 0.1
    assert event_rows[0]["meta"]["hall"] == "hall_facts"


def test_optional_support_collection_and_mcp_support_fallback_paths(tmp_path):
    with patch("mempalace.searcher.get_support_collection", side_effect=RuntimeError("missing")):
        assert searcher._get_optional_support_collection(str(tmp_path)) is None

    from mempalace import mcp_server

    with (
        patch("mempalace.mcp_server._get_client", side_effect=RuntimeError("boom")),
        patch(
            "mempalace.mcp_server.get_support_collection_adapter",
            return_value=SimpleNamespace(_collection="fallback-support"),
        ),
    ):
        assert mcp_server._get_support_collection(create=True) == "fallback-support"

    with (
        patch("mempalace.mcp_server._get_client", side_effect=RuntimeError("boom")),
        patch("mempalace.mcp_server.get_support_collection_adapter", side_effect=RuntimeError("boom")),
    ):
        assert mcp_server._get_support_collection(create=True) is None
