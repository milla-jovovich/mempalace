"""
test_search_similarity_formula.py — A1 (RFC-0028 §4.1).

Verifies that the cosine-distance → similarity mapping grades the full
[0, 2] cosine-distance range. The pre-fix formula `max(0, 1 - dist)`
collapsed every distance ≥ 1.0 to similarity 0.0, hiding the gradient
between weakly-related and unrelated drawers and making the
``similarity`` field useless for ranking, gating, or duplicate scoring.

Post-fix mapping: ``similarity = max(0, (2 - dist) / 2)``
  distance 0.0 → 1.0   (identical)
  distance 0.5 → 0.75
  distance 1.0 → 0.5   (orthogonal — was 0.0 before)
  distance 1.5 → 0.25  (was 0.0 before)
  distance 2.0 → 0.0   (opposite)

Tests stub ChromaDB at the boundary so the assertions exercise only the
response-building code paths, independent of the embedder used to seed
the palace.
"""

from unittest.mock import MagicMock


def _build_results(distances):
    """Build a chromadb query-response shape with N drawers at given distances."""
    n = len(distances)
    return {
        "ids": [[f"d_{i}" for i in range(n)]],
        "documents": [[f"text {i}" for i in range(n)]],
        "metadatas": [
            [
                {"wing": "w", "room": "r", "source_file": f"f_{i}.md", "filed_at": "2026-04-26"}
                for i in range(n)
            ]
        ],
        "distances": [list(distances)],
    }


def _stub_chroma(distances):
    """Drop-in collection that returns a fixed distance list for query()."""
    fake = MagicMock()
    fake.query.return_value = _build_results(distances)
    fake.get.return_value = {"ids": [], "documents": [], "metadatas": []}
    return fake


def test_similarity_grades_full_distance_range(monkeypatch, tmp_path):
    """search_memories should produce a similarity > 0 for every distance < 2.0."""
    from mempalace import searcher

    distances = [0.0, 0.5, 1.0, 1.5, 1.9]

    monkeypatch.setattr(searcher, "get_collection", lambda *a, **k: _stub_chroma(distances))
    monkeypatch.setattr(
        searcher,
        "get_closets_collection",
        lambda *a, **k: (_ for _ in ()).throw(Exception("no closets")),
    )

    result = searcher.search_memories(
        query="anything",
        palace_path=str(tmp_path),
        n_results=len(distances),
        max_distance=2.0,
    )

    sims = [r["similarity"] for r in result["results"]]
    # Every result should have a strictly positive similarity except the absolute opposite.
    assert all(s > 0.0 for s in sims), f"some sim collapsed to 0: {sims}"
    # Identical at distance 0 stays 1.0.
    assert sims[0] == 1.0
    # Orthogonal (distance 1.0) is the midpoint.
    assert abs(sims[2] - 0.5) < 1e-9
    # Monotonic decreasing as distance grows.
    for a, b in zip(sims, sims[1:]):
        assert a > b, f"non-monotonic similarity: {sims}"


def test_similarity_orthogonal_is_half_not_zero(monkeypatch, tmp_path):
    """The pre-fix formula returned 0 for distance 1.0; the fix returns 0.5."""
    from mempalace import searcher

    monkeypatch.setattr(searcher, "get_collection", lambda *a, **k: _stub_chroma([1.0]))
    monkeypatch.setattr(
        searcher,
        "get_closets_collection",
        lambda *a, **k: (_ for _ in ()).throw(Exception("no closets")),
    )

    result = searcher.search_memories(
        query="x",
        palace_path=str(tmp_path),
        n_results=1,
        max_distance=2.0,
    )
    assert result["results"][0]["similarity"] == 0.5


def test_check_duplicate_similarity_consistent_with_search(monkeypatch, palace_path, kg, config):
    """tool_check_duplicate must use the same cosine-distance → similarity formula
    as search; otherwise duplicate detection silently misses near-matches whose
    cosine distance crosses 1.0."""
    from mempalace import mcp_server

    monkeypatch.setattr(mcp_server, "_config", config)
    monkeypatch.setattr(mcp_server, "_kg", kg)

    fake = MagicMock()
    fake.query.return_value = _build_results([0.05, 1.10])
    monkeypatch.setattr(mcp_server, "_get_collection", lambda *a, **k: fake)

    # Threshold 0.4 should match d_1 (similarity = (2 - 1.10) / 2 = 0.45) under the
    # new formula. Pre-fix `1 - dist` would have given negative similarity → no match.
    result = mcp_server.tool_check_duplicate("anything", threshold=0.4)
    assert result["is_duplicate"] is True
    matched_ids = {m["id"] for m in result["matches"]}
    assert "d_0" in matched_ids and "d_1" in matched_ids
