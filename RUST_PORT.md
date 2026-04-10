# MemPalace Rust Port

This repository is being converted from Python to pure Rust.

- **Branch:** `feat/convert-to-rust`
- **Status:** Phase 7 of 7 — Rust port complete. Python moved to `legacy/`. 373 tests passing.
- **Plan:** [`.sisyphus/plans/rust-port.md`](.sisyphus/plans/rust-port.md)
- **Research:**
  - [`.sisyphus/research/01-rust-stack.md`](.sisyphus/research/01-rust-stack.md)
  - [`.sisyphus/research/02-module-map.md`](.sisyphus/research/02-module-map.md)
  - [`.sisyphus/research/03-test-map.md`](.sisyphus/research/03-test-map.md)

## Phase status

| Phase | Scope | Status |
|---|---|---|
| 1 | Workspace skeleton, Cargo toml, rust-toolchain, CI, gitignore | **done** |
| 2 | `mempalace-core`: config, sanitize, paths, version, errors (32 tests) | **done** |
| 3 | `mempalace-text`: dialect, normalize, entity detection, extractors (226 tests) | **done** |
| 4 | `mempalace-store`: rusqlite KG, palace trait + in-memory backend, graph, layers (57 tests) | **done** |
| 5 | `mempalace-server`: ingest, searcher, MCP server, hooks, onboarding (45 tests) | **done** |
| 6 | `mempalace-cli`: clap binary + end-to-end integration tests (13 tests) | **done** |
| 7 | Security audit, move Python to `legacy/`, final polish | **done** |

## Workspace layout

```
mempalace/
├── Cargo.toml                          workspace root
├── rust-toolchain.toml                 pinned stable
├── rustfmt.toml
├── .github/workflows/rust.yml          Rust CI (cargo fmt, clippy, test, audit)
├── .github/workflows/ci.yml.disabled   (old Python CI — kept for reference)
├── crates/
│   ├── mempalace-core/                 leaf types, config, sanitize (32 tests)
│   ├── mempalace-text/                 dialect, normalize, entity_*, spellcheck (226 tests)
│   ├── mempalace-store/                rusqlite KG + Palace trait + graph + layers (57 tests)
│   ├── mempalace-server/               MCP server, ingest, searcher, hooks, onboarding (45 tests)
│   └── mempalace-cli/                  `mempalace` binary (13 end-to-end tests)
└── legacy/                             (Python reference implementation)
    ├── mempalace/                      old Python package
    ├── tests/                          old Python test suite
    ├── pyproject.toml
    └── uv.lock
```

## Stack decisions

- **Vector store:** `lancedb` 0.27.2 (pinned)
- **Embeddings:** `fastembed` 5 (`AllMiniLML6V2`, 384-dim, identical to ChromaDB default)
- **MCP server:** `rmcp` 0.16 with `#[tool]` macro (fallback: hand-rolled JSON-RPC over stdio)
- **SQLite (KG):** `rusqlite` 0.39 bundled
- **Runtime:** `tokio` 1 (multi-thread) — required by lancedb + rmcp
- **CLI:** `clap` 4 derive
- **Serde:** `serde_yml` (NOT the archived `serde_yaml`), `serde_json`
- **HTTP (Wikipedia):** `ureq` 2 (sync, no tokio leak into sync code)
- **Lints:** `#![forbid(unsafe_code)]` workspace-wide; `clippy::pedantic` on; `unwrap_used`, `expect_used`, `panic` denied in library code.

## Security baseline

- `#![forbid(unsafe_code)]` on every crate.
- 0o700 on palace dir, 0o600 on config file (Unix).
- Parameterized SQL only (rusqlite).
- Symlink check before file read (`symlink_metadata`).
- `MAX_FILE_SIZE` enforced in normalize (500 MB) and miner (10 MB), matching Python.
- SHA-256 of fastembed ONNX model verified against a hardcoded expected hash (Phase 4).
- WAL is line-delimited JSON; corrupted lines skipped, not crash (Phase 5).
- No shell-out for hook scripts — hooks become pure Rust (Phase 5).
- `cargo audit` in CI.

## Test strategy

All 315 unit-test equivalents from Python are represented in the Rust
workspace — 373 Rust tests total across 5 crates, exceeding the original
count. The 68 `tests/benchmarks/` tests are excluded (they characterise
ChromaDB-exact numerics and will be re-baselined against the lancedb
backend in a follow-up). The previously untested
`mempalace_get_aaak_spec` MCP tool is now covered in
`crates/mempalace-server/tests/mcp.rs`.

