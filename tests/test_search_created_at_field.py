"""
test_search_created_at_field.py — A4 (RFC-0028 §4.4).

The search response builder exposes a ``created_at`` field so callers can
sort or display when each result was filed. Drawer metadata uses the
``filed_at`` key (not ``created_at``); the response builder reads
``filed_at`` first, then falls back to ``created_at`` for legacy palaces
that pre-date the rename, and only returns ``"unknown"`` when neither
key exists.

The bug pattern that motivated this test was a search response where
``created_at`` was always the literal string ``"unknown"`` even though
the underlying drawer had a known ``filed_at`` timestamp. The pre-fix
code did ``meta.get("created_at", "unknown")`` — never reading the key
the rest of the lib actually writes.
"""

from unittest.mock import MagicMock


def _build_results_with_meta(metas):
    n = len(metas)
    return {
        "ids": [[f"d_{i}" for i in range(n)]],
        "documents": [[f"text {i}" for i in range(n)]],
        "metadatas": [list(metas)],
        "distances": [[0.1] * n],
    }


def _stub_chroma(metas):
    fake = MagicMock()
    fake.query.return_value = _build_results_with_meta(metas)
    fake.get.return_value = {"ids": [], "documents": [], "metadatas": []}
    return fake


def test_search_response_uses_filed_at(monkeypatch, tmp_path):
    """When metadata carries ``filed_at``, the search response surfaces it as ``created_at``."""
    from mempalace import searcher

    metas = [
        {"wing": "w", "room": "r", "source_file": "a.md", "filed_at": "2026-01-15T12:00:00"}
    ]
    monkeypatch.setattr(searcher, "get_collection", lambda *a, **k: _stub_chroma(metas))
    monkeypatch.setattr(
        searcher,
        "get_closets_collection",
        lambda *a, **k: (_ for _ in ()).throw(Exception("no closets")),
    )

    result = searcher.search_memories(
        query="x", palace_path=str(tmp_path), n_results=1, max_distance=2.0
    )
    assert result["results"][0]["created_at"] == "2026-01-15T12:00:00"


def test_search_response_falls_back_to_created_at(monkeypatch, tmp_path):
    """Legacy palaces that wrote ``created_at`` instead of ``filed_at`` still surface a value."""
    from mempalace import searcher

    metas = [
        {"wing": "w", "room": "r", "source_file": "legacy.md", "created_at": "2025-09-01T08:00:00"}
    ]
    monkeypatch.setattr(searcher, "get_collection", lambda *a, **k: _stub_chroma(metas))
    monkeypatch.setattr(
        searcher,
        "get_closets_collection",
        lambda *a, **k: (_ for _ in ()).throw(Exception("no closets")),
    )

    result = searcher.search_memories(
        query="x", palace_path=str(tmp_path), n_results=1, max_distance=2.0
    )
    assert result["results"][0]["created_at"] == "2025-09-01T08:00:00"


def test_search_response_unknown_when_both_missing(monkeypatch, tmp_path):
    """Drawers with neither key surface ``"unknown"`` — preserved for back-compat."""
    from mempalace import searcher

    metas = [{"wing": "w", "room": "r", "source_file": "naked.md"}]
    monkeypatch.setattr(searcher, "get_collection", lambda *a, **k: _stub_chroma(metas))
    monkeypatch.setattr(
        searcher,
        "get_closets_collection",
        lambda *a, **k: (_ for _ in ()).throw(Exception("no closets")),
    )

    result = searcher.search_memories(
        query="x", palace_path=str(tmp_path), n_results=1, max_distance=2.0
    )
    assert result["results"][0]["created_at"] == "unknown"
