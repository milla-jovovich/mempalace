# MemPalace Rust Port — Master Plan

**Branch**: `feat/convert-to-rust`
**Starting commit**: `2981433` (fix: add mcp command with setup guidance)
**Scope**: Convert ~9,200 LoC Python + ~6,400 LoC tests to pure Rust, 5-crate workspace, all unit tests passing, security audit clean.
**Estimated iterations**: 7 happy path, 10-12 realistic (per Oracle).
**Author**: Sisyphus
**References**: `.sisyphus/research/01-rust-stack.md`, `02-module-map.md`, `03-test-map.md`

## Stack (decided)

- `lancedb` 0.27 (vector store, replaces ChromaDB)
- `fastembed` 5 (all-MiniLM-L6-v2 embeddings, identical 384-dim vectors)
- `rmcp` 0.16 (official MCP SDK, stdio, `#[tool]` macro); fallback: hand-rolled JSON-RPC if immature
- `rusqlite` 0.39 bundled (KG)
- `tokio` 1, `clap` 4 derive, `regex` 1, `ignore` 0.4, `serde` 1, `serde_json`, `serde_yml`, `ureq` 2 (Wikipedia sync HTTP), `sha2` 0.10 (preserve drawer ID compat), `thiserror` 2, `anyhow` 1, `tracing` 0.1 + `tracing-subscriber` 0.3, `lzma-sys` static feature.

## Workspace structure (5 crates, per Oracle)

```
mempalace/                          ← repo root (Cargo workspace)
├── Cargo.toml                      ← [workspace]
├── rust-toolchain.toml             ← pinned stable
├── .github/workflows/rust.yml      ← CI
├── crates/
│   ├── mempalace-core/             ← error types, config, version, path/sanitize helpers
│   ├── mempalace-text/             ← dialect, normalize, entity_*, spellcheck, room_detector,
│   │                                   split_mega_files, general_extractor
│   ├── mempalace-store/            ← lancedb vector store (palace) + rusqlite KG + graph + layers
│   ├── mempalace-server/           ← mcp server, hooks, onboarding, searcher, instructions
│   │                                   ingest (miner + convo_miner)
│   └── mempalace-cli/              ← binary crate, thin wrapper
├── legacy/                         ← (Phase 7) old Python moves here
└── tests/ (at crate level only)
```

Each crate: `#![forbid(unsafe_code)]`, `#![deny(clippy::all)]` in `lib.rs`. Public APIs use `thiserror` error enums.

## Phase-by-phase plan

### Phase 1 — Skeleton + CI (this iteration)

1. Delete `uv.lock` and leave `pyproject.toml` untouched (still needed to run Python tests during transition).
2. Create workspace `Cargo.toml` with 5 member crates.
3. Create 5 empty crates with `Cargo.toml` + `src/lib.rs` stub (`#![forbid(unsafe_code)]`).
4. Make `mempalace-cli` a binary crate producing `mempalace` executable.
5. Create `rust-toolchain.toml` pinning stable.
6. Write `.github/workflows/rust.yml` running: `cargo fmt --check`, `cargo clippy --workspace --all-targets -- -D warnings`, `cargo test --workspace --all-targets -- --test-threads=1`, `cargo audit`.
7. Update `.gitignore` to ignore `target/`, keep ignoring Python cache.
8. Create `RUST_PORT.md` at root documenting status: phase, what's ported, what isn't.
9. `cargo check --workspace` must pass locally (assuming cargo is present).
10. Commit: `chore(rust): phase 1 — cargo workspace skeleton and CI`.

### Phase 2 — `mempalace-core`

Port (all Tier-0 pure-logic items):
- `version.py` → `core::version::VERSION` constant
- `config.py` → `core::config::Config` (serde), `core::sanitize::{sanitize_name, sanitize_content}`
- Error types → `core::error::{CoreError, PathError, ValidationError}` via `thiserror`
- Path helpers → `core::paths::{default_palace_path, default_config_dir, ensure_private_dir}` (secure 0o700 on Unix)

