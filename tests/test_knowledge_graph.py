from mempalace.knowledge_graph import KnowledgeGraph


def test_add_entity(tmp_dir):
    kg = KnowledgeGraph(db_path=str(tmp_dir / "kg.db"))
    eid = kg.add_entity("Alice", "person", {"gender": "female"})
    assert eid == "alice"


def test_entity_id_normalizes():
    kg = KnowledgeGraph.__new__(KnowledgeGraph)
    assert kg._entity_id("Alice Smith") == "alice_smith"
    assert kg._entity_id("O'Brien") == "obrien"


def test_add_triple_creates_entities(tmp_dir):
    kg = KnowledgeGraph(db_path=str(tmp_dir / "kg.db"))
    tid = kg.add_triple("Max", "child_of", "Alice", valid_from="2015-04-01")
    assert tid.startswith("t_max_child_of_alice_")
    stats = kg.stats()
    assert stats["entities"] == 2
    assert stats["triples"] == 1


def test_add_triple_deduplicates_open(tmp_dir):
    kg = KnowledgeGraph(db_path=str(tmp_dir / "kg.db"))
    id1 = kg.add_triple("Max", "loves", "chess")
    id2 = kg.add_triple("Max", "loves", "chess")
    assert id1 == id2
    assert kg.stats()["triples"] == 1


def test_invalidate(tmp_dir):
    kg = KnowledgeGraph(db_path=str(tmp_dir / "kg.db"))
    kg.add_triple("Max", "has_issue", "injury", valid_from="2026-01-01")
    kg.invalidate("Max", "has_issue", "injury", ended="2026-02-15")
    stats = kg.stats()
    assert stats["current_facts"] == 0
    assert stats["expired_facts"] == 1


def test_query_entity_outgoing(tmp_dir):
    kg = KnowledgeGraph(db_path=str(tmp_dir / "kg.db"))
    kg.add_triple("Max", "loves", "chess")
    kg.add_triple("Max", "does", "swimming")
    results = kg.query_entity("Max", direction="outgoing")
    predicates = {r["predicate"] for r in results}
    assert predicates == {"loves", "does"}
    assert all(r["direction"] == "outgoing" for r in results)


def test_query_entity_incoming(tmp_dir):
    kg = KnowledgeGraph(db_path=str(tmp_dir / "kg.db"))
    kg.add_triple("Max", "child_of", "Alice")
    results = kg.query_entity("Alice", direction="incoming")
    assert len(results) == 1
    assert results[0]["subject"] == "Max"
    assert results[0]["direction"] == "incoming"


def test_query_entity_both(tmp_dir):
    kg = KnowledgeGraph(db_path=str(tmp_dir / "kg.db"))
    kg.add_triple("Max", "child_of", "Alice")
    kg.add_triple("Alice", "married_to", "Jordan")
    results = kg.query_entity("Alice", direction="both")
    assert len(results) == 2


def test_temporal_query_as_of(tmp_dir):
    kg = KnowledgeGraph(db_path=str(tmp_dir / "kg.db"))
    kg.add_triple("Max", "does", "swimming", valid_from="2025-01-01")
    kg.invalidate("Max", "does", "swimming", ended="2025-06-01")
    kg.add_triple("Max", "does", "tennis", valid_from="2025-07-01")

    # In March 2025: swimming was active
    results = kg.query_entity("Max", as_of="2025-03-15", direction="outgoing")
    objects = {r["object"] for r in results}
    assert "swimming" in objects
    assert "tennis" not in objects

    # In August 2025: tennis is active, swimming ended
    results = kg.query_entity("Max", as_of="2025-08-01", direction="outgoing")
    objects = {r["object"] for r in results}
    assert "tennis" in objects
    assert "swimming" not in objects


def test_query_relationship(tmp_dir):
    kg = KnowledgeGraph(db_path=str(tmp_dir / "kg.db"))
    kg.add_triple("Max", "loves", "chess")
    kg.add_triple("Alice", "loves", "painting")
    results = kg.query_relationship("loves")
    subjects = {r["subject"] for r in results}
    assert subjects == {"Max", "Alice"}


def test_timeline_ordered(tmp_dir):
    kg = KnowledgeGraph(db_path=str(tmp_dir / "kg.db"))
    kg.add_triple("Max", "born", "world", valid_from="2015-04-01")
    kg.add_triple("Max", "started", "school", valid_from="2021-09-01")
    kg.add_triple("Max", "loves", "chess", valid_from="2024-01-01")
    tl = kg.timeline("Max")
    dates = [e["valid_from"] for e in tl]
    assert dates == ["2015-04-01", "2021-09-01", "2024-01-01"]


def test_timeline_global(tmp_dir):
    kg = KnowledgeGraph(db_path=str(tmp_dir / "kg.db"))
    kg.add_triple("Max", "born", "world", valid_from="2015-01-01")
    kg.add_triple("Alice", "started", "job", valid_from="2020-01-01")
    tl = kg.timeline()
    assert len(tl) == 2


def test_stats(tmp_dir):
    kg = KnowledgeGraph(db_path=str(tmp_dir / "kg.db"))
    kg.add_triple("Max", "loves", "chess")
    kg.add_triple("Max", "does", "swimming")
    kg.invalidate("Max", "does", "swimming", ended="2026-01-01")
    stats = kg.stats()
    assert stats["entities"] == 3  # max, chess, swimming
    assert stats["triples"] == 2
    assert stats["current_facts"] == 1
    assert stats["expired_facts"] == 1
    assert set(stats["relationship_types"]) == {"does", "loves"}
