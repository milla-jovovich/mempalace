//! End-to-end integration tests for mempalace.
//!
//! Tests full-stack flows at the library level since the CLI uses
//! in-memory state per process (no persistence across invocations).

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::uninlined_format_args
)]

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::process::{Command, Stdio};
use std::time::Duration;

use mempalace_server::ingest::MinerOptions;
use mempalace_server::{search_memories, ConvoMiner, ExtractMode, McpServer, Miner, SearchQuery};
use mempalace_store::palace::{DrawerMetadata, DrawerRecord, InMemoryPalace, Palace};
use mempalace_store::KnowledgeGraph;
use mempalace_text::dialect::Dialect;
use tempfile::TempDir;

// ── Test 1: Mine project files then search ──────────────────────────────

#[test]
fn test_mine_projects_then_search() {
    let tmp = TempDir::new().unwrap();

    std::fs::write(
        tmp.path().join("intro.txt"),
        "Rust is a systems programming language focused on safety and performance. \
         It prevents data races at compile time and guarantees memory safety without \
         a garbage collector.",
    )
    .unwrap();

    std::fs::write(
        tmp.path().join("concurrency.txt"),
        "Rust ownership model enables fearless concurrency. Threads can share data \
         safely through channels and mutexes. The borrow checker ensures no data \
         races occur at compile time.",
    )
    .unwrap();

    std::fs::write(
        tmp.path().join("ecosystem.txt"),
        "The Rust ecosystem includes Cargo for package management, rustfmt for \
         formatting, and clippy for linting. Crates.io hosts thousands of community \
         packages for web development, CLI tools, and embedded systems.",
    )
    .unwrap();

    let mut palace = InMemoryPalace::new();
    let miner = Miner::new(MinerOptions {
        wing: Some("test".into()),
        default_room: "general".into(),
        ..Default::default()
    });

    let stats = miner.mine(tmp.path(), &mut palace).unwrap();
    assert!(
        stats.files_indexed >= 3,
        "expected >= 3 files indexed, got {}",
        stats.files_indexed
    );
    assert!(
        stats.drawers_written >= 3,
        "expected >= 3 drawers, got {}",
        stats.drawers_written
    );

    let resp = search_memories(
        &palace,
        &SearchQuery {
            query: "rust safety".into(),
            ..Default::default()
        },
    );
    assert!(
        !resp.results.is_empty(),
        "search for 'rust safety' should return results"
    );
    assert!(
        resp.results
            .iter()
            .any(|h| h.text.to_lowercase().contains("safety")
                || h.text.to_lowercase().contains("rust")),
        "results should contain relevant content about Rust or safety"
    );
}

// ── Test 2: Mine conversations then search ──────────────────────────────

#[test]
fn test_mine_convos_then_search() {
    let tmp = TempDir::new().unwrap();

    let chat_content = "\
> What is memory?
Memory is the persistence of information over time. It allows systems to retain state.

> Why does it matter?
It enables continuity across sessions and conversations. Without memory, every interaction starts from zero.

> How do we build it?
With structured storage and retrieval mechanisms for knowledge. We use indexing and search.
";
    std::fs::write(tmp.path().join("chat.txt"), chat_content).unwrap();

    let mut palace = InMemoryPalace::new();
    let convo_miner = ConvoMiner {
        wing: Some("convos".into()),
        extract_mode: ExtractMode::Exchange,
        limit: 0,
        dry_run: false,
    };

    let stats = convo_miner.mine(tmp.path(), &mut palace).unwrap();
    assert!(
        stats.drawers_filed >= 2,
        "expected >= 2 drawers filed, got {}",
        stats.drawers_filed
    );
    assert_eq!(stats.files_processed, 1);

    let count = palace.count().unwrap();
    assert!(count >= 2, "palace should have >= 2 drawers, got {}", count);

    let resp = search_memories(
        &palace,
        &SearchQuery {
            query: "memory persistence".into(),
            ..Default::default()
        },
    );
    assert!(
        !resp.results.is_empty(),
        "search for 'memory persistence' should return results"
    );
}

// ── Test 3: Knowledge graph add, query, traverse ────────────────────────

