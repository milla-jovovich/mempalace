"""
test_knowledge_graph.py — Tests for the temporal knowledge graph.

Covers: entity CRUD, triple CRUD, temporal queries, invalidation,
timeline, stats, and edge cases (duplicate triples, ID collisions).
"""

import pytest


class TestEntityOperations:
    def test_add_entity(self, kg):
        eid = kg.add_entity("Alice", entity_type="person")
        assert eid == "alice"

    def test_add_entity_normalizes_id(self, kg):
        eid = kg.add_entity("Dr. Chen", entity_type="person")
        assert eid == "dr._chen"

    def test_add_entity_upsert(self, kg):
        kg.add_entity("Alice", entity_type="person")
        kg.add_entity("Alice", entity_type="engineer")
        # Should not raise — INSERT OR REPLACE
        stats = kg.stats()
        assert stats["entities"] == 1


class TestTripleOperations:
    def test_add_triple_creates_entities(self, kg):
        tid = kg.add_triple("Alice", "knows", "Bob")
        assert tid.startswith("t_alice_knows_bob_")
        stats = kg.stats()
        assert stats["entities"] == 2  # auto-created

    def test_add_triple_with_dates(self, kg):
        tid = kg.add_triple("Max", "does", "swimming", valid_from="2025-01-01")
        assert tid.startswith("t_max_does_swimming_")

    def test_duplicate_triple_returns_existing_id(self, kg):
        tid1 = kg.add_triple("Alice", "knows", "Bob")
        tid2 = kg.add_triple("Alice", "knows", "Bob")
        assert tid1 == tid2

    def test_invalidated_triple_allows_re_add(self, kg):
        tid1 = kg.add_triple("Alice", "works_at", "Acme")
        kg.invalidate("Alice", "works_at", "Acme", ended="2025-01-01")
        tid2 = kg.add_triple("Alice", "works_at", "Acme")
        assert tid1 != tid2  # new triple since old one was closed


class TestQueries:
    def test_query_outgoing(self, seeded_kg):
        results = seeded_kg.query_entity("Alice", direction="outgoing")
        predicates = {r["predicate"] for r in results}
        assert "parent_of" in predicates
        assert "works_at" in predicates

    def test_query_incoming(self, seeded_kg):
        results = seeded_kg.query_entity("Max", direction="incoming")
        assert any(r["subject"] == "Alice" and r["predicate"] == "parent_of" for r in results)

    def test_query_both_directions(self, seeded_kg):
        results = seeded_kg.query_entity("Max", direction="both")
        directions = {r["direction"] for r in results}
        assert "outgoing" in directions
        assert "incoming" in directions

    def test_query_as_of_filters_expired(self, seeded_kg):
        results = seeded_kg.query_entity("Alice", as_of="2023-06-01", direction="outgoing")
        employers = [r["object"] for r in results if r["predicate"] == "works_at"]
        assert "Acme Corp" in employers
        assert "NewCo" not in employers

    def test_query_as_of_shows_current(self, seeded_kg):
        results = seeded_kg.query_entity("Alice", as_of="2025-06-01", direction="outgoing")
        employers = [r["object"] for r in results if r["predicate"] == "works_at"]
        assert "NewCo" in employers
        assert "Acme Corp" not in employers

    def test_query_relationship(self, seeded_kg):
        results = seeded_kg.query_relationship("does")
        assert len(results) == 2  # swimming + chess


class TestInvalidation:
    def test_invalidate_sets_valid_to(self, seeded_kg):
        seeded_kg.invalidate("Max", "does", "chess", ended="2026-01-01")
        results = seeded_kg.query_entity("Max", direction="outgoing")
        chess = [r for r in results if r["object"] == "chess"]
        assert len(chess) == 1
        assert chess[0]["valid_to"] == "2026-01-01"
        assert chess[0]["current"] is False