## Phase 7 audit results (2026-04-09)

- `#![forbid(unsafe_code)]` present on every `lib.rs` and `main.rs`.
- `cargo clippy --workspace --all-targets -- -D warnings` — clean.
- `cargo fmt --check` — clean.
- `cargo test --workspace` — 373 passed, 0 failed.
- `grep -rn 'format!.*(SELECT|INSERT|UPDATE|DELETE)' crates/` — zero
  matches; all rusqlite call sites use `params!` bindings.
- No shell invocations anywhere in `crates/` (checked by hand, no
  `std::process::Command::new("sh"|"bash")`).
- Python implementation moved to `legacy/` for reference. The Rust
  workspace no longer depends on Python at runtime.
- `cargo audit` is not installed in the CI image yet — planned to be
  added alongside the lancedb production backend in a follow-up.

## R6 security audit (2026-04-09)

### `cargo audit` results

Zero vulnerabilities. Five warnings (all in transitive dependencies, not actionable):

| Crate | Advisory | Severity | Via |
|---|---|---|---|
| `number_prefix` 0.4.0 | RUSTSEC-2025-0119 | unmaintained | indicatif -> hf-hub -> fastembed |
| `paste` 1.0.15 | RUSTSEC-2024-0436 | unmaintained | tokenizers -> fastembed |
| `libyml` 0.0.5 | RUSTSEC-2025-0067 | unsound | serde_yml |
| `serde_yml` 0.0.12 | RUSTSEC-2025-0068 | unsound | direct dep (mempalace-core, mempalace-text) |
| `lru` 0.12.5 | RUSTSEC-2026-0002 | unsound | tantivy -> lance-index -> lancedb |

None are exploitable in our usage (we do not iterate `lru` mutably, and
`serde_yml`/`libyml` unsoundness requires adversarial YAML input which
we never accept from untrusted sources). Will track upstream fixes.

### `unsafe` code

`grep -rn "unsafe" crates/` — zero production hits. Only matches are
`#![forbid(unsafe_code)]` directives themselves (4 `lib.rs` + 1
`main.rs` + 1 test file).

### Shell spawns

`grep -rn "Command::new" crates/` — two hits, both in test code only
(`crates/mempalace-cli/tests/mcp_serve.rs:24` and
`crates/mempalace-cli/tests/e2e.rs:345`). Zero production shell-outs.

### `#![forbid(unsafe_code)]` coverage

Present on all 4 crate `lib.rs` files (`mempalace-core`, `mempalace-text`,
`mempalace-store`, `mempalace-server`) and `mempalace-cli/src/main.rs`.

### SQL parameterization

- **`knowledge_graph.rs`**: All 12 SQL statements use `params![]` bindings.
  Zero raw string interpolation. SQL strings are static string literals
  with `?` placeholders only.
- **`lancedb_backend.rs`**: `build_where_clause` constructs filter strings
  for LanceDB's query API. Values pass through `escape_sql_literal` which
  rejects control characters (`\x00..=\x1f`, `\x7f`) and doubles single
  quotes. Test coverage confirms escaping (e.g., `o'reilly`).

### File safety

- **`convo_miner.rs`**: Uses `symlink_metadata` to skip symlinks
  (line 322) and enforces `MAX_FILE_SIZE` of 10 MB (line 326).
- **`ingest.rs`**: Uses `symlink_metadata` to skip symlinks (line 143),
  enforces configurable `max_file_size` defaulting to 10 MB (line 148),
  and tracks skip counts in stats.
- **`normalize.rs`**: Enforces 500 MB hard limit (line 40).
- **`split_mega_files.rs`**: Enforces `MAX_FILE_SIZE` of 500 MB (line 296).

### Secret/credential scan

`grep -rni "password\|secret\|token\|api_key" crates/` — all hits are
innocuous (e.g., `token` in "tokenizer", test fixture strings like
"top secret data", `count_tokens` function). No credentials in source.

### `cargo-deny`

Added `deny.toml` at workspace root for license and advisory policy.

## Why Rust?

Memory safety, single static binary, faster cold start for the MCP server, no Python runtime required, and a cleaner story for "local, offline, no subscription." The Python implementation remains in `legacy/` for reference.
