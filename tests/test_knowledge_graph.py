"""
Tests for knowledge_graph.py — Temporal Entity-Relationship Graph.

Covers:
  - Entity CRUD (add, update, properties)
  - Triple creation with auto-entity, dedup, and temporal validity
  - Querying by entity (outgoing, incoming, both directions)
  - Temporal filtering with as_of parameter
  - Fact invalidation and its effect on queries
  - Relationship-type queries
  - Timeline generation (chronological ordering)
  - Statistics (entity/triple/current/expired counts)
  - Seeding from structured entity facts
"""

import os
import json
import tempfile
import shutil

from mempalace.knowledge_graph import KnowledgeGraph


def _make_kg():
    """Create a KnowledgeGraph in a temp directory for isolated testing."""
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test_kg.sqlite3")
    return KnowledgeGraph(db_path=db_path), tmpdir


# ── Entity operations ──────────────────────────────────────────────────


def test_add_entity_basic():
    """Adding an entity returns a normalized ID (lowercase, underscores)."""
    kg, tmpdir = _make_kg()
    try:
        eid = kg.add_entity("Alice Smith", entity_type="person")
        assert eid == "alice_smith"
    finally:
        shutil.rmtree(tmpdir)


def test_add_entity_with_properties():
    """Entity properties are stored as JSON and survive round-trip."""
    kg, tmpdir = _make_kg()
    try:
        props = {"birthday": "1990-05-15", "gender": "female"}
        kg.add_entity("Alice", entity_type="person", properties=props)

        conn = kg._conn()
        row = conn.execute("SELECT properties FROM entities WHERE id = ?", ("alice",)).fetchone()
        conn.close()

        stored_props = json.loads(row[0])
        assert stored_props["birthday"] == "1990-05-15"
        assert stored_props["gender"] == "female"
    finally:
        shutil.rmtree(tmpdir)


def test_add_entity_updates_existing():
    """Re-adding an entity with the same name updates type and properties."""
    kg, tmpdir = _make_kg()
    try:
        kg.add_entity("Bob", entity_type="person")
        kg.add_entity("Bob", entity_type="developer", properties={"lang": "python"})

        conn = kg._conn()
        row = conn.execute(
            "SELECT type, properties FROM entities WHERE id = ?", ("bob",)
        ).fetchone()
        conn.close()

        assert row[0] == "developer"
        assert "python" in row[1]
    finally:
        shutil.rmtree(tmpdir)


# ── Triple operations ──────────────────────────────────────────────────


def test_add_triple_creates_entities_automatically():
    """Adding a triple auto-creates subject and object entities if missing."""
    kg, tmpdir = _make_kg()
    try:
        kg.add_triple("Kai", "works_on", "Orion", valid_from="2025-06-01")

        conn = kg._conn()
        entities = conn.execute("SELECT id FROM entities").fetchall()
        conn.close()

        entity_ids = {row[0] for row in entities}
        assert "kai" in entity_ids
        assert "orion" in entity_ids
    finally:
        shutil.rmtree(tmpdir)


def test_add_triple_returns_triple_id():
    """Adding a triple returns a string ID starting with 't_'."""
    kg, tmpdir = _make_kg()
    try:
        tid = kg.add_triple("Alice", "loves", "Chess")
        assert isinstance(tid, str)
        assert tid.startswith("t_")
    finally:
        shutil.rmtree(tmpdir)


def test_add_triple_prevents_duplicate_active():
    """Adding the same active triple twice returns the existing ID, not a new one."""
    kg, tmpdir = _make_kg()
    try:
        tid1 = kg.add_triple("Kai", "works_on", "Orion")
        tid2 = kg.add_triple("Kai", "works_on", "Orion")
        assert tid1 == tid2
    finally:
        shutil.rmtree(tmpdir)


