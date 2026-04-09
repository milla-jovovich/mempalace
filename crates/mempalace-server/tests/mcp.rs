#![allow(clippy::unwrap_used, clippy::expect_used)]

use mempalace_server::mcp::{AddDrawerRequest, McpServer, AAAK_SPEC_TEXT};
use mempalace_server::searcher::SearchQuery;
use mempalace_store::knowledge_graph::KnowledgeGraph;
use mempalace_store::palace::{DrawerMetadata, DrawerRecord, InMemoryPalace, Palace};
use tempfile::TempDir;

fn make_server() -> (TempDir, McpServer) {
    let tmp = TempDir::new().unwrap();
    let kg_path = tmp.path().join("kg.sqlite3");
    let kg = KnowledgeGraph::open(&kg_path).unwrap();
    let mut palace = InMemoryPalace::new();
    for (wing, room, text) in [
        ("wing_app", "auth", "We decided to use Clerk for auth"),
        ("wing_app", "db", "Postgres for the primary store"),
        ("wing_other", "general", "Generic note"),
    ] {
        palace
            .add(DrawerRecord {
                id: format!("{wing}-{room}"),
                content: text.to_string(),
                metadata: DrawerMetadata {
                    wing: Some(wing.to_string()),
                    room: Some(room.to_string()),
                    ..DrawerMetadata::default()
                },
            })
            .unwrap();
    }
    let server = McpServer::new(Box::new(palace), kg);
    (tmp, server)
}

#[test]
fn status_reports_total_drawers_and_version() {
    let (_tmp, server) = make_server();
    let status = server.status().unwrap();
    assert_eq!(status.total_drawers, 3);
    assert_eq!(status.version, mempalace_core::VERSION);
    assert_eq!(status.tools_registered, 19);
    assert!(status.aaak_spec.contains("AAAK"));
}

#[test]
fn list_wings_returns_all_wings_with_counts() {
    let (_tmp, server) = make_server();
    let wings = server.list_wings().unwrap();
    assert_eq!(wings.len(), 2);
    let app = wings.iter().find(|w| w.name == "wing_app").unwrap();
    assert_eq!(app.drawer_count, 2);
}

#[test]
fn list_rooms_filters_by_wing() {
    let (_tmp, server) = make_server();
    let rooms = server.list_rooms(Some("wing_app")).unwrap();
    assert_eq!(rooms.len(), 2);
}

#[test]
fn get_taxonomy_groups_wings_and_rooms() {
    let (_tmp, server) = make_server();
    let tax = server.get_taxonomy().unwrap();
    assert_eq!(tax.wings.len(), 2);
    let app = tax.wings.iter().find(|w| w.name == "wing_app").unwrap();
    assert_eq!(app.drawer_count, 2);
    assert_eq!(app.rooms.len(), 2);
}

#[test]
fn search_returns_hits_for_query() {
    let (_tmp, server) = make_server();
    let hits = server
        .search(SearchQuery {
            query: "Postgres".to_string(),
            n_results: 5,
            ..SearchQuery::default()
        })
        .unwrap();
    assert_eq!(hits.len(), 1);
}

#[test]
fn check_duplicate_detects_existing_id() {
    let (_tmp, server) = make_server();
    let r = server.check_duplicate("wing_app-auth").unwrap();
    assert!(r.exists);

    let r2 = server.check_duplicate("nonexistent").unwrap();
    assert!(!r2.exists);
}

#[test]
fn get_aaak_spec_returns_text() {
    let (_tmp, server) = make_server();
    let spec = server.get_aaak_spec();
    assert_eq!(spec, AAAK_SPEC_TEXT);
    assert!(spec.contains("AAAK"));
}

#[test]
fn add_drawer_inserts_into_palace() {
    let (_tmp, server) = make_server();
    server
        .add_drawer(AddDrawerRequest {
            id: "new-drawer-1".to_string(),
            content: "New insight".to_string(),
            wing: Some("wing_app".to_string()),
            room: Some("insights".to_string()),
            hall: None,
            source_file: None,
        })
        .unwrap();
    let r = server.check_duplicate("new-drawer-1").unwrap();
    assert!(r.exists);
}

#[test]
fn delete_drawer_removes_from_palace() {
    let (_tmp, server) = make_server();
    let existed = server.delete_drawer("wing_app-auth").unwrap();
    assert!(existed);
    let r = server.check_duplicate("wing_app-auth").unwrap();
    assert!(!r.exists);
}

#[test]
fn kg_add_and_query_roundtrip() {
    let (_tmp, server) = make_server();
    server
        .kg_add("Alice", "works_on", "Driftwood", Some("2026-01-01"))
        .unwrap();
    let rows = server.kg_query("Alice", None).unwrap();
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].object, "Driftwood");
}

#[test]
fn kg_invalidate_sets_valid_to() {
    let (_tmp, server) = make_server();
    server
        .kg_add("Alice", "works_on", "OldProject", Some("2020-01-01"))
        .unwrap();
    let n = server
        .kg_invalidate("Alice", "works_on", "OldProject", Some("2023-01-01"))
        .unwrap();
    assert_eq!(n, 1);
}

#[test]
fn kg_timeline_unfiltered_returns_all() {
    let (_tmp, server) = make_server();
    server
        .kg_add("Alice", "loves", "chess", Some("2025-01-01"))
        .unwrap();
    server
        .kg_add("Bob", "loves", "cards", Some("2025-02-01"))
        .unwrap();
    let entries = server.kg_timeline(None).unwrap();
    assert!(entries.len() >= 2);
}

#[test]
fn kg_stats_returns_counts() {
    let (_tmp, server) = make_server();
    server.kg_add("A", "rel", "B", None).unwrap();
    let stats = server.kg_stats().unwrap();
    assert!(stats.triples >= 1);
    assert!(stats.current_facts >= 1);
}

#[test]
fn traverse_returns_start_room() {
    let (_tmp, server) = make_server();
    let res = server.traverse("auth", 2).unwrap();
    assert!(res.iter().any(|h| h.room == "auth"));
}

#[test]
fn find_tunnels_returns_rooms_spanning_multiple_wings() {
    let (_tmp, server) = make_server();
    server
        .add_drawer(AddDrawerRequest {
            id: "extra-1".to_string(),
            content: "duplicate room test".to_string(),
            wing: Some("wing_other".to_string()),
            room: Some("auth".to_string()),
            hall: None,
            source_file: None,
        })
        .unwrap();
    let tunnels = server.find_tunnels(None, None).unwrap();
    assert!(tunnels.iter().any(|t| t.room == "auth"));
}

#[test]
fn graph_stats_reports_totals() {
    let (_tmp, server) = make_server();
    let stats = server.graph_stats().unwrap();
    assert!(stats.total_rooms >= 2);
}
