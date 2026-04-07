"""Tests for searcher.py — verifies sys.exit replaced with RuntimeError."""

import tempfile
import pytest
from mempalace.searcher import search, search_memories


def test_search_raises_on_missing_palace():
    """search() must raise RuntimeError, not sys.exit, when palace is missing."""
    with pytest.raises(RuntimeError, match="No palace found"):
        search("test query", palace_path="/nonexistent/palace/path")


def test_search_memories_returns_error_dict():
    """search_memories() must return error dict, never sys.exit."""
    result = search_memories("test query", palace_path="/nonexistent/palace/path")
    assert "error" in result
    assert "No palace found" in result["error"]


def test_search_returns_results(tmp_path):
    """search() works normally when palace exists with data."""
    import chromadb

    palace_path = str(tmp_path / "palace")
    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_or_create_collection("mempalace_drawers")
    col.add(
        ids=["test1"],
        documents=["The quick brown fox jumps over the lazy dog"],
        metadatas=[{"wing": "test", "room": "general", "source_file": "test.txt"}],
    )
    # Should not raise
    search("fox", palace_path=palace_path, n_results=1)


def test_search_memories_returns_hits(tmp_path):
    """search_memories() returns structured results when palace has data."""
    import chromadb

    palace_path = str(tmp_path / "palace")
    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_or_create_collection("mempalace_drawers")
    col.add(
        ids=["test1"],
        documents=["Memory about artificial intelligence"],
        metadatas=[{"wing": "tech", "room": "ai", "source_file": "notes.md"}],
    )
    result = search_memories("artificial intelligence", palace_path=palace_path, n_results=1)
    assert "results" in result
    assert len(result["results"]) == 1
    assert result["results"][0]["wing"] == "tech"