def test_add_triple_with_confidence():
    """Triple confidence value is stored correctly."""
    kg, tmpdir = _make_kg()
    try:
        kg.add_triple("Alice", "prefers", "Python", confidence=0.8)

        conn = kg._conn()
        row = conn.execute(
            "SELECT confidence FROM triples WHERE subject = ? AND predicate = ?",
            ("alice", "prefers"),
        ).fetchone()
        conn.close()

        assert row[0] == 0.8
    finally:
        shutil.rmtree(tmpdir)


# ── Query operations ──────────────────────────────────────────────────


def test_query_entity_outgoing():
    """Default query returns outgoing relationships from an entity."""
    kg, tmpdir = _make_kg()
    try:
        kg.add_triple("Kai", "works_on", "Orion")
        kg.add_triple("Kai", "loves", "Rust")

        results = kg.query_entity("Kai")
        assert len(results) == 2
        assert all(r["direction"] == "outgoing" for r in results)
        predicates = {r["predicate"] for r in results}
        assert "works_on" in predicates
        assert "loves" in predicates
    finally:
        shutil.rmtree(tmpdir)


def test_query_entity_incoming():
    """Incoming query finds relationships where the entity is the object."""
    kg, tmpdir = _make_kg()
    try:
        kg.add_triple("Kai", "works_on", "Orion")
        kg.add_triple("Maya", "works_on", "Orion")

        results = kg.query_entity("Orion", direction="incoming")
        assert len(results) == 2
        assert all(r["direction"] == "incoming" for r in results)
        subjects = {r["subject"] for r in results}
        assert "Kai" in subjects
        assert "Maya" in subjects
    finally:
        shutil.rmtree(tmpdir)


def test_query_entity_both_directions():
    """Direction='both' returns both incoming and outgoing relationships."""
    kg, tmpdir = _make_kg()
    try:
        kg.add_triple("Alice", "manages", "Bob")
        kg.add_triple("Bob", "works_on", "Orion")

        results = kg.query_entity("Bob", direction="both")
        directions = {r["direction"] for r in results}
        assert "incoming" in directions
        assert "outgoing" in directions
    finally:
        shutil.rmtree(tmpdir)


def test_query_entity_temporal_filtering():
    """as_of parameter correctly filters facts by temporal validity window."""
    kg, tmpdir = _make_kg()
    try:
        kg.add_triple(
            "Maya", "assigned_to", "auth-migration", valid_from="2026-01-15", valid_to="2026-02-15"
        )
        kg.add_triple("Maya", "assigned_to", "billing-refactor", valid_from="2026-03-01")

        # During auth-migration period
        jan_results = kg.query_entity("Maya", as_of="2026-01-20")
        assert len(jan_results) == 1
        assert jan_results[0]["object"] == "auth-migration"

        # After auth-migration ended, during billing-refactor
        mar_results = kg.query_entity("Maya", as_of="2026-03-15")
        assert len(mar_results) == 1
        assert mar_results[0]["object"] == "billing-refactor"
    finally:
        shutil.rmtree(tmpdir)


# ── Invalidation ──────────────────────────────────────────────────────


def test_invalidate_sets_valid_to():
    """Invalidating a fact sets its valid_to date."""
    kg, tmpdir = _make_kg()
    try:
        kg.add_triple("Kai", "works_on", "Orion")
        kg.invalidate("Kai", "works_on", "Orion", ended="2026-03-01")

        conn = kg._conn()
        row = conn.execute(
            "SELECT valid_to FROM triples WHERE subject = ? AND predicate = ?",
            ("kai", "works_on"),
        ).fetchone()
        conn.close()

        assert row[0] == "2026-03-01"
    finally:
        shutil.rmtree(tmpdir)


def test_invalidated_fact_not_in_current_query():
    """Once invalidated, a fact should not appear in current (no as_of) queries
    that check valid_to IS NULL. But query_entity without as_of returns all facts."""
    kg, tmpdir = _make_kg()
    try:
        kg.add_triple("Kai", "works_on", "Orion", valid_from="2025-01-01")
        kg.invalidate("Kai", "works_on", "Orion", ended="2026-03-01")

        results = kg.query_entity("Kai")
        # The fact still appears but should show current=False
        assert len(results) == 1
        assert results[0]["current"] is False
    finally:
        shutil.rmtree(tmpdir)