class TestTimeline:
    def test_timeline_all(self, seeded_kg):
        tl = seeded_kg.timeline()
        assert len(tl) >= 4

    def test_timeline_entity(self, seeded_kg):
        tl = seeded_kg.timeline("Max")
        subjects_and_objects = {t["subject"] for t in tl} | {t["object"] for t in tl}
        assert "Max" in subjects_and_objects

    def test_timeline_global_has_limit(self, kg):
        # Add > 100 triples
        for i in range(105):
            kg.add_triple(f"entity_{i}", "relates_to", f"entity_{i + 1}")
        tl = kg.timeline()
        assert len(tl) == 100  # LIMIT 100

    def test_timeline_entity_has_limit(self, kg):
        # Add > 100 triples all connected to a single entity
        for i in range(105):
            kg.add_triple(
                "hub", "connects_to", f"spoke_{i}", valid_from=f"2025-01-{(i % 28) + 1:02d}"
            )
        tl = kg.timeline("hub")
        assert len(tl) == 100  # LIMIT 100 on entity-filtered branch


class TestWALMode:
    def test_wal_mode_enabled(self, kg):
        conn = kg._conn()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"


class TestStats:
    def test_stats_empty(self, kg):
        stats = kg.stats()
        assert stats["entities"] == 0
        assert stats["triples"] == 0

    def test_stats_seeded(self, seeded_kg):
        stats = seeded_kg.stats()
        assert stats["entities"] >= 4
        assert stats["triples"] == 5
        assert stats["current_facts"] == 4  # 1 expired (Acme Corp)
        assert stats["expired_facts"] == 1


def test_fts5_trigram_substring_lookup(tmp_path):
    from mempalace.knowledge_graph import KnowledgeGraph

    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    kg.add_entity("Alice Smith", entity_type="person")
    kg.add_entity("Ben Jones", entity_type="person")
    kg.add_entity("Carol Alice-Jones", entity_type="person")

    matches = kg.find_entities_by_name_trigram("alice")
    names = {m["name"] for m in matches}
    assert "Alice Smith" in names
    assert "Carol Alice-Jones" in names
    assert "Ben Jones" not in names


def test_fts5_index_stays_in_sync_on_delete(tmp_path):
    from mempalace.knowledge_graph import KnowledgeGraph

    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    kg.add_entity("Alice", entity_type="person")
    conn = kg._conn()
    with conn:
        conn.execute("DELETE FROM entities WHERE id=?", (kg._entity_id("Alice"),))
    matches = kg.find_entities_by_name_trigram("alice")
    assert matches == []


def test_fts5_backfill_idempotent_on_repeat_init(tmp_path):
    """Repeat KnowledgeGraph() opens should not duplicate rows in FTS."""
    from mempalace.knowledge_graph import KnowledgeGraph

    db_path = str(tmp_path / "kg.db")
    kg1 = KnowledgeGraph(db_path)
    kg1.add_entity("Alice", entity_type="person")

    kg2 = KnowledgeGraph(db_path)
    n = kg2._conn().execute("SELECT COUNT(*) FROM entities_name_fts").fetchone()[0]
    assert n == 1


def test_fts5_no_duplicates_on_repeated_add_entity(tmp_path):
    """Calling add_entity multiple times on the same entity must not accumulate
    duplicate FTS rows. INSERT OR REPLACE fires AFTER DELETE then AFTER INSERT;
    the delete trigger must remove old rows via rowid to avoid accumulation."""
    from mempalace.knowledge_graph import KnowledgeGraph

    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    kg.add_entity("Alice", entity_type="person")
    kg.add_entity("Alice", entity_type="person")
    kg.add_entity("Alice", entity_type="person")

    n = kg._conn().execute("SELECT COUNT(*) FROM entities_name_fts").fetchone()[0]
    assert n == 1, f"Expected 1 FTS row, got {n} — rowid-based delete trigger broken"


def test_source_drawer_ids_column_added_on_init(tmp_path):
    from mempalace.knowledge_graph import KnowledgeGraph

    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    cur = kg._conn().execute("PRAGMA table_info(triples)")
    columns = [row[1] for row in cur.fetchall()]
    assert "source_drawer_ids" in columns
    assert "source" in columns


