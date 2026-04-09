#![allow(clippy::unwrap_used, clippy::expect_used)]

use mempalace_store::palace::{DrawerMetadata, DrawerRecord, InMemoryPalace, Palace};
use mempalace_store::palace_graph::PalaceGraph;

fn seed_palace() -> InMemoryPalace {
    let mut palace = InMemoryPalace::new();

    for (i, (wing, room, hall)) in [
        ("wing_kai", "auth-migration", "hall_facts"),
        ("wing_driftwood", "auth-migration", "hall_events"),
        ("wing_priya", "auth-migration", "hall_advice"),
        ("wing_kai", "chromadb-setup", "hall_facts"),
        ("wing_driftwood", "graphql-switch", "hall_facts"),
        ("wing_kai", "graphql-switch", "hall_facts"),
        ("wing_other", "general", "hall_events"),
    ]
    .iter()
    .enumerate()
    {
        palace
            .add(DrawerRecord {
                id: format!("d{i}"),
                content: format!("content {i}"),
                metadata: DrawerMetadata {
                    wing: Some((*wing).to_string()),
                    room: Some((*room).to_string()),
                    hall: Some((*hall).to_string()),
                    date: Some("2026-01-01".to_string()),
                    ..DrawerMetadata::default()
                },
            })
            .unwrap();
    }
    palace
}

#[test]
fn build_skips_general_rooms() {
    let palace = seed_palace();
    let graph = PalaceGraph::new(&palace);
    let (nodes, _) = graph.build();
    assert!(!nodes.contains_key("general"));
}

#[test]
fn build_tracks_room_wings() {
    let palace = seed_palace();
    let graph = PalaceGraph::new(&palace);
    let (nodes, _) = graph.build();
    let auth = nodes.get("auth-migration").unwrap();
    assert_eq!(auth.wings.len(), 3);
}

#[test]
fn build_edges_span_wings() {
    let palace = seed_palace();
    let graph = PalaceGraph::new(&palace);
    let (_, edges) = graph.build();
    assert!(edges.iter().any(|e| e.room == "auth-migration"));
}

#[test]
fn find_tunnels_returns_multi_wing_rooms() {
    let palace = seed_palace();
    let graph = PalaceGraph::new(&palace);
    let tunnels = graph.find_tunnels(None, None);
    assert!(tunnels.iter().any(|t| t.room == "auth-migration"));
    assert!(!tunnels.iter().any(|t| t.room == "chromadb-setup"));
}

#[test]
fn find_tunnels_filtered_by_wing() {
    let palace = seed_palace();
    let graph = PalaceGraph::new(&palace);
    let tunnels = graph.find_tunnels(Some("wing_kai"), None);
    assert!(tunnels.iter().any(|t| t.room == "graphql-switch"));
    assert!(tunnels.iter().any(|t| t.room == "auth-migration"));
}

#[test]
fn find_tunnels_filtered_by_both_wings() {
    let palace = seed_palace();
    let graph = PalaceGraph::new(&palace);
    let tunnels = graph.find_tunnels(Some("wing_kai"), Some("wing_driftwood"));
    assert!(tunnels.iter().any(|t| t.room == "auth-migration"));
    assert!(tunnels.iter().any(|t| t.room == "graphql-switch"));
}

#[test]
fn traverse_includes_start_room_at_hop_zero() {
    let palace = seed_palace();
    let graph = PalaceGraph::new(&palace);
    let path = graph.traverse("auth-migration", 2);
    let start = path.iter().find(|p| p.room == "auth-migration").unwrap();
    assert_eq!(start.hop, 0);
}

#[test]
fn traverse_finds_connected_rooms() {
    let palace = seed_palace();
    let graph = PalaceGraph::new(&palace);
    let path = graph.traverse("auth-migration", 2);
    assert!(path.iter().any(|p| p.room == "graphql-switch"));
}

#[test]
fn traverse_missing_room_returns_empty() {
    let palace = seed_palace();
    let graph = PalaceGraph::new(&palace);
    let path = graph.traverse("nonexistent", 2);
    assert!(path.is_empty());
}

#[test]
fn stats_reports_tunnel_rooms() {
    let palace = seed_palace();
    let graph = PalaceGraph::new(&palace);
    let stats = graph.stats();
    assert!(stats.total_rooms >= 3);
    assert!(stats.tunnel_rooms >= 2);
    assert!(stats.top_tunnels.iter().any(|t| t.room == "auth-migration"));
}

#[test]
fn stats_counts_rooms_per_wing() {
    let palace = seed_palace();
    let graph = PalaceGraph::new(&palace);
    let stats = graph.stats();
    let kai_count = *stats.rooms_per_wing.get("wing_kai").unwrap();
    assert!(kai_count >= 2);
}

#[test]
fn empty_palace_produces_empty_graph() {
    let palace = InMemoryPalace::new();
    let graph = PalaceGraph::new(&palace);
    let (nodes, edges) = graph.build();
    assert!(nodes.is_empty());
    assert!(edges.is_empty());
}
