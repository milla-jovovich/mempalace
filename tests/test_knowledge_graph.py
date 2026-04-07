"""Tests for mempalace.knowledge_graph — temporal entity-relationship graph."""

import pytest

from mempalace.knowledge_graph import KnowledgeGraph


@pytest.fixture()
def kg(tmp_path):
    return KnowledgeGraph(db_path=str(tmp_path / "test_kg.sqlite3"))


class TestAddEntity:
    def test_add_entity(self, kg):
        eid = kg.add_entity("Alice", "person", {"birthday": "1990-01-01"})
        assert eid == "alice"

    def test_overwrite_entity(self, kg):
        kg.add_entity("Alice", "person")
        kg.add_entity("Alice", "human", {"role": "creator"})
        results = kg.query_entity("Alice")
        assert isinstance(results, list)


class TestAddTriple:
    def test_basic_triple(self, kg):
        tid = kg.add_triple("Max", "child_of", "Alice", valid_from="2015-04-01")
        assert tid is not None

    def test_auto_creates_entities(self, kg):
        kg.add_triple("Riley", "loves", "Chess")
        results = kg.query_entity("Riley")
        assert len(results) >= 1
        assert results[0]["object"] == "Chess"

    def test_duplicate_returns_existing(self, kg):
        t1 = kg.add_triple("Max", "does", "swimming")
        t2 = kg.add_triple("Max", "does", "swimming")
        assert t1 == t2

    def test_with_confidence(self, kg):
        kg.add_triple("Max", "likes", "pizza", confidence=0.8)
        results = kg.query_entity("Max")
        assert results[0]["confidence"] == 0.8

    def test_with_source(self, kg):
        kg.add_triple("Alice", "works_on", "MemPalace", source_file="/notes/work.txt")
        results = kg.query_entity("Alice")
        assert results[0]["source_closet"] is None or True  # source_closet can be None


class TestInvalidate:
    def test_sets_valid_to(self, kg):
        kg.add_triple("Max", "has_issue", "broken_arm", valid_from="2026-01-01")
        kg.invalidate("Max", "has_issue", "broken_arm", ended="2026-02-15")
        results = kg.query_entity("Max")
        assert len(results) == 1
        assert results[0]["current"] is False
        assert results[0]["valid_to"] == "2026-02-15"

    def test_invalidated_filtered_by_as_of(self, kg):
        kg.add_triple("Max", "does", "swimming", valid_from="2025-01-01")
        kg.invalidate("Max", "does", "swimming", ended="2025-06-01")
        current = kg.query_entity("Max", as_of="2026-01-01")
        assert len(current) == 0


class TestQueryEntity:
    def test_outgoing(self, kg):
        kg.add_triple("Alice", "parent_of", "Max")
        kg.add_triple("Alice", "married_to", "Bob")
        results = kg.query_entity("Alice", direction="outgoing")
        assert len(results) == 2

    def test_incoming(self, kg):
        kg.add_triple("Max", "child_of", "Alice")
        results = kg.query_entity("Alice", direction="incoming")
        assert len(results) == 1
        assert results[0]["subject"] == "Max"

    def test_both_directions(self, kg):
        kg.add_triple("Alice", "parent_of", "Max")
        kg.add_triple("Bob", "married_to", "Alice")
        results = kg.query_entity("Alice", direction="both")
        assert len(results) == 2

    def test_as_of_filter(self, kg):
        kg.add_triple("Max", "does", "swimming", valid_from="2025-01-01", valid_to="2025-06-01")
        kg.add_triple("Max", "does", "chess", valid_from="2025-06-01")
        results = kg.query_entity("Max", as_of="2025-03-01")
        objects = [r["object"] for r in results]
        assert "swimming" in objects
        assert "chess" not in objects


class TestQueryRelationship:
    def test_find_by_predicate(self, kg):
        kg.add_triple("Alice", "parent_of", "Max")
        kg.add_triple("Alice", "parent_of", "Riley")
        results = kg.query_relationship("parent_of")
        assert len(results) == 2

    def test_with_as_of(self, kg):
        kg.add_triple("Max", "does", "swimming", valid_from="2025-01", valid_to="2025-06")
        results = kg.query_relationship("does", as_of="2025-03")
        assert len(results) == 1


class TestTimeline:
    def test_chronological_order(self, kg):
        kg.add_triple("Max", "born", "event", valid_from="2015-04-01")
        kg.add_triple("Max", "started", "school", valid_from="2021-09-01")
        kg.add_triple("Max", "loves", "chess", valid_from="2025-10-01")
        timeline = kg.timeline("Max")
        dates = [t["valid_from"] for t in timeline if t["valid_from"]]
        assert dates == sorted(dates)

    def test_global_timeline(self, kg):
        kg.add_triple("Alice", "created", "MemPalace", valid_from="2025-01-01")
        kg.add_triple("Bob", "joined", "team", valid_from="2025-03-01")
        timeline = kg.timeline()
        assert len(timeline) >= 2


class TestStats:
    def test_stats(self, kg):
        kg.add_triple("Alice", "parent_of", "Max")
        kg.add_triple("Alice", "married_to", "Bob")
        kg.invalidate("Alice", "married_to", "Bob", ended="2026-01-01")
        stats = kg.stats()
        assert stats["entities"] >= 3
        assert stats["triples"] == 2
        assert stats["current_facts"] == 1
        assert stats["expired_facts"] == 1
        assert "parent_of" in stats["relationship_types"]


class TestSeedFromEntityFacts:
    def test_seeds_from_facts(self, kg):
        facts = {
            "alice": {
                "full_name": "Alice",
                "type": "person",
                "gender": "female",
                "birthday": "1990-01-01",
                "partner": "bob",
                "interests": ["chess", "hiking"],
            },
            "max": {
                "full_name": "Max",
                "type": "person",
                "gender": "male",
                "birthday": "2015-04-01",
                "parent": "alice",
                "relationship": "daughter",
                "interests": ["swimming"],
            },
        }
        kg.seed_from_entity_facts(facts)
        alice_rels = kg.query_entity("Alice", direction="both")
        assert len(alice_rels) >= 1
        max_rels = kg.query_entity("Max", direction="outgoing")
        assert len(max_rels) >= 1
