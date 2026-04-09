# Rust Stack Decisions — MemPalace Port

Source: `librarian` research task `bg_e2d48542` (2m28s).

## Final stack

| Layer | Crate | Version | Why |
|---|---|---|---|
| Vector DB (replaces ChromaDB) | `lancedb` | `0.27` | Embedded, file-based, Arrow-backed, metadata WHERE clauses, ~100k dl/90d, released 2026-03-31. Only production-ready pure-Rust embedded vector store with filter support. |
| Embeddings | `fastembed` | `5` | Native `AllMiniLML6V2` (identical 384-dim vectors to ChromaDB). Sync API. Auto-downloads ~80 MB ONNX to `~/.cache/fastembed/`. Cross-platform (macOS incl. Apple Silicon, Linux, Windows). |
| MCP server | `rmcp` | `0.16` (features `server`, `transport-io`, `macros`) | Official `modelcontextprotocol/rust-sdk`. `#[tool]` macro + `schemars`. stdio transport. Active (v1.3.0 on 2026-03-26). |
| Schema for rmcp | `schemars` | `1` | Required by `#[tool]` macro to derive JSON Schema. |
| SQLite (KG) | `rusqlite` | `0.39` (feature `bundled`) | Sync matches our sync KG code. WAL mode, parameterized queries, transactions. 54M+ total dl. |
| Async runtime | `tokio` | `1` (features `rt-multi-thread`, `macros`, `io-std`) | Required by both `lancedb` and `rmcp`. |
| Serde | `serde` / `serde_json` / `serde_yml` | `1` / `1` / `0.0.12` | `serde_yaml` (dtolnay) is archived — use `serde_yml` (maintained fork). |
| CLI | `clap` | `4` (feature `derive`) | Standard. Derive ergonomic. |
| Regex | `regex` | `1` | **NO lookaround**. Codebase audit: zero lookaround patterns — safe. |
| Dir traversal | `ignore` | `0.4` | From ripgrep; respects `.gitignore` patterns (matches Python's gitignore-aware miner). |
| Hashing | `blake3` | `1` | Faster than SHA-256; `sha2 = "0.10"` if we need SHA-2 compat for drawer IDs. The Python code uses `hashlib.sha256`; to preserve on-disk IDs we'll use **`sha2 = "0.10"`** instead. |
| Error (lib) | `thiserror` | `2` | For library crates. |
| Error (bin) | `anyhow` | `1` | For binary crates. |
| Logging | `tracing` + `tracing-subscriber` | `0.1` / `0.3` (feature `env-filter`) | Async-friendly, structured. |
| lzma-sys (lancedb dep) | `lzma-sys` | `*` (feature `static`) | Avoid runtime `liblzma` issues. |
| HTTP (Wikipedia in entity_registry) | `ureq` | `2` | Sync, no tokio leak into sync code paths. Entity registry does occasional Wikipedia lookups. |

## Gotchas

1. **`fastembed` first-run download** — ~80 MB ONNX model. Must handle first-run in onboarding/init. Alternative: bundle model directory with release via `with_model_path(…)`.
2. **`lancedb` is async-only** — entire storage layer must be async. Sync callers (e.g., `rusqlite`) that are called from async context must use `tokio::task::spawn_blocking`.
3. **`serde_yaml` is dead** — use `serde_yml`.
4. **`regex` no lookaround** — audited: zero lookaround patterns in mempalace; safe to use stable `regex` crate.
5. **`lancedb` initial compile is slow** (~3–5 min). CI must cache `target/`.
6. **`rmcp` 1.0 rewrite** — ignore pre-1.0 tutorials; use current docs.rs.
7. **`rusqlite::Connection` is `!Send`** — wrap in `Mutex` or use `tokio::task::spawn_blocking` from async context.
8. **`lancedb` needs Arrow schema upfront** — unlike ChromaDB, metadata columns must be defined in a schema. Match existing metadata keys: `wing`, `room`, `source_file`, `chunk_index`, `added_by`, `filed_at`, `source_mtime`, `ingest_mode`, `extract_mode`, `hall`, `topic`, `type`, `agent`, `date`, `compression_ratio`, `original_tokens`. All TEXT except the mtime/compression/tokens (Float64 or Int64).
9. **`lzma-sys` static feature** — add to avoid dynamic `liblzma` linkage.
10. **`Qdrant Edge`** is too new (March 2026, v0.6.1, 280 downloads) — stick with `lancedb`.

## Alternate: SQLite consolidation

`sqlite-vec` + `rusqlite` would let us merge vector store and knowledge graph into one SQLite file. Pros: single file, no Arrow schema. Cons: pre-v1 alpha, C FFI, breaking changes every few days. **Decision: use `lancedb` for now; revisit in a future release.**
