#![allow(clippy::unwrap_used, clippy::expect_used)]

use mempalace_store::knowledge_graph::{Direction, KnowledgeGraph};
use tempfile::TempDir;

fn fresh_kg() -> (TempDir, KnowledgeGraph) {
    let tmp = TempDir::new().unwrap();
    let db = tmp.path().join("kg.sqlite3");
    let kg = KnowledgeGraph::open(&db).unwrap();
    (tmp, kg)
}

#[test]
fn entity_id_lowers_and_strips_quotes() {
    assert_eq!(KnowledgeGraph::entity_id("Max"), "max");
    assert_eq!(KnowledgeGraph::entity_id("Max O'Neill"), "max_oneill");
    assert_eq!(KnowledgeGraph::entity_id("My Project"), "my_project");
}

#[test]
fn add_entity_creates_node() {
    let (_tmp, kg) = fresh_kg();
    let eid = kg.add_entity("Max", "person", None).unwrap();
    assert_eq!(eid, "max");
}

#[test]
fn add_triple_creates_relationship() {
    let (_tmp, kg) = fresh_kg();
    let id = kg
        .add_triple(
            "Max",
            "child_of",
            "Alice",
            Some("2015-04-01"),
            None,
            1.0,
            None,
            None,
        )
        .unwrap();
    assert!(id.starts_with("t_max_child_of_alice_"));
}

#[test]
fn add_triple_idempotent_when_still_valid() {
    let (_tmp, kg) = fresh_kg();
    let id1 = kg
        .add_triple("Max", "loves", "chess", None, None, 1.0, None, None)
        .unwrap();
    let id2 = kg
        .add_triple("Max", "loves", "chess", None, None, 1.0, None, None)
        .unwrap();
    assert_eq!(id1, id2);
}

#[test]
fn query_entity_outgoing_returns_added_triple() {
    let (_tmp, kg) = fresh_kg();
    kg.add_triple("Max", "does", "swimming", None, None, 1.0, None, None)
        .unwrap();
    let rows = kg.query_entity("Max", None, Direction::Outgoing).unwrap();
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].predicate, "does");
    assert_eq!(rows[0].object, "swimming");
    assert!(rows[0].current);
}

#[test]
fn query_entity_incoming_returns_reverse_relationship() {
    let (_tmp, kg) = fresh_kg();
    kg.add_triple("Max", "child_of", "Alice", None, None, 1.0, None, None)
        .unwrap();
    let rows = kg.query_entity("Alice", None, Direction::Incoming).unwrap();
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].subject, "Max");
    assert_eq!(rows[0].predicate, "child_of");
    assert_eq!(rows[0].object, "Alice");
}

#[test]
fn query_entity_both_returns_incoming_and_outgoing() {
    let (_tmp, kg) = fresh_kg();
    kg.add_triple("Max", "child_of", "Alice", None, None, 1.0, None, None)
        .unwrap();
    kg.add_triple("Alice", "worried_about", "Max", None, None, 1.0, None, None)
        .unwrap();
    let rows = kg.query_entity("Max", None, Direction::Both).unwrap();
    assert_eq!(rows.len(), 2);
}

#[test]
fn as_of_filter_hides_future_facts() {
    let (_tmp, kg) = fresh_kg();
    kg.add_triple(
        "Max",
        "does",
        "swimming",
        Some("2030-01-01"),
        None,
        1.0,
        None,
        None,
    )
    .unwrap();
    let rows = kg
        .query_entity("Max", Some("2025-01-01"), Direction::Outgoing)
        .unwrap();
    assert!(rows.is_empty());
}

#[test]
fn invalidate_sets_valid_to() {
    let (_tmp, kg) = fresh_kg();
    kg.add_triple("Max", "has_issue", "injury", None, None, 1.0, None, None)
        .unwrap();
    let n = kg
        .invalidate("Max", "has_issue", "injury", Some("2026-02-15"))
        .unwrap();
    assert_eq!(n, 1);
    let rows = kg.query_entity("Max", None, Direction::Outgoing).unwrap();
    assert_eq!(rows.len(), 1);
    assert!(!rows[0].current);
    assert_eq!(rows[0].valid_to.as_deref(), Some("2026-02-15"));
}

