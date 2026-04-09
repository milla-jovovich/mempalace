#![allow(clippy::unwrap_used, clippy::expect_used)]

use mempalace_server::searcher::{search_memories, SearchQuery};
use mempalace_store::palace::{DrawerMetadata, DrawerRecord, InMemoryPalace, Palace};

fn seed() -> InMemoryPalace {
    let mut palace = InMemoryPalace::new();
    palace
        .add(DrawerRecord {
            id: "1".to_string(),
            content: "We picked Postgres over MongoDB for concurrent writes".to_string(),
            metadata: DrawerMetadata {
                wing: Some("myapp".to_string()),
                room: Some("db".to_string()),
                source_file: Some("/notes/db.md".to_string()),
                ..DrawerMetadata::default()
            },
        })
        .unwrap();
    palace
        .add(DrawerRecord {
            id: "2".to_string(),
            content: "Auth uses Clerk for user sessions".to_string(),
            metadata: DrawerMetadata {
                wing: Some("myapp".to_string()),
                room: Some("auth".to_string()),
                source_file: Some("/notes/auth.md".to_string()),
                ..DrawerMetadata::default()
            },
        })
        .unwrap();
    palace
}

#[test]
fn search_finds_by_token() {
    let palace = seed();
    let q = SearchQuery {
        query: "Postgres".to_string(),
        n_results: 5,
        ..SearchQuery::default()
    };
    let resp = search_memories(&palace, &q);
    assert_eq!(resp.results.len(), 1);
    assert_eq!(resp.results[0].wing, "myapp");
    assert_eq!(resp.results[0].room, "db");
}

#[test]
fn search_filters_by_wing() {
    let palace = seed();
    let q = SearchQuery {
        query: "auth".to_string(),
        wing: Some("myapp".to_string()),
        n_results: 5,
        ..SearchQuery::default()
    };
    let resp = search_memories(&palace, &q);
    assert_eq!(resp.results.len(), 1);
}

#[test]
fn search_no_match_returns_empty() {
    let palace = seed();
    let q = SearchQuery {
        query: "nonexistent".to_string(),
        n_results: 5,
        ..SearchQuery::default()
    };
    let resp = search_memories(&palace, &q);
    assert!(resp.results.is_empty());
}

#[test]
fn search_default_n_results() {
    let palace = seed();
    let q = SearchQuery {
        query: "myapp".to_string(),
        n_results: 0,
        ..SearchQuery::default()
    };
    let _resp = search_memories(&palace, &q);
}

#[test]
fn search_hit_shortens_source_path() {
    let palace = seed();
    let q = SearchQuery {
        query: "Postgres".to_string(),
        n_results: 5,
        ..SearchQuery::default()
    };
    let resp = search_memories(&palace, &q);
    assert_eq!(resp.results[0].source_file, "db.md");
}
