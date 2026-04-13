"""Unit coverage for the LongMemEval benchmark harness helpers."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


_BENCH_PATH = Path(__file__).resolve().parents[1] / "benchmarks" / "longmemeval_bench.py"
_SPEC = importlib.util.spec_from_file_location("tests.longmemeval_bench", _BENCH_PATH)
longmemeval_bench = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(longmemeval_bench)


def _sample_entry() -> dict:
    return {
        "question_id": "q1",
        "question_type": "fact",
        "question": "What did you suggest for tea?",
        "answer": "Try oolong",
        "answer_session_ids": ["sess_a"],
        "haystack_session_ids": ["sess_a", "sess_b"],
        "haystack_dates": ["2024-01-10", "2024-02-11"],
        "haystack_sessions": [
            [
                {"role": "user", "content": "I prefer tea."},
                {"role": "assistant", "content": "Try oolong and sencha."},
                {"role": "user", "content": "Remind me next week."},
            ],
            [
                {"role": "user", "content": "Project note."},
                {"role": "assistant", "content": "Schedule a review."},
            ],
        ],
    }


def test_build_product_documents_matches_mined_transcript_shapes():
    session_docs = longmemeval_bench._build_product_documents(_sample_entry(), granularity="session")
    assert session_docs[0]["corpus_id"] == "sess_a"
    assert session_docs[0]["text"].startswith("> I prefer tea.")
    assert "Try oolong and sencha." in session_docs[0]["text"]
    assert session_docs[0]["source_file"] == "2024-01-10_sess_a.txt"

    turn_docs = longmemeval_bench._build_product_documents(_sample_entry(), granularity="turn")
    assert [doc["corpus_id"] for doc in turn_docs] == ["sess_a_turn_0", "sess_a_turn_1", "sess_b_turn_0"]
    assert turn_docs[0]["text"] == "> I prefer tea.\nTry oolong and sencha."
    assert turn_docs[1]["text"] == "> Remind me next week."


def test_rankings_from_product_hits_fills_missing_indices():
    documents = [
        {"corpus_id": "sess_a", "source_file": "a.txt"},
        {"corpus_id": "sess_b", "source_file": "b.txt"},
        {"corpus_id": "sess_c", "source_file": "c.txt"},
    ]
    results = {"results": [{"source_file": "b.txt"}]}

    rankings = longmemeval_bench._rankings_from_product_hits(results, documents)
    assert rankings == [1, 0, 2]


def test_build_product_rows_preserves_raw_and_support_artifacts(monkeypatch):
    documents = [
        {
            "corpus_id": "sess_a",
            "text": "> I prefer tea.\nTry oolong.",
            "timestamp": "2024-01-10",
            "source_file": "2024-01-10_sess_a.txt",
        }
    ]

    monkeypatch.setattr(
        longmemeval_bench,
        "build_retrieval_artifacts",
        lambda **kwargs: {
            "drawer_id": "drawer_a",
            "metadata": {"corpus_id": kwargs["extra_metadata"]["corpus_id"], "hall": "hall_preferences"},
            "support_row": {
                "id": "support_a",
                "document": "User has mentioned: tea",
                "metadata": {"parent_drawer_id": "drawer_a"},
            },
        },
    )

    raw_rows, support_rows = longmemeval_bench._build_product_rows(documents)
    assert raw_rows == [
        {
            "id": "drawer_a",
            "document": "> I prefer tea.\nTry oolong.",
            "metadata": {"corpus_id": "sess_a", "hall": "hall_preferences"},
        }
    ]
    assert support_rows == [
        {
            "id": "support_a",
            "document": "User has mentioned: tea",
            "metadata": {"parent_drawer_id": "drawer_a"},
        }
    ]


def test_build_product_rows_can_skip_support_artifacts(monkeypatch):
    documents = [
        {
            "corpus_id": "sess_a",
            "text": "> I prefer tea.\nTry oolong.",
            "timestamp": "2024-01-10",
            "source_file": "2024-01-10_sess_a.txt",
        }
    ]

    seen = {}

    def _fake_build(**kwargs):
        seen["include_support"] = kwargs["include_support"]
        return {
            "drawer_id": "drawer_a",
            "metadata": {"corpus_id": kwargs["extra_metadata"]["corpus_id"], "hall": "hall_preferences"},
            "support_row": None,
        }

    monkeypatch.setattr(longmemeval_bench, "build_retrieval_artifacts", _fake_build)

    raw_rows, support_rows = longmemeval_bench._build_product_rows(documents, include_support=False)
    assert seen["include_support"] is False
    assert raw_rows == [
        {
            "id": "drawer_a",
            "document": "> I prefer tea.\nTry oolong.",
            "metadata": {"corpus_id": "sess_a", "hall": "hall_preferences"},
        }
    ]
    assert support_rows == []


def test_run_benchmark_query_only_rejects_non_product_modes(tmp_path):
    data_file = tmp_path / "data.json"
    data_file.write_text(json.dumps([_sample_entry()]), encoding="utf-8")

    with pytest.raises(SystemExit):
        longmemeval_bench.run_benchmark(
            str(data_file),
            limit=1,
            mode="aaak",
            timing_scope="query_only",
        )


def test_run_benchmark_query_only_reports_split_timing(tmp_path, capsys, monkeypatch):
    data_file = tmp_path / "data.json"
    out_file = tmp_path / "results.jsonl"
    data_file.write_text(json.dumps([_sample_entry()]), encoding="utf-8")

    monkeypatch.setattr(
        longmemeval_bench,
        "build_product_palace_and_retrieve",
        lambda *args, **kwargs: ([0], ["doc"], ["sess_a"], ["2024-01-10"], 0.2, 0.05),
    )

    longmemeval_bench.run_benchmark(
        str(data_file),
        limit=1,
        out_file=str(out_file),
        mode="hybrid_v3",
        timing_scope="query_only",
    )

    out = capsys.readouterr().out
    assert "Timing:      query-only" in out
    assert "Query time:" in out
    assert "Build time excluded:" in out
    assert out_file.exists()


def test_normalize_mode_name_prefers_raw_v2_and_keeps_legacy_alias():
    assert longmemeval_bench._normalize_mode_name("raw_v2") == "raw_v2"
    assert longmemeval_bench._normalize_mode_name("hybrid_v2") == "raw_v2"


def test_build_product_palace_and_retrieve_batches_upserts_and_creates_support_lazily(monkeypatch):
    monkeypatch.setattr(
        longmemeval_bench,
        "_build_product_documents",
        lambda *args, **kwargs: [
            {
                "corpus_id": "sess_a",
                "text": "> I prefer tea.\nTry oolong.",
                "timestamp": "2024-01-10",
                "source_file": "2024-01-10_sess_a.txt",
            }
        ],
    )
    monkeypatch.setattr(
        longmemeval_bench,
        "_build_product_rows",
        lambda docs, include_support=True: (
            [{"id": "drawer_a", "document": docs[0]["text"], "metadata": {"corpus_id": "sess_a"}}],
            [],
        ),
    )

    raw_collection = MagicMock()
    support_collection = MagicMock()

    monkeypatch.setattr(
        longmemeval_bench,
        "_clone_product_palace_template",
        lambda: (MagicMock(), "/tmp/palace"),
    )
    monkeypatch.setattr(longmemeval_bench, "get_palace_collection", lambda *args, **kwargs: raw_collection)
    support_factory = MagicMock(return_value=support_collection)
    monkeypatch.setattr(longmemeval_bench, "get_support_collection", support_factory)
    monkeypatch.setattr(
        longmemeval_bench,
        "search_memories",
        lambda *args, **kwargs: {"results": [{"source_file": "2024-01-10_sess_a.txt"}]},
    )

    rankings, corpus, corpus_ids, corpus_timestamps, build_seconds, query_seconds = (
        longmemeval_bench.build_product_palace_and_retrieve(_sample_entry(), mode="hybrid_v3")
    )

    assert rankings == [0]
    assert corpus_ids == ["sess_a"]
    assert corpus_timestamps == ["2024-01-10"]
    assert build_seconds >= 0.0
    assert query_seconds >= 0.0
    raw_collection.upsert.assert_called_once_with(
        ids=["drawer_a"],
        documents=["> I prefer tea.\nTry oolong."],
        metadatas=[{"corpus_id": "sess_a"}],
    )
    support_factory.assert_not_called()
    support_collection.upsert.assert_not_called()


def test_build_product_palace_and_retrieve_skips_support_work_for_raw_v2(monkeypatch):
    monkeypatch.setattr(
        longmemeval_bench,
        "_build_product_documents",
        lambda *args, **kwargs: [
            {
                "corpus_id": "sess_a",
                "text": "> I prefer tea.\nTry oolong.",
                "timestamp": "2024-01-10",
                "source_file": "2024-01-10_sess_a.txt",
            }
        ],
    )

    calls = {}

    def _fake_rows(docs, include_support=True):
        calls["include_support"] = include_support
        return (
            [{"id": "drawer_a", "document": docs[0]["text"], "metadata": {"corpus_id": "sess_a"}}],
            [],
        )

    monkeypatch.setattr(longmemeval_bench, "_build_product_rows", _fake_rows)
    monkeypatch.setattr(
        longmemeval_bench,
        "_clone_product_palace_template",
        lambda: (MagicMock(), "/tmp/palace"),
    )

    raw_collection = MagicMock()
    monkeypatch.setattr(longmemeval_bench, "get_palace_collection", lambda *args, **kwargs: raw_collection)
    support_factory = MagicMock()
    monkeypatch.setattr(longmemeval_bench, "get_support_collection", support_factory)
    monkeypatch.setattr(
        longmemeval_bench,
        "search_memories",
        lambda *args, **kwargs: {"results": [{"source_file": "2024-01-10_sess_a.txt"}]},
    )

    longmemeval_bench.build_product_palace_and_retrieve(_sample_entry(), mode="raw_v2")

    assert calls["include_support"] is False
    support_factory.assert_not_called()