#[test]
fn test_kg_add_query_traverse() {
    let tmp = TempDir::new().unwrap();
    let db_path = tmp.path().join("test_kg.sqlite3");
    let kg = KnowledgeGraph::open(&db_path).unwrap();

    // Add triples
    kg.add_triple("Rust", "is", "language", None, None, 1.0, None, None)
        .unwrap();
    kg.add_triple("Python", "is", "language", None, None, 1.0, None, None)
        .unwrap();
    kg.add_triple("Rust", "replaces", "Python", None, None, 0.8, None, None)
        .unwrap();

    // Query entity "Rust"
    let triples = kg
        .query_entity(
            "Rust",
            None,
            mempalace_store::knowledge_graph::Direction::Both,
        )
        .unwrap();
    assert!(
        triples.len() >= 2,
        "Rust should have >= 2 triples (is + replaces), got {}",
        triples.len()
    );

    // Check predicates
    let predicates: Vec<&str> = triples.iter().map(|t| t.predicate.as_str()).collect();
    assert!(
        predicates.contains(&"is"),
        "should have 'is' predicate: {predicates:?}"
    );
    assert!(
        predicates.contains(&"replaces"),
        "should have 'replaces' predicate: {predicates:?}"
    );

    // Stats
    let stats = kg.stats().unwrap();
    assert!(
        stats.entities >= 3,
        "expected >= 3 entities, got {}",
        stats.entities
    );
    assert!(
        stats.triples >= 3,
        "expected >= 3 triples, got {}",
        stats.triples
    );
    assert!(stats.current_facts >= 3);
    assert_eq!(stats.expired_facts, 0);
    assert!(!stats.relationship_types.is_empty());
}

// ── Test 4: MCP server tool calls ───────────────────────────────────────

#[test]
fn test_mcp_server_tool_call() {
    let mut palace = InMemoryPalace::new();

    // Add a drawer manually
    palace
        .add(DrawerRecord {
            id: "drawer_test_001".into(),
            content: "Rust is great for systems programming".into(),
            metadata: DrawerMetadata {
                wing: Some("projects".into()),
                room: Some("technical".into()),
                ..Default::default()
            },
        })
        .unwrap();
    palace
        .add(DrawerRecord {
            id: "drawer_test_002".into(),
            content: "Python is great for scripting".into(),
            metadata: DrawerMetadata {
                wing: Some("projects".into()),
                room: Some("general".into()),
                ..Default::default()
            },
        })
        .unwrap();

    let tmp = TempDir::new().unwrap();
    let db_path = tmp.path().join("mcp_test_kg.sqlite3");
    let kg = KnowledgeGraph::open(&db_path).unwrap();

    let server = McpServer::new(Box::new(palace), kg);

    // status
    let status = server.status().unwrap();
    assert_eq!(status.total_drawers, 2);
    assert!(!status.version.is_empty());
    assert!(status.tools_registered > 0);

    // search
    let _results = server
        .search(SearchQuery {
            query: "test".into(),
            ..Default::default()
        })
        .unwrap();
    // InMemoryPalace uses keyword matching, so results may vary
    // Just verify it doesn't panic

    // list_wings
    let wings = server.list_wings().unwrap();
    assert!(!wings.is_empty(), "should have at least one wing");
    let wing_names: Vec<&str> = wings.iter().map(|w| w.name.as_str()).collect();
    assert!(
        wing_names.contains(&"projects"),
        "should contain 'projects' wing: {wing_names:?}"
    );

    // get_taxonomy
    let taxonomy = server.get_taxonomy().unwrap();
    assert!(!taxonomy.wings.is_empty(), "taxonomy should have wings");
    let tax_wing = taxonomy
        .wings
        .iter()
        .find(|w| w.name == "projects")
        .unwrap();
    assert_eq!(tax_wing.drawer_count, 2);
    assert!(tax_wing.rooms.len() >= 2);

    // kg_stats
    let kg_stats = server.kg_stats().unwrap();
    assert_eq!(kg_stats.triples, 0); // empty KG
}

// ── Test 5: Compress round-trip ─────────────────────────────────────────

