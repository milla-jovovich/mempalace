"""Regression tests for issue #195 — empty query results must not IndexError.

Before the backend refactor these tests checked the Chroma-native nested
batch shape (``{"documents": [["a","b"]]}``). After the refactor,
``BaseCollection.query`` returns a :class:`QueryResult` with flat lists,
so the adapter layer is responsible for collapsing the batch dimension
before callers ever see it. ``_first_or_empty`` now just guards against
``None`` / missing attrs so search keeps returning "no results" instead
of crashing.
"""

from mempalace.backends.base import QueryResult
from mempalace.searcher import _first_or_empty


def test_first_or_empty_handles_empty_query_result():
    """An empty QueryResult (collection is empty or filter excludes all)."""
    results = QueryResult()
    assert _first_or_empty(results, "documents") == []
    assert _first_or_empty(results, "metadatas") == []
    assert _first_or_empty(results, "distances") == []


def test_first_or_empty_handles_none_results():
    """Defensive: callers sometimes pass ``None`` on exception paths."""
    assert _first_or_empty(None, "documents") == []


def test_first_or_empty_returns_flat_list_for_normal_result():
    results = QueryResult(
        ids=["a", "b", "c"],
        documents=["doc_a", "doc_b", "doc_c"],
        metadatas=[{}, {}, {}],
        distances=[0.1, 0.2, 0.3],
    )
    assert _first_or_empty(results, "documents") == ["doc_a", "doc_b", "doc_c"]
    assert _first_or_empty(results, "distances") == [0.1, 0.2, 0.3]


def test_first_or_empty_handles_dict_like_with_flat_values():
    """Backwards-compat: plain dicts with flat lists (tests or fakes)."""
    results = {"documents": ["a", "b"]}
    assert _first_or_empty(results, "documents") == ["a", "b"]
    assert _first_or_empty(results, "missing_key") == []
