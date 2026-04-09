#![allow(clippy::unwrap_used, clippy::expect_used)]

use mempalace_store::palace::{DrawerMetadata, DrawerRecord, InMemoryPalace, Palace, SearchFilter};

fn make_drawer(id: &str, content: &str, wing: Option<&str>, room: Option<&str>) -> DrawerRecord {
    DrawerRecord {
        id: id.to_string(),
        content: content.to_string(),
        metadata: DrawerMetadata {
            wing: wing.map(str::to_string),
            room: room.map(str::to_string),
            ..DrawerMetadata::default()
        },
    }
}

#[test]
fn new_palace_is_empty() {
    let palace = InMemoryPalace::new();
    assert_eq!(palace.count().unwrap(), 0);
}

#[test]
fn add_and_count() {
    let mut palace = InMemoryPalace::new();
    palace
        .add(make_drawer("1", "hello world", Some("myapp"), Some("auth")))
        .unwrap();
    assert_eq!(palace.count().unwrap(), 1);
}

#[test]
fn duplicate_id_rejected() {
    let mut palace = InMemoryPalace::new();
    palace.add(make_drawer("1", "hello", None, None)).unwrap();
    let err = palace.add(make_drawer("1", "world", None, None));
    assert!(err.is_err());
}

#[test]
fn get_returns_record() {
    let mut palace = InMemoryPalace::new();
    palace
        .add(make_drawer("1", "hello", Some("myapp"), None))
        .unwrap();
    let rec = palace.get("1").unwrap().unwrap();
    assert_eq!(rec.content, "hello");
}

#[test]
fn delete_removes_record() {
    let mut palace = InMemoryPalace::new();
    palace.add(make_drawer("1", "hello", None, None)).unwrap();
    assert!(palace.delete("1").unwrap());
    assert_eq!(palace.count().unwrap(), 0);
}

#[test]
fn list_paginates() {
    let mut palace = InMemoryPalace::new();
    for i in 0..10 {
        palace
            .add(make_drawer(&format!("{i}"), "content", None, None))
            .unwrap();
    }
    let page = palace.list(3, 5).unwrap();
    assert_eq!(page.len(), 3);
    assert_eq!(page[0].id, "5");
}

#[test]
fn list_filtered_by_wing() {
    let mut palace = InMemoryPalace::new();
    palace
        .add(make_drawer("1", "a", Some("myapp"), None))
        .unwrap();
    palace
        .add(make_drawer("2", "b", Some("other"), None))
        .unwrap();
    palace
        .add(make_drawer("3", "c", Some("myapp"), None))
        .unwrap();

    let filter = SearchFilter {
        wing: Some("myapp".to_string()),
        room: None,
    };
    let list = palace.list_filtered(&filter, 10).unwrap();
    assert_eq!(list.len(), 2);
}

#[test]
fn list_filtered_by_wing_and_room() {
    let mut palace = InMemoryPalace::new();
    palace
        .add(make_drawer("1", "a", Some("app"), Some("auth")))
        .unwrap();
    palace
        .add(make_drawer("2", "b", Some("app"), Some("db")))
        .unwrap();
    let filter = SearchFilter {
        wing: Some("app".to_string()),
        room: Some("auth".to_string()),
    };
    let list = palace.list_filtered(&filter, 10).unwrap();
    assert_eq!(list.len(), 1);
    assert_eq!(list[0].id, "1");
}

#[test]
fn search_matches_content_tokens() {
    let mut palace = InMemoryPalace::new();
    palace
        .add(make_drawer("1", "We use Postgres for storage", None, None))
        .unwrap();
    palace
        .add(make_drawer("2", "We picked MongoDB", None, None))
        .unwrap();
    palace
        .add(make_drawer("3", "Tabs vs spaces", None, None))
        .unwrap();
    let hits = palace
        .search("Postgres", &SearchFilter::default(), 5)
        .unwrap();
    assert_eq!(hits.len(), 1);
    assert_eq!(hits[0].id, "1");
}

#[test]
fn search_respects_filter() {
    let mut palace = InMemoryPalace::new();
    palace
        .add(make_drawer("1", "auth with JWT", Some("app"), Some("auth")))
        .unwrap();
    palace
        .add(make_drawer(
            "2",
            "auth with OAuth",
            Some("other"),
            Some("auth"),
        ))
        .unwrap();
    let hits = palace
        .search(
            "auth",
            &SearchFilter {
                wing: Some("app".to_string()),
                room: None,
            },
            5,
        )
        .unwrap();
    assert_eq!(hits.len(), 1);
    assert_eq!(hits[0].id, "1");
}

#[test]
fn search_returns_empty_for_unknown_query() {
    let mut palace = InMemoryPalace::new();
    palace.add(make_drawer("1", "hello", None, None)).unwrap();
    let hits = palace
        .search("nonexistent", &SearchFilter::default(), 5)
        .unwrap();
    assert!(hits.is_empty());
}

#[test]
fn delete_of_missing_returns_false() {
    let mut palace = InMemoryPalace::new();
    assert!(!palace.delete("missing").unwrap());
}