def test_new_columns_accept_null_and_values(tmp_path):
    import sqlite3
    from mempalace.knowledge_graph import KnowledgeGraph

    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    kg.add_entity("Alice", entity_type="person")
    kg.add_entity("Ben", entity_type="person")

    conn = kg._conn()
    with conn:
        conn.execute(
            "INSERT INTO triples (id, subject, predicate, object, "
            "source_drawer_ids, source) VALUES (?, ?, ?, ?, ?, ?)",
            ("t1", "alice", "knows", "ben", None, None),
        )
        conn.execute(
            "INSERT INTO triples (id, subject, predicate, object, "
            "source_drawer_ids, source) VALUES (?, ?, ?, ?, ?, ?)",
            ("t2", "ben", "knows", "alice", '[\"drw_a\", \"drw_b\"]', "extractor_v3"),
        )

    rows = dict(
        (r["id"], (r["source_drawer_ids"], r["source"]))
        for r in conn.execute(
            "SELECT id, source_drawer_ids, source FROM triples "
            "WHERE id IN ('t1', 't2')"
        )
    )
    assert rows["t1"] == (None, None)
    assert rows["t2"] == ('[\"drw_a\", \"drw_b\"]', "extractor_v3")


def test_old_palace_upgrades_cleanly(tmp_path):
    """A palace created without the new columns should ALTER cleanly."""
    import sqlite3

    db_path = tmp_path / "kg.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE entities (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'unknown',
            properties TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE triples (
            id TEXT PRIMARY KEY,
            subject TEXT NOT NULL REFERENCES entities(id),
            predicate TEXT NOT NULL,
            object TEXT NOT NULL REFERENCES entities(id),
            valid_from TEXT,
            valid_to TEXT,
            confidence REAL NOT NULL DEFAULT 1.0,
            source_closet TEXT,
            source_file TEXT,
            extracted_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

    from mempalace.knowledge_graph import KnowledgeGraph
    kg = KnowledgeGraph(str(db_path))
    cur = kg._conn().execute("PRAGMA table_info(triples)")
    columns = [row[1] for row in cur.fetchall()]
    assert "source_drawer_ids" in columns
    assert "source" in columns


def test_upsert_triple_inserts_new(tmp_path):
    from mempalace.knowledge_graph import KnowledgeGraph

    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    result = kg.upsert_triple(
        subject="Alice",
        predicate="knows",
        obj="Ben",
        confidence=0.9,
        source="extractor_v3",
    )
    assert result.inserted is True
    assert result.updated is False
    assert result.triple_id is not None

    rows = kg._conn().execute(
        "SELECT confidence, source FROM triples WHERE id=?", (result.triple_id,)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["confidence"] == pytest.approx(0.9)
    assert rows[0]["source"] == "extractor_v3"


def test_upsert_triple_updates_existing(tmp_path):
    from mempalace.knowledge_graph import KnowledgeGraph

    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    r1 = kg.upsert_triple(subject="Alice", predicate="knows", obj="Ben", confidence=0.5)
    r2 = kg.upsert_triple(
        subject="Alice", predicate="knows", obj="Ben",
        confidence=0.95, source="extractor_v4",
    )
    assert r2.inserted is False
    assert r2.updated is True
    assert r2.triple_id == r1.triple_id

    row = kg._conn().execute(
        "SELECT confidence, source FROM triples WHERE id=?", (r1.triple_id,)
    ).fetchone()
    assert row["confidence"] == pytest.approx(0.95)
    assert row["source"] == "extractor_v4"


def test_upsert_triple_does_not_touch_invalidated(tmp_path):
    from mempalace.knowledge_graph import KnowledgeGraph

    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    r1 = kg.upsert_triple(subject="Alice", predicate="knows", obj="Ben", confidence=0.5)
    kg.invalidate(subject="alice", predicate="knows", obj="ben")
    r2 = kg.upsert_triple(subject="Alice", predicate="knows", obj="Ben", confidence=0.9)
    assert r2.inserted is True  # new live row
    assert r2.triple_id != r1.triple_id  # different id


def test_upsert_triple_race_safe(tmp_path):
    """Concurrent upserts must not raise exceptions or produce duplicate live rows."""
    import threading
    from mempalace.knowledge_graph import KnowledgeGraph

    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    errors = []

    def worker(i):
        try:
            kg.upsert_triple(
                subject="Alice", predicate="knows", obj="Ben",
                confidence=0.5 + i * 0.01,
            )
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert not errors, f"Concurrent upserts raised: {errors}"
    live = kg._conn().execute(
        "SELECT COUNT(*) FROM triples WHERE subject=? AND predicate=? AND object=? AND valid_to IS NULL",
        ("alice", "knows", "ben"),
    ).fetchone()[0]
    assert live == 1


def test_check_triple_conflicts_no_conflict(tmp_path):
    from mempalace.knowledge_graph import KnowledgeGraph

    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    kg.add_triple("Alice", "works_at", obj="Acme")
    conflicts = kg.check_triple_conflicts()
    assert conflicts == []


def test_check_triple_conflicts_detects_relationship_mismatch(tmp_path):
    """Two live triples with same (subject, predicate) but different objects = conflict."""
    from mempalace.knowledge_graph import KnowledgeGraph

    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    # Force two different objects for same (subject, predicate)
    conn = kg._conn()
    with conn:
        kg.add_entity("Alice", entity_type="person")
        kg.add_entity("Acme", entity_type="org")
        kg.add_entity("Globex", entity_type="org")
        conn.execute(
            "INSERT INTO triples (id, subject, predicate, object, confidence) "
            "VALUES (?, ?, ?, ?, ?)",
            ("t1", "alice", "works_at", "acme", 0.9),
        )
        conn.execute(
            "INSERT INTO triples (id, subject, predicate, object, confidence) "
            "VALUES (?, ?, ?, ?, ?)",
            ("t2", "alice", "works_at", "globex", 0.8),
        )

    conflicts = kg.check_triple_conflicts()
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c["type"] == "relationship_mismatch"
    assert c["subject"] == "alice"
    assert c["predicate"] == "works_at"
    assert set(c["conflicting_objects"]) == {"acme", "globex"}


def test_check_triple_conflicts_ignores_invalidated(tmp_path):
    """Invalidated triples must not contribute to conflicts."""
    from mempalace.knowledge_graph import KnowledgeGraph

    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    kg.add_triple("Alice", "works_at", obj="Acme")
    kg.invalidate(subject="alice", predicate="works_at", obj="acme")
    # Now add a different live triple — no conflict (old one is invalidated)
    kg.add_triple("Alice", "works_at", obj="Globex")
    conflicts = kg.check_triple_conflicts()
    assert conflicts == []


def test_read_during_long_write_does_not_block(tmp_path):
    """Reads must not block while a write is in progress (WAL mode)."""
    import threading
    import time
    from mempalace.knowledge_graph import KnowledgeGraph

    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    kg.add_entity("Alice", entity_type="person")

    read_completed = threading.Event()
    write_started = threading.Event()

    def long_write():
        # Do many upserts to hold the write lock
        write_started.set()
        for i in range(200):
            kg.upsert_triple(
                subject="Alice", predicate=f"knows_{i}", obj=f"Entity_{i}",
                confidence=0.5,
            )

    def concurrent_read():
        write_started.wait(timeout=2)
        kg.query_entity("Alice")
        read_completed.set()

    writer = threading.Thread(target=long_write)
    reader = threading.Thread(target=concurrent_read)
    writer.start()
    reader.start()

    read_completed_ok = read_completed.wait(timeout=5)
    writer.join(timeout=10)
    reader.join(timeout=2)

    assert read_completed_ok, "Read timed out — likely blocked by write lock"
