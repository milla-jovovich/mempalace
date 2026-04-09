# MemPalace Rust Port — Remediation Plan (100% Pass)

**Branch:** `feat/convert-to-rust`
**Status:** Phases 1–7 committed but several components are stubbed, unused, or missing. This plan takes the port from ~50% to 100%.
**Strategy:** Sequential sub-agent driven. One phase at a time. Prep → delegate → verify → commit → next.

## Audit Findings (what's actually missing)

| # | Gap | Severity | Evidence |
|---|---|---|---|
| 1 | `LanceDbPalace` backend does not exist | **Critical** | `lancedb` and `fastembed` declared in `mempalace-store/Cargo.toml` but zero source references. `palace.rs` only has `InMemoryPalace` with a BoW substring-match fake "search". Doc comment at `palace.rs:8` lies: claims `lancedb_backend` module exists. |
| 2 | `rmcp` MCP transport not wired | **Critical** | `rmcp` declared workspace dep, zero `use rmcp` in any source file. `cmd_mcp` just prints `"mempalace mcp-serve"` but no such subcommand exists. The binary does NOT speak MCP. |
| 3 | `convo_miner` not ported | **High** | Python `convo_miner.py` (380 lines) has no Rust counterpart. No `--mode convos` flag. |
| 4 | `general` extraction not exposed via CLI | **Medium** | `general_extractor.rs` exists but `mine --extract general` flag missing; function only unit-tested. |
| 5 | `compress` CLI command missing | **Medium** | Python `cli.py` has `mempalace compress`; no Rust equivalent. |
| 6 | `cargo audit` not in CI | **Medium** | Phase 7 audit note acknowledged this. |
| 7 | SHA-256 verification of fastembed ONNX blocked by gap #1 | Critical (blocked) | Claimed in Phase 4 audit; cannot exist without fastembed usage. |
| 8 | `fact_checker.py` not ported | **Low** | Python-side never wired into KG per README; skip unless asked. |

## Phase Plan (7 Iterations)

### Iteration R1 — LanceDbPalace backend (fastembed + lancedb)

**Goal:** Real semantic vector store using `lancedb` 0.27.2 + `fastembed` 5 (AllMiniLML6V2, 384-dim).

**Deliverables:**
- `crates/mempalace-store/src/lancedb_backend.rs` — `LanceDbPalace` impls `Palace`.
- Embeddings via `fastembed::TextEmbedding::try_new(AllMiniLML6V2)`.
- Arrow schema: `id: Utf8`, `content: Utf8`, `vector: FixedSizeList<Float32,384>`, metadata cols.
- ANN search via `lancedb::Table::query().nearest_to(vec)`.
- `add/delete/get/list/list_filtered/search` all real.
- Persistent at a user-provided path; uses `tokio` runtime internally (handles sync Palace trait by blocking).
- **OR** — add `async` variant of Palace trait: `PalaceAsync` and make `LanceDbPalace` implement that; adapt ingest/searcher.
- Decision: keep sync `Palace` trait and use `tokio::runtime::Handle::block_on` internally inside `LanceDbPalace`. Rationale: minimal changes to existing callers.
- Fix doc-comment lie in `palace.rs:8`.
- New tests: add/search/delete/filter/persistence round-trip. Ignored by default if model download is required; behind feature flag `lancedb-backend` (default on).
- Offline CI: stub a `TestEmbedder` or gate real-model tests behind `#[ignore]` unless `MEMPALACE_ALLOW_MODEL_DOWNLOAD=1`.

**Verification:** `cargo test -p mempalace-store --features lancedb-backend` passes, at least unit tests for schema & non-model code.

**Commit:** `feat(rust): phase R1 — LanceDbPalace backend with fastembed`

### Iteration R2 — rmcp stdio transport + mcp-serve CLI

**Goal:** Actual MCP server binary over stdio using `rmcp` 0.16.

**Deliverables:**
- `crates/mempalace-server/src/mcp_transport.rs` — `ServerHandler` implementation wrapping `McpServer`.
- Register each of the ~19 tools with descriptions, JSON schemas, and handlers.
- `tokio` runtime, stdin/stdout `Transport::stdio()`.
- New CLI subcommand: `mempalace mcp-serve` (hidden or documented).
- Update `cmd_mcp` help text to reflect reality.
- Integration test: spawn binary, send a JSON-RPC `initialize`, assert response.

**Verification:** `echo '{"jsonrpc":"2.0",...}' | cargo run -- mcp-serve` returns a valid response.

**Commit:** `feat(rust): phase R2 — rmcp stdio transport + mcp-serve subcommand`

