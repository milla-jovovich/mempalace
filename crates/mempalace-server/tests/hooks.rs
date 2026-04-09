#![allow(clippy::unwrap_used, clippy::expect_used)]

use mempalace_server::hooks::{precompact_save, SaveHook, SaveRequest};
use mempalace_store::palace::{InMemoryPalace, Palace};

#[test]
fn save_writes_drawer_to_palace() {
    let mut palace = InMemoryPalace::new();
    let hook = SaveHook::default();
    let result = hook
        .save(
            &mut palace,
            SaveRequest {
                wing: Some("myapp".to_string()),
                room: Some("auth".to_string()),
                source: Some("/conversations/2026-04-09.md".to_string()),
                content: "We decided to migrate to Clerk for auth".to_string(),
            },
        )
        .unwrap();
    assert!(!result.deduped);
    assert!(result.chars_written > 0);
    assert_eq!(palace.count().unwrap(), 1);
}

#[test]
fn save_dedupes_identical_content() {
    let mut palace = InMemoryPalace::new();
    let hook = SaveHook::default();
    let req = SaveRequest {
        wing: None,
        room: None,
        source: Some("/chat.md".to_string()),
        content: "same content".to_string(),
    };
    let r1 = hook.save(&mut palace, req.clone()).unwrap();
    let r2 = hook.save(&mut palace, req).unwrap();
    assert!(!r1.deduped);
    assert!(r2.deduped);
    assert_eq!(palace.count().unwrap(), 1);
}

#[test]
fn save_rejects_empty() {
    let mut palace = InMemoryPalace::new();
    let hook = SaveHook::default();
    let res = hook.save(
        &mut palace,
        SaveRequest {
            content: "   ".to_string(),
            ..SaveRequest::default()
        },
    );
    assert!(res.is_err());
}

#[test]
fn precompact_is_equivalent_to_default_save() {
    let mut palace = InMemoryPalace::new();
    let result = precompact_save(
        &mut palace,
        SaveRequest {
            content: "urgent save before compaction".to_string(),
            ..SaveRequest::default()
        },
    )
    .unwrap();
    assert!(result.chars_written > 0);
}

#[test]
fn save_defaults_room_to_general() {
    let mut palace = InMemoryPalace::new();
    SaveHook::default()
        .save(
            &mut palace,
            SaveRequest {
                content: "note".to_string(),
                ..SaveRequest::default()
            },
        )
        .unwrap();
    let all = palace.list(10, 0).unwrap();
    assert_eq!(
        all[0].metadata.room.as_deref(),
        Some("general"),
        "default room should be `general`"
    );
}

#[test]
fn different_sources_produce_different_drawer_ids() {
    let mut palace = InMemoryPalace::new();
    let hook = SaveHook::default();
    let r1 = hook
        .save(
            &mut palace,
            SaveRequest {
                content: "same text".to_string(),
                source: Some("/chat1.md".to_string()),
                ..SaveRequest::default()
            },
        )
        .unwrap();
    let r2 = hook
        .save(
            &mut palace,
            SaveRequest {
                content: "same text".to_string(),
                source: Some("/chat2.md".to_string()),
                ..SaveRequest::default()
            },
        )
        .unwrap();
    assert_ne!(r1.drawer_id, r2.drawer_id);
}
