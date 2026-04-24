"""Tests for the CLI `search()` path — asserts it applies hybrid rerank.

Regression: before this fix, `mempalace search` (CLI) went straight from
ChromaDB cosine results to display without calling `_hybrid_rank`. Meanwhile
`search_memories()` (MCP path) did apply hybrid rerank. Same file, two
paths, opposite retrieval quality. Confirmed by Igor 2026-04-24.

After the fix, the CLI path also runs `_hybrid_rank` so CLI and MCP return
comparable ranked results."""
from unittest import mock

import pytest

from mempalace import searcher


class _FakeCollection:
    """Minimal ChromaDB collection stub that returns canned query results."""

    def __init__(self, docs, metas, dists):
        self._docs = docs
        self._metas = metas
        self._dists = dists

    def query(self, **kwargs):
        n = kwargs.get("n_results", 5)
        return {
            "documents": [self._docs[:n]],
            "metadatas": [self._metas[:n]],
            "distances": [self._dists[:n]],
        }


@pytest.fixture
def fake_collection_docs():
    """Three drawer texts where cosine ranking and BM25 disagree.

    Drawer A matches 'paris' more strongly in cosine (tightest distance).
    Drawer B is cosine-weaker but BM25-stronger (contains 'paris' twice).
    Drawer C is cosine-weak and BM25-weak.
    After hybrid rerank, B should beat A on BM25 weight contribution."""
    return (
        [
            "A paris trip story.",                           # cosine-strongest
            "paris paris paris overview document body",    # bm25-strongest
            "unrelated content about other topics",         # weakest
        ],
        [
            {"source_file": "a.txt", "wing": "w", "room": "r"},
            {"source_file": "b.txt", "wing": "w", "room": "r"},
            {"source_file": "c.txt", "wing": "w", "room": "r"},
        ],
        [0.1, 0.3, 0.9],  # cosine distances
    )


def test_cli_search_calls_hybrid_rank(fake_collection_docs, capsys, tmp_path):
    """The CLI `search()` path MUST call `_hybrid_rank`. This is the
    regression test for the 'two paths, opposite retrieval quality' bug."""
    docs, metas, dists = fake_collection_docs
    col = _FakeCollection(docs, metas, dists)

    with mock.patch.object(searcher, "get_collection", return_value=col), \
         mock.patch.object(searcher, "_hybrid_rank",
                           wraps=searcher._hybrid_rank) as spy:
        searcher.search("paris", str(tmp_path))

    assert spy.called, (
        "CLI search() must call _hybrid_rank for BM25+cosine hybrid ranking. "
        "Before this fix, the CLI path skipped rerank while the MCP path "
        "applied it — producing inconsistent search quality between CLI and "
        "agent calls."
    )


def test_cli_search_overfetches_for_rerank(fake_collection_docs, tmp_path):
    """The CLI must over-fetch from ChromaDB so _hybrid_rank has material
    to reshuffle. n_results * K candidates, same pattern as search_memories."""
    docs, metas, dists = fake_collection_docs
    captured_kwargs = {}

    class _SpyCollection:
        def query(self, **kwargs):
            captured_kwargs.update(kwargs)
            return {
                "documents": [docs],
                "metadatas": [metas],
                "distances": [dists],
            }

    with mock.patch.object(searcher, "get_collection", return_value=_SpyCollection()):
        searcher.search("paris", str(tmp_path), n_results=3)

    # Over-fetch: must ask ChromaDB for MORE than n_results so there's
    # material for the hybrid reranker to actually reshuffle.
    assert captured_kwargs.get("n_results", 3) > 3, (
        f"Expected over-fetch (n_results > 3) for rerank; got "
        f"n_results={captured_kwargs.get('n_results')}"
    )


def test_cli_search_respects_n_results_for_display(fake_collection_docs, capsys, tmp_path):
    """Even though we over-fetch from ChromaDB, the user should see only
    n_results items in the output (after reranking)."""
    docs, metas, dists = fake_collection_docs
    col = _FakeCollection(docs, metas, dists)

    with mock.patch.object(searcher, "get_collection", return_value=col):
        searcher.search("paris", str(tmp_path), n_results=2)

    out = capsys.readouterr().out
    # Result headers look like "  [1] w / r" / "  [2] w / r"
    # After fix, we should see [1] and [2] but NOT [3]
    assert "[1]" in out
    assert "[2]" in out
    assert "[3]" not in out, (
        "User asked for n_results=2, should see only 2 result blocks after "
        "rerank + truncation"
    )