### Iteration R3 — convo_miner port

**Goal:** Port `convo_miner.py` (Q/A exchange chunking, format detection).

**Deliverables:**
- `crates/mempalace-server/src/convo_miner.rs` — `ConvoMiner`.
- Support formats: Claude Code JSONL, Claude.ai JSON, ChatGPT JSON, Slack JSON, plain text (via `normalize.rs`).
- Chunk by exchange pair (user+assistant turn).
- Room detection per exchange (via `room_detector`).
- Emit `DrawerRecord` with `hall_events`, `wing`, `room` set.
- Tests: each format parses, chunking, dedup by source+index.

**Verification:** Port all tests from `legacy/tests/test_convo_miner*.py` to Rust. `cargo test -p mempalace-server convo` passes.

**Commit:** `feat(rust): phase R3 — convo_miner with 5 chat format support`

### Iteration R4 — CLI modes: --mode convos, --extract general, compress

**Goal:** Wire the CLI to match Python parity.

**Deliverables:**
- `cmd_mine` takes `--mode {projects|convos}` and `--extract {exchange|general}`.
- New `cmd_compress` that streams drawers through `Dialect::compress` and stores in a sibling collection `mempalace_compressed` (on the LanceDb backend).
- New `cmd_mcp_serve` entry point (from R2).
- Update `--help` text to match.

**Verification:** `mempalace mine --help`, `mempalace compress --help`, smoke tests for each path.

**Commit:** `feat(rust): phase R4 — CLI mode flags, compress, mcp-serve wiring`

### Iteration R5 — Integration tests end-to-end

**Goal:** End-to-end tests that actually exercise the full stack (ingest → search → MCP tool call).

**Deliverables:**
- `crates/mempalace-cli/tests/e2e.rs`:
  - `init → mine projects → search` round-trip via LanceDb (real embeddings — behind feature flag).
  - `init → mine convos → kg_query → traverse`.
  - `mcp-serve` subprocess test: send `initialize`, `tools/list`, `tools/call mempalace_search`.
- Use `tempfile::TempDir` and `assert_cmd::Command` consistently.

**Verification:** `cargo test -p mempalace-cli --test e2e` passes.

**Commit:** `test(rust): phase R5 — end-to-end integration tests`

### Iteration R6 — Security hardening + cargo audit in CI

**Goal:** Close the Phase 7 follow-ups.

**Deliverables:**
- `.github/workflows/rust.yml` — add `cargo install cargo-audit --locked` step and `cargo audit --deny warnings`.
- `cargo deny` config (optional but recommended) pinning banned licenses.
- Re-run `cargo clippy -- -D warnings` across workspace including new crates.
- Audit new code:
  - All SQL uses `params!`.
  - No `unsafe`.
  - No shell spawns (`Command::new("sh")` etc.).
  - File size + symlink checks preserved everywhere new ingest code reads a path.
  - `#![forbid(unsafe_code)]` on every new `lib.rs`.
- Update `RUST_PORT.md` security section with fresh grep commands + results.

**Verification:** CI step passes locally (`cargo audit`).

**Commit:** `chore(rust): phase R6 — cargo audit CI + security re-audit`

### Iteration R7 — Final verification + docs + cleanup

**Goal:** Truth in advertising. Update `RUST_PORT.md` and `README.md` to reflect reality.

**Deliverables:**
- `RUST_PORT.md`: update phase table; move R1–R6 into "post-phase-7 remediation"; update test counts; update audit results.
- `README.md` Rust banner: confirm parity claims.
- `cargo test --workspace` — all tests pass, new counts recorded.
- `cargo clippy --workspace --all-targets -- -D warnings` — clean.
- `cargo fmt --check` — clean.
- Final Oracle review via ultrawork loop verification step.

**Verification:** Full workspace test + clippy + fmt clean. Oracle-verified.

**Commit:** `docs(rust): phase R7 — update RUST_PORT.md with R1–R7 remediation`

## Commit discipline

One commit per iteration. Each commit message:

```
feat(rust): phase Rn of 7 — <summary>

<bullet list of what changed>
<test counts>
<any new deps>
```

No merges, no rebases. Linear history.

## Sub-agent driven, no parallelism

Each iteration:
1. I prepare a detailed spec (this plan + current-state summary).
2. I dispatch ONE sub-agent (`ultrabrain` / `deep` / `artistry`) with the spec.
3. I verify results: build, test, clippy, manual inspection.
4. I commit.
5. I move to the next iteration.

No parallel sub-agents. No skipping phases.
