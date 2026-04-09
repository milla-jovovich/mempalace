#![allow(clippy::unwrap_used, clippy::expect_used)]

use mempalace_server::ingest::{chunk_text, compute_drawer_id, Miner, MinerOptions};
use mempalace_store::palace::{InMemoryPalace, Palace};
use std::path::Path;
use tempfile::TempDir;

#[test]
fn chunk_text_respects_size_and_overlap() {
    let text = "a".repeat(2500);
    let chunks = chunk_text(&text, 800, 100);
    assert!(chunks.len() >= 3);
    for c in &chunks {
        assert!(c.len() <= 800);
    }
}

#[test]
fn chunk_text_short_returns_single() {
    let text = "short".to_string();
    let chunks = chunk_text(&text, 800, 100);
    assert_eq!(chunks.len(), 1);
    assert_eq!(chunks[0], "short");
}

#[test]
fn chunk_text_empty_returns_empty() {
    let chunks = chunk_text("", 800, 100);
    assert!(chunks.is_empty());
}

#[test]
fn compute_drawer_id_is_deterministic() {
    let a = compute_drawer_id(Path::new("a.md"), 0, "hello");
    let b = compute_drawer_id(Path::new("a.md"), 0, "hello");
    assert_eq!(a, b);
}

#[test]
fn compute_drawer_id_changes_per_chunk_index() {
    let a = compute_drawer_id(Path::new("a.md"), 0, "hello");
    let b = compute_drawer_id(Path::new("a.md"), 1, "hello");
    assert_ne!(a, b);
}

#[test]
fn miner_ingests_text_files() {
    let tmp = TempDir::new().unwrap();
    std::fs::write(
        tmp.path().join("notes.md"),
        "This is a long note about Postgres. ".repeat(60),
    )
    .unwrap();
    std::fs::write(
        tmp.path().join("other.py"),
        "print('hello world')".repeat(40),
    )
    .unwrap();

    let mut palace = InMemoryPalace::new();
    let miner = Miner::new(MinerOptions {
        wing: Some("myapp".to_string()),
        ..MinerOptions::default()
    });
    let stats = miner.mine(tmp.path(), &mut palace).unwrap();
    assert!(stats.files_scanned >= 2);
    assert!(stats.files_indexed >= 2);
    assert!(stats.drawers_written >= 2);
    assert!(palace.count().unwrap() >= 2);
}

#[test]
fn miner_skips_binary_extensions() {
    let tmp = TempDir::new().unwrap();
    std::fs::write(tmp.path().join("image.bin"), vec![0u8; 1024]).unwrap();
    let mut palace = InMemoryPalace::new();
    let miner = Miner::new(MinerOptions::default());
    let stats = miner.mine(tmp.path(), &mut palace).unwrap();
    assert_eq!(stats.drawers_written, 0);
    assert!(stats.files_skipped_binary >= 1);
}

#[test]
fn miner_skips_gitignored_files() {
    let tmp = TempDir::new().unwrap();
    std::fs::create_dir_all(tmp.path().join(".git")).unwrap();
    std::fs::write(tmp.path().join(".gitignore"), "secret.md\n").unwrap();
    std::fs::write(tmp.path().join("secret.md"), "top secret data ".repeat(20)).unwrap();
    std::fs::write(tmp.path().join("public.md"), "public knowledge ".repeat(20)).unwrap();

    let mut palace = InMemoryPalace::new();
    let miner = Miner::new(MinerOptions::default());
    let _stats = miner.mine(tmp.path(), &mut palace).unwrap();
    let all = palace.list(100, 0).unwrap();
    for d in all {
        assert!(!d.content.contains("top secret"));
    }
}

#[test]
fn miner_errors_on_missing_root() {
    let mut palace = InMemoryPalace::new();
    let miner = Miner::new(MinerOptions::default());
    let res = miner.mine(Path::new("/definitely/does/not/exist"), &mut palace);
    assert!(res.is_err());
}
