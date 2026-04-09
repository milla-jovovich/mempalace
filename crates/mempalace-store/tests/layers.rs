#![allow(clippy::unwrap_used, clippy::expect_used)]

use std::path::PathBuf;

use mempalace_store::layers::{Layer0, Layer1, Layer2, Layer3, MemoryStack};
use mempalace_store::palace::{DrawerMetadata, DrawerRecord, InMemoryPalace, Palace};
use tempfile::TempDir;

fn seed_palace() -> InMemoryPalace {
    let mut palace = InMemoryPalace::new();
    palace
        .add(DrawerRecord {
            id: "d1".to_string(),
            content: "We decided to use Postgres for storage reliability".to_string(),
            metadata: DrawerMetadata {
                wing: Some("myapp".to_string()),
                room: Some("auth".to_string()),
                importance: Some(5.0),
                source_file: Some("/notes/auth.md".to_string()),
                ..DrawerMetadata::default()
            },
        })
        .unwrap();
    palace
        .add(DrawerRecord {
            id: "d2".to_string(),
            content: "Set up Clerk for user authentication".to_string(),
            metadata: DrawerMetadata {
                wing: Some("myapp".to_string()),
                room: Some("auth".to_string()),
                importance: Some(4.0),
                source_file: Some("/notes/clerk.md".to_string()),
                ..DrawerMetadata::default()
            },
        })
        .unwrap();
    palace
        .add(DrawerRecord {
            id: "d3".to_string(),
            content: "Database migration plan".to_string(),
            metadata: DrawerMetadata {
                wing: Some("other".to_string()),
                room: Some("db".to_string()),
                importance: Some(2.0),
                ..DrawerMetadata::default()
            },
        })
        .unwrap();
    palace
}

#[test]
fn layer0_renders_default_when_no_file() {
    let tmp = TempDir::new().unwrap();
    let missing = tmp.path().join("missing.txt");
    let mut l0 = Layer0::new(Some(missing));
    let text = l0.render();
    assert!(text.contains("L0 — IDENTITY"));
    assert!(text.contains("identity.txt"));
}

#[test]
fn layer0_reads_file_when_present() {
    let tmp = TempDir::new().unwrap();
    let path = tmp.path().join("identity.txt");
    std::fs::write(&path, "I am Atlas. I help Alice.").unwrap();
    let mut l0 = Layer0::new(Some(path));
    assert!(l0.render().contains("Atlas"));
}

#[test]
fn layer0_token_estimate_is_nonzero() {
    let tmp = TempDir::new().unwrap();
    let path = tmp.path().join("identity.txt");
    std::fs::write(
        &path,
        "I am Atlas. I help Alice. I remember things for her.",
    )
    .unwrap();
    let mut l0 = Layer0::new(Some(path));
    assert!(l0.token_estimate() > 0);
}

#[test]
fn layer1_generates_essential_story() {
    let palace = seed_palace();
    let l1 = Layer1::new(&palace);
    let text = l1.generate();
    assert!(text.contains("L1 — ESSENTIAL STORY"));
    assert!(text.contains("Postgres"));
}

#[test]
fn layer1_filters_by_wing() {
    let palace = seed_palace();
    let l1 = Layer1::with_wing(&palace, Some("other".to_string()));
    let text = l1.generate();
    assert!(text.contains("Database migration"));
    assert!(!text.contains("Postgres"));
}

#[test]
fn layer1_empty_palace_returns_placeholder() {
    let palace = InMemoryPalace::new();
    let l1 = Layer1::new(&palace);
    let text = l1.generate();
    assert!(text.contains("No memories yet"));
}

#[test]
fn layer2_retrieves_by_wing_and_room() {
    let palace = seed_palace();
    let l2 = Layer2::new(&palace);
    let text = l2.retrieve(Some("myapp"), Some("auth"), 10);
    assert!(text.contains("L2 — ON-DEMAND"));
    assert!(text.contains("Clerk") || text.contains("Postgres"));
}

#[test]
fn layer2_returns_placeholder_when_no_match() {
    let palace = seed_palace();
    let l2 = Layer2::new(&palace);
    let text = l2.retrieve(Some("nonexistent"), None, 10);
    assert!(text.contains("No drawers found"));
}

#[test]
fn layer3_search_finds_content() {
    let palace = seed_palace();
    let l3 = Layer3::new(&palace);
    let text = l3.search("Postgres", None, None, 5);
    assert!(text.contains("L3 — SEARCH RESULTS"));
    assert!(text.contains("Postgres"));
}

#[test]
fn layer3_search_returns_no_results_placeholder() {
    let palace = seed_palace();
    let l3 = Layer3::new(&palace);
    let text = l3.search("nonexistent", None, None, 5);
    assert!(text.contains("No results"));
}

#[test]
fn memory_stack_wake_up_combines_l0_and_l1() {
    let tmp = TempDir::new().unwrap();
    let identity = tmp.path().join("identity.txt");
    std::fs::write(&identity, "I am Atlas.").unwrap();

    let palace = seed_palace();
    let mut stack = MemoryStack::new(&palace, Some(identity));
    let text = stack.wake_up(None);
    assert!(text.contains("Atlas"));
    assert!(text.contains("L1"));
}

#[test]
fn memory_stack_recall_forwards_to_l2() {
    let tmp = TempDir::new().unwrap();
    let identity = tmp.path().join("identity.txt");

    let palace = seed_palace();
    let stack = MemoryStack::new(&palace, Some(identity));
    let text = stack.recall(Some("myapp"), Some("auth"), 10);
    assert!(text.contains("L2"));
}

#[test]
fn memory_stack_search_forwards_to_l3() {
    let tmp = TempDir::new().unwrap();
    let identity = tmp.path().join("identity.txt");

    let palace = seed_palace();
    let stack = MemoryStack::new(&palace, Some(identity));
    let text = stack.search("Postgres", None, None, 5);
    assert!(text.contains("L3"));
}

#[test]
fn memory_stack_total_drawers_matches_palace_count() {
    let tmp = TempDir::new().unwrap();
    let palace = seed_palace();
    let stack = MemoryStack::new(&palace, Some(tmp.path().join("identity.txt")));
    assert_eq!(stack.total_drawers(), 3);
}

#[test]
fn memory_stack_uses_default_identity_path() {
    let palace = InMemoryPalace::new();
    let stack = MemoryStack::new(&palace, None);
    assert!(stack
        .identity_path
        .ends_with(PathBuf::from(".mempalace/identity.txt")));
}