# ── Relationship queries ──────────────────────────────────────────────


def test_query_relationship_by_predicate():
    """query_relationship returns all triples with a given predicate type."""
    kg, tmpdir = _make_kg()
    try:
        kg.add_triple("Kai", "works_on", "Orion")
        kg.add_triple("Maya", "works_on", "Driftwood")
        kg.add_triple("Kai", "loves", "Rust")

        results = kg.query_relationship("works_on")
        assert len(results) == 2
        subjects = {r["subject"] for r in results}
        assert "Kai" in subjects
        assert "Maya" in subjects
    finally:
        shutil.rmtree(tmpdir)


# ── Timeline ──────────────────────────────────────────────────────────


def test_timeline_chronological_order():
    """Timeline returns facts sorted by valid_from ascending."""
    kg, tmpdir = _make_kg()
    try:
        kg.add_triple("Kai", "joined", "Team", valid_from="2023-01-01")
        kg.add_triple("Kai", "promoted_to", "Senior", valid_from="2025-06-01")
        kg.add_triple("Kai", "works_on", "Orion", valid_from="2024-03-01")

        timeline = kg.timeline("Kai")
        dates = [t["valid_from"] for t in timeline if t["valid_from"]]
        assert dates == sorted(dates)
    finally:
        shutil.rmtree(tmpdir)


def test_timeline_entity_filter():
    """Timeline with entity_name only returns facts involving that entity."""
    kg, tmpdir = _make_kg()
    try:
        kg.add_triple("Kai", "works_on", "Orion", valid_from="2024-01-01")
        kg.add_triple("Maya", "works_on", "Driftwood", valid_from="2024-02-01")

        timeline = kg.timeline("Kai")
        # Only Kai-related facts
        entities_in_timeline = set()
        for t in timeline:
            entities_in_timeline.add(t["subject"])
            entities_in_timeline.add(t["object"])
        assert "Kai" in entities_in_timeline
        assert "Maya" not in entities_in_timeline
    finally:
        shutil.rmtree(tmpdir)


# ── Stats ─────────────────────────────────────────────────────────────


def test_stats_counts():
    """Stats correctly counts entities, triples, current, and expired facts."""
    kg, tmpdir = _make_kg()
    try:
        kg.add_triple("Alice", "knows", "Bob", valid_from="2025-01-01")
        kg.add_triple("Alice", "works_on", "Orion", valid_from="2025-01-01")
        kg.add_triple("Bob", "loves", "Chess", valid_from="2025-01-01")
        kg.invalidate("Alice", "works_on", "Orion", ended="2026-01-01")

        stats = kg.stats()
        assert stats["entities"] == 4  # Alice, Bob, Orion, Chess
        assert stats["triples"] == 3
        assert stats["current_facts"] == 2
        assert stats["expired_facts"] == 1
        assert "knows" in stats["relationship_types"]
        assert "works_on" in stats["relationship_types"]
        assert "loves" in stats["relationship_types"]
    finally:
        shutil.rmtree(tmpdir)


# ── Seeding ───────────────────────────────────────────────────────────


def test_seed_from_entity_facts():
    """seed_from_entity_facts creates entities and relationships from a dict."""
    kg, tmpdir = _make_kg()
    try:
        facts = {
            "max": {
                "full_name": "Max",
                "type": "person",
                "gender": "male",
                "birthday": "2015-04-01",
                "relationship": "daughter",
                "parent": "alice",
                "interests": ["swimming", "chess"],
            }
        }
        kg.seed_from_entity_facts(facts)

        stats = kg.stats()
        assert stats["entities"] >= 2  # Max + Alice at minimum
        assert stats["triples"] >= 2  # is_child_of + interests

        # Verify interests were added
        results = kg.query_entity("Max")
        predicates = {r["predicate"] for r in results}
        assert "loves" in predicates
    finally:
        shutil.rmtree(tmpdir)
