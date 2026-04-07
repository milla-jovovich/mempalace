"""Tests for knowledge_graph.py — verifies named column access after fix."""

import tempfile
import os
from mempalace.knowledge_graph import KnowledgeGraph


def _make_kg(tmp_path):
    db = str(tmp_path / "kg.sqlite3")
    kg = KnowledgeGraph(db_path=db)
    return kg


def test_add_entity_and_triple(tmp_path):
    kg = _make_kg(tmp_path)
    kg.add_entity("Alice", "person")
    kg.add_entity("Chess", "activity")
    tid = kg.add_triple("Alice", "loves", "Chess", valid_from="2025-01-01")
    assert tid is not None


def test_query_entity_outgoing(tmp_path):
    kg = _make_kg(tmp_path)
    kg.add_triple("Alice", "loves", "Chess", valid_from="2025-01-01")
    results = kg.query_entity("Alice", direction="outgoing")
    assert len(results) == 1
    r = results[0]
    assert r["direction"] == "outgoing"
    assert r["subject"] == "Alice"
    assert r["predicate"] == "loves"
    assert r["object"] == "Chess"
    assert r["valid_from"] == "2025-01-01"
    assert r["valid_to"] is None
    assert r["current"] is True


def test_query_entity_incoming(tmp_path):
    kg = _make_kg(tmp_path)
    kg.add_triple("Alice", "parent_of", "Max", valid_from="2015-01-01")
    results = kg.query_entity("Max", direction="incoming")
    assert len(results) == 1
    r = results[0]
    assert r["direction"] == "incoming"
    assert r["subject"] == "Alice"
    assert r["predicate"] == "parent_of"
    assert r["object"] == "Max"


def test_query_entity_both(tmp_path):
    kg = _make_kg(tmp_path)
    kg.add_triple("Alice", "parent_of", "Max")
    kg.add_triple("Max", "loves", "Chess")
    results = kg.query_entity("Max", direction="both")
    assert len(results) == 2
    directions = {r["direction"] for r in results}
    assert directions == {"incoming", "outgoing"}


def test_query_entity_temporal_filter(tmp_path):
    kg = _make_kg(tmp_path)
    kg.add_triple("Max", "does", "Swimming", valid_from="2025-01-01", valid_to="2025-06-01")
    kg.add_triple("Max", "does", "Chess", valid_from="2025-03-01")
    # Query as of April — both should match
    results = kg.query_entity("Max", as_of="2025-04-01")
    assert len(results) == 2
    # Query as of August — only Chess (Swimming expired June)
    results = kg.query_entity("Max", as_of="2025-08-01")
    assert len(results) == 1
    assert results[0]["object"] == "Chess"


def test_query_relationship(tmp_path):
    kg = _make_kg(tmp_path)
    kg.add_triple("Alice", "loves", "Chess")
    kg.add_triple("Max", "loves", "Swimming")
    results = kg.query_relationship("loves")
    assert len(results) == 2
    subjects = {r["subject"] for r in results}
    objects = {r["object"] for r in results}
    assert "Alice" in subjects
    assert "Chess" in objects
    # Verify named fields are populated (not None from wrong index)
    for r in results:
        assert r["subject"] is not None
        assert r["object"] is not None
        assert r["predicate"] == "loves"


def test_timeline(tmp_path):
    kg = _make_kg(tmp_path)
    kg.add_triple("Alice", "loves", "Chess", valid_from="2025-01-01")
    kg.add_triple("Max", "does", "Swimming", valid_from="2025-06-01")
    results = kg.timeline()
    assert len(results) == 2
    # Should be chronological
    assert results[0]["valid_from"] <= results[1]["valid_from"]
    for r in results:
        assert r["subject"] is not None
        assert r["object"] is not None
        assert r["predicate"] is not None


def test_timeline_entity_filter(tmp_path):
    kg = _make_kg(tmp_path)
    kg.add_triple("Alice", "loves", "Chess", valid_from="2025-01-01")
    kg.add_triple("Max", "does", "Swimming", valid_from="2025-06-01")
    results = kg.timeline(entity_name="Alice")
    assert len(results) == 1
    assert results[0]["subject"] == "Alice"


def test_invalidate(tmp_path):
    kg = _make_kg(tmp_path)
    kg.add_triple("Max", "does", "Swimming", valid_from="2025-01-01")
    kg.invalidate("Max", "does", "Swimming", ended="2025-06-01")
    results = kg.query_entity("Max")
    assert len(results) == 1
    assert results[0]["valid_to"] == "2025-06-01"
    assert results[0]["current"] is False


def test_stats(tmp_path):
    kg = _make_kg(tmp_path)
    kg.add_triple("Alice", "loves", "Chess")
    kg.add_triple("Max", "does", "Swimming")
    s = kg.stats()
    assert s["entities"] >= 4  # Alice, Chess, Max, Swimming
    assert s["triples"] == 2
    assert s["current_facts"] == 2
    assert "loves" in s["relationship_types"]