#[test]
fn test_compress_roundtrip() {
    let dialect = Dialect::new(HashMap::new(), vec![]);

    let texts = [
        "We decided to migrate from Python to Rust for better performance and safety. \
         The team evaluated several alternatives including Go and C++, but ultimately \
         chose Rust because of its ownership model and zero-cost abstractions. \
         This was a difficult decision that took weeks of deliberation.",
        "The architecture uses a layered design with a storage layer backed by SQLite \
         and an API layer that exposes REST endpoints. Each component follows the \
         single responsibility principle and communicates through well-defined interfaces.",
        "During the debugging session we discovered that the memory leak was caused by \
         a circular reference in the event handler. The fix involved switching to weak \
         references and adding explicit cleanup in the destructor. This resolved the \
         production crash that had been affecting users for three days.",
    ];

    for original in &texts {
        let compressed = dialect.compress(original, None);
        // Compressed should not be empty
        assert!(
            !compressed.is_empty(),
            "compressed text should not be empty"
        );

        // Compressed should be shorter or equal in byte length
        assert!(
            compressed.len() <= original.len(),
            "compressed ({}) should be <= original ({}) for text starting with {:?}",
            compressed.len(),
            original.len(),
            &original[..40],
        );

        // Check compression_stats returns valid stats
        let stats = dialect.compression_stats(original, &compressed);
        assert!(
            stats.original_tokens_est > 0,
            "original tokens should be > 0"
        );
        assert!(stats.summary_tokens_est > 0, "summary tokens should be > 0");
        assert!(
            stats.size_ratio >= 1.0,
            "size ratio should be >= 1.0, got {}",
            stats.size_ratio,
        );
    }
}

// ── Test 6: MCP serve tools/list (subprocess) ───────────────────────────

#[test]
fn test_mcp_serve_tools_list() {
    let initialize_req = r#"{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"e2e-test","version":"0"}}}"#;
    let initialized_notif = r#"{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}"#;
    let list_tools_req = r#"{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}"#;

    let bin = assert_cmd::cargo::cargo_bin("mempalace");

    let mut child = Command::new(&bin)
        .arg("mcp-serve")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .expect("failed to spawn mempalace mcp-serve");

    let mut stdin = child.stdin.take().expect("stdin not captured");
    let stdout = child.stdout.take().expect("stdout not captured");

    let reader_handle = std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        let mut responses: Vec<serde_json::Value> = Vec::new();
        let deadline = std::time::Instant::now() + Duration::from_secs(10);

        for line_result in reader.lines() {
            if std::time::Instant::now() > deadline {
                break;
            }
            let Ok(line) = line_result else { break };
            let trimmed = line.trim();
            if trimmed.is_empty() {
                continue;
            }
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(trimmed) {
                if val.get("id").is_some() {
                    responses.push(val);
                }
            }
            if responses.len() >= 2 {
                break;
            }
        }

        responses
    });

    // Send initialize
    writeln!(stdin, "{initialize_req}").expect("write init");
    stdin.flush().expect("flush");

    std::thread::sleep(Duration::from_millis(500));

    // Send initialized notification + tools/list
    writeln!(stdin, "{initialized_notif}").expect("write notif");
    stdin.flush().expect("flush");

    std::thread::sleep(Duration::from_millis(200));

    writeln!(stdin, "{list_tools_req}").expect("write tools/list");
    stdin.flush().expect("flush");

    std::thread::sleep(Duration::from_millis(500));

    drop(stdin);

    let responses = reader_handle.join().expect("reader thread panicked");

    let _ = child.kill();
    let _ = child.wait();

    assert!(
        responses.len() >= 2,
        "expected >= 2 responses, got {}: {responses:#?}",
        responses.len(),
    );

    // Response 1: initialize
    let init_resp = &responses[0];
    assert_eq!(
        init_resp.get("id").and_then(serde_json::Value::as_i64),
        Some(1),
    );
    assert!(init_resp.get("result").is_some());

    // Response 2: tools/list
    let tools_resp = &responses[1];
    assert_eq!(
        tools_resp.get("id").and_then(serde_json::Value::as_i64),
        Some(2),
    );
    let tools_result = tools_resp
        .get("result")
        .expect("tools/list response missing result");
    let tools = tools_result
        .get("tools")
        .and_then(|v| v.as_array())
        .expect("tools/list result should have tools array");

    let tool_names: Vec<&str> = tools
        .iter()
        .filter_map(|t| t.get("name").and_then(|n| n.as_str()))
        .collect();

    // At least 15 tools
    assert!(
        tool_names.len() >= 15,
        "expected >= 15 tools, got {}: {tool_names:?}",
        tool_names.len(),
    );

    // Specific tools must exist
    for expected in [
        "mempalace_status",
        "mempalace_search",
        "mempalace_add_drawer",
        "mempalace_kg_query",
    ] {
        assert!(
            tool_names.contains(&expected),
            "tools should include {expected}, got: {tool_names:?}",
        );
    }
}