#[test]
fn query_relationship_returns_all_triples_of_type() {
    let (_tmp, kg) = fresh_kg();
    kg.add_triple("Alice", "loves", "chess", None, None, 1.0, None, None)
        .unwrap();
    kg.add_triple("Bob", "loves", "cards", None, None, 1.0, None, None)
        .unwrap();
    let rows = kg.query_relationship("loves", None).unwrap();
    assert_eq!(rows.len(), 2);
}

#[test]
fn timeline_scoped_to_entity() {
    let (_tmp, kg) = fresh_kg();
    kg.add_triple(
        "Max",
        "child_of",
        "Alice",
        Some("2015-04-01"),
        None,
        1.0,
        None,
        None,
    )
    .unwrap();
    kg.add_triple(
        "Max",
        "loves",
        "chess",
        Some("2025-10-01"),
        None,
        1.0,
        None,
        None,
    )
    .unwrap();
    kg.add_triple(
        "Bob",
        "loves",
        "cards",
        Some("2020-01-01"),
        None,
        1.0,
        None,
        None,
    )
    .unwrap();
    let rows = kg.timeline(Some("Max")).unwrap();
    assert_eq!(rows.len(), 2);
}

#[test]
fn timeline_unfiltered_returns_all() {
    let (_tmp, kg) = fresh_kg();
    kg.add_triple(
        "Max",
        "loves",
        "chess",
        Some("2025-01-01"),
        None,
        1.0,
        None,
        None,
    )
    .unwrap();
    kg.add_triple(
        "Bob",
        "loves",
        "cards",
        Some("2025-02-01"),
        None,
        1.0,
        None,
        None,
    )
    .unwrap();
    let rows = kg.timeline(None).unwrap();
    assert_eq!(rows.len(), 2);
}

#[test]
fn stats_counts_current_and_expired() {
    let (_tmp, kg) = fresh_kg();
    kg.add_triple("Max", "loves", "chess", None, None, 1.0, None, None)
        .unwrap();
    kg.add_triple("Max", "has_issue", "injury", None, None, 1.0, None, None)
        .unwrap();
    kg.invalidate("Max", "has_issue", "injury", Some("2026-02-15"))
        .unwrap();
    let s = kg.stats().unwrap();
    assert_eq!(s.triples, 2);
    assert_eq!(s.current_facts, 1);
    assert_eq!(s.expired_facts, 1);
    assert!(s.relationship_types.contains(&"loves".to_string()));
}

#[test]
fn predicate_is_lowercased_and_spaces_to_underscores() {
    let (_tmp, kg) = fresh_kg();
    kg.add_triple("Max", "Is Child Of", "Alice", None, None, 1.0, None, None)
        .unwrap();
    let rows = kg.query_entity("Max", None, Direction::Outgoing).unwrap();
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].predicate, "is_child_of");
}

#[test]
fn database_is_persisted_to_disk() {
    let tmp = TempDir::new().unwrap();
    let db = tmp.path().join("kg.sqlite3");
    {
        let kg = KnowledgeGraph::open(&db).unwrap();
        kg.add_triple("A", "rel", "B", None, None, 1.0, None, None)
            .unwrap();
    }
    let kg2 = KnowledgeGraph::open(&db).unwrap();
    let rows = kg2.query_entity("A", None, Direction::Outgoing).unwrap();
    assert_eq!(rows.len(), 1);
}

#[test]
fn confidence_is_stored() {
    let (_tmp, kg) = fresh_kg();
    kg.add_triple("A", "rel", "B", None, None, 0.5, None, None)
        .unwrap();
    let rows = kg.query_entity("A", None, Direction::Outgoing).unwrap();
    assert!((rows[0].confidence - 0.5).abs() < 1e-9);
}

#[test]
fn source_closet_is_stored() {
    let (_tmp, kg) = fresh_kg();
    kg.add_triple(
        "A",
        "rel",
        "B",
        None,
        None,
        1.0,
        Some("closet_123"),
        Some("file.txt"),
    )
    .unwrap();
    let rows = kg.query_entity("A", None, Direction::Outgoing).unwrap();
    assert_eq!(rows[0].source_closet.as_deref(), Some("closet_123"));
}

#[test]
fn invalidate_does_nothing_when_already_invalid() {
    let (_tmp, kg) = fresh_kg();
    kg.add_triple("A", "rel", "B", None, None, 1.0, None, None)
        .unwrap();
    kg.invalidate("A", "rel", "B", Some("2026-01-01")).unwrap();
    let n = kg.invalidate("A", "rel", "B", Some("2026-02-01")).unwrap();
    assert_eq!(n, 0);
}