Port tests:
- test_config.py (4), test_config_extra.py (10), test_version_consistency.py (2) → 16 test fns in `crates/mempalace-core/tests/`.

Verify: `cargo test -p mempalace-core` green, `cargo clippy -p mempalace-core -- -D warnings` clean.

Commit: `feat(rust): phase 2 — core crate with config, sanitization, and path helpers`.

### Phase 3 — `mempalace-text` (split into 3 parallel sub-agents)

**Sub-agent A**: `dialect.py` (1075 LoC) + `entity_registry.py` (639 LoC, HTTP Wikipedia lookup via `ureq`).
**Sub-agent B**: `normalize.py` (334 LoC, all 6 chat formats) + `split_mega_files.py` (317 LoC) + `spellcheck.py` (269 LoC, uses `EntityRegistry`).
**Sub-agent C**: `entity_detector.py` (853 LoC, 47 parameterized patterns) + `general_extractor.py` (521 LoC, 80+ regex markers) + `room_detector_local.py` (310 LoC).

All three share the same crate but are independent modules. Each agent runs `cargo test -p mempalace-text` before reporting done.

Port tests:
- test_dialect.py (16), test_entity_registry.py (20), test_normalize.py (32),
  test_split_mega_files.py (17), test_spellcheck.py (16), test_spellcheck_extra.py (5),
  test_entity_detector.py (18), test_general_extractor.py (19), test_room_detector_local.py (15).
- Total: 158 test functions.

Verify: `cargo test -p mempalace-text`, `cargo clippy -p mempalace-text -- -D warnings`, `cargo audit`.

Commit: `feat(rust): phase 3 — text crate (dialect, normalize, entity detection, extractors)`.

### Phase 4 — `mempalace-store` (split into 2 parallel sub-agents)

**Sub-agent A — vector**: `palace.py` + vector store via `lancedb` + `fastembed` (embedding model). Arrow schema matching the 16 ChromaDB metadata keys. Tokio runtime for async ops; sync facade via `block_on` for non-async callers.

**Sub-agent B — KG + graph + layers**: `knowledge_graph.py` via `rusqlite` bundled WAL + 4 indexes (exact Python schema), `palace_graph.py` BFS + tunnels, `layers.py` L0/L1/L2/L3 + `MemoryStack`.

Port tests:
- test_knowledge_graph.py (17), test_knowledge_graph_extra.py (7), test_palace_graph.py (17),
  test_layers.py (30), test_searcher.py (14) — searcher lives in server but its tests drive the store.
- Total: 85 test functions (not counting searcher's 14 which stay in server).

Embedding model: on first use, fastembed downloads ONNX to `~/.cache/fastembed/`. Add SHA256 verification against a hardcoded expected hash (Oracle rec. k).

Verify: `cargo test -p mempalace-store -- --test-threads=1`, clippy, audit.

Commit: `feat(rust): phase 4 — store crate (lancedb vector, rusqlite kg, graph, layers)`.

### Phase 5 — `mempalace-server` (single agent)

Ingest (miner.py 641 + convo_miner.py 380), searcher.py 152, onboarding.py 489, hooks_cli.py 226, instructions_cli.py 28, mcp_server.py 946.

MCP tools (19): use `rmcp` with `#[tool]` macro, one handler per tool. Fallback to hand-rolled JSON-RPC if rmcp doesn't fit.

Port tests:
- test_mcp_server.py (25), test_miner.py (13), test_convo_miner.py (1),
  test_convo_miner_unit.py (12), test_hooks_cli.py (21),
  test_instructions_cli.py (4), test_onboarding.py (32), test_searcher.py (14).
- Total: 122 test functions.

Security: symlink check (Oracle i), MAX_FILE_SIZE (j), WAL integrity (l), no shell exec for hooks (m).

Add test for `mempalace_get_aaak_spec` MCP tool (gap in Python tests).

Verify: `cargo test -p mempalace-server -- --test-threads=1`, clippy, audit.

Commit: `feat(rust): phase 5 — server crate (ingest, searcher, mcp, hooks, onboarding)`.

### Phase 6 — `mempalace-cli` binary + integration tests

`cli.py` 574 → `mempalace-cli` binary. `clap` derive. 11 subcommands (`status`, `search`, `init`, `mine`, `wake-up`, `split`, `mcp`, `repair`, `compress`, `hook run`, `instructions`).

Port tests:
- test_cli.py (33) — integration tests that spawn the compiled binary via `assert_cmd`.

End-to-end smoke: `cargo run -- status` against a temp palace. Build release binary: `cargo build --release`.

Verify: `cargo test --workspace -- --test-threads=1`, clippy `--workspace --all-targets -- -D warnings`, `cargo audit`, `cargo fmt --check`.

Commit: `feat(rust): phase 6 — cli binary and end-to-end integration tests`.

### Phase 7 — Audit, legacy move, final polish

1. `cargo clippy --workspace --all-targets --all-features -- -D warnings -W clippy::pedantic`
2. `cargo audit`
3. `cargo deny check` (if present) — check licenses
4. Run full `cargo test --workspace -- --test-threads=1` one more time.
5. Verify every crate has `#![forbid(unsafe_code)]`.
6. Verify filesystem path canonicalization in all user-input paths.
7. Verify parameterized SQL in all rusqlite call sites (grep for `format!(` near sql).
8. Move `mempalace/` (Python) → `legacy/mempalace/`; `tests/` → `legacy/tests/`; `pyproject.toml` → `legacy/pyproject.toml`; `uv.lock` → `legacy/`.
9. Update `README.md` with Rust build/install instructions; archive old sections to `legacy/README.md`.
10. Update `.github/workflows/rust.yml` to be the primary (remove Python CI if present).
11. `cargo test --workspace --release` green.

Commit: `feat(rust): phase 7 — security audit, legacy python move, final polish`.

## "Pass all tests" definition (per Oracle)

- **Port all unit tests (all 25 files, ~315 test functions)** to Rust equivalents.
- **Exclude `tests/benchmarks/`** (9 files, ~68 tests). These are performance characterization, not correctness, and depend on exact ChromaDB numerics. Document as future work.
- **Accept structural, not numeric, parity** on integration tests that touched ChromaDB — we verify metadata/ordering/presence, not cosine similarities to N decimals.
- **Close test gap**: add test for `mempalace_get_aaak_spec` MCP tool (never tested in Python).

## Security checklist (per Oracle + my baseline)

- [ ] `#![forbid(unsafe_code)]` on every crate (lib and bin)
- [ ] All filesystem paths validated with `Path::canonicalize` and checked to stay under an allowed base
- [ ] No shell invocations for user-controlled input (hook scripts become pure Rust)
- [ ] Parameterized SQL only in rusqlite (audit via grep in Phase 7)
- [ ] `#[serde(deny_unknown_fields)]` on all config structs
- [ ] Explicit `thiserror` error types; no `unwrap()`/`expect()` in library code (allow in tests)
- [ ] `cargo audit` in CI
- [ ] 0o700 on palace dir, 0o600 on config file on Unix
- [ ] Symlink check before following (std::fs::symlink_metadata)
- [ ] MAX_FILE_SIZE=500MB in normalize (matches Python), MAX_FILE_SIZE=10MB in miner
- [ ] ONNX model SHA-256 verification after fastembed download
- [ ] WAL is line-delimited JSON; corrupted lines skipped, not crash
- [ ] Name sanitizer rejects `..`, `/`, `\`, null bytes, >128 chars (matches Python)
- [ ] Content sanitizer rejects null bytes, >100k chars (matches Python)

## Commit discipline

- 7 commits (one per phase). Each must pass `cargo test` + `cargo clippy -D warnings` + `cargo fmt --check` + `cargo audit`.
- Never use `--amend` after pushing. Never `git push --force`.
- Never commit without being asked. But the user explicitly said "commit in phases" — we treat that as permission for these 7 commits on this branch.

## Status tracking

Keep `.sisyphus/plans/rust-port.md` (this file) and `RUST_PORT.md` at root in sync. Mark phases complete as we go.
