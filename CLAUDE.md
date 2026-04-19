# CLAUDE.md — memorypalace

## What This Is

JP's fork of [milla-jovovich/mempalace](https://github.com/milla-jovovich/mempalace) — a local AI memory system using ChromaDB for verbatim storage and semantic search.

- **Fork**: `jphein/mempalace` (origin) / `milla-jovovich/mempalace` (upstream)
- **Version**: 3.3.1 (merged upstream v3.3.1 on 2026-04-18)
- **Python**: venv at `./venv/`, editable install with dev deps
- **Palace data**: `~/.mempalace/palace` (ChromaDB) + `~/.mempalace/config.json`

## Key Files

- `~/Projects/mempalace.yaml` — **do not delete**. Mining config with wing/room definitions. Regenerate with `mempalace init ~/Projects --yes` if lost.
- `~/.mempalace/config.json` — topic wings and hall keywords, customized for JP's domains (infrastructure, development, tools, creative, projects, system).
- `~/.mempalace/palace/` — ChromaDB vector store. The actual data.
- `~/.mempalace/hook_state/` — stop hook session tracking.

## Development

```bash
source venv/bin/activate
python -m pytest tests/ -q              # ~1063 tests (benchmarks deselected)
mempalace status                         # check palace state
mempalace search "query"                 # test search
python -m mempalace.mcp_server           # run MCP server standalone
```

Ruff for linting (`ruff check`), line length 100, target Python 3.9.

## Fork Changes (still ahead of upstream after v3.3.1 merge)

1. **feat: bulk_check_mined()** — paginated pre-fetch of all source_file/mtime pairs for concurrent mining (fork-only; independent of the mtime comparison fix, which has since been upstreamed)
2. **feat: similarity threshold** — `max_distance` parameter in search, default 1.5 cosine distance in MCP
3. **feat: hooks_cli silent save** — stop hook saves directly via Python API with systemMessage notification, deterministic, zero data loss
4. **feat: `mempal_save_hook.sh` Python auto-detection** — checks `MEMPAL_PYTHON` env var → repo venv → system `python3`; no hardcoded path required
5. **fix: convo_miner wing assignment** — `_wing_from_transcript_path()` extracts project name from Claude Code transcript path
6. **perf: graph cache** — `build_graph()` cached module-level with 60s TTL, invalidated on writes via `invalidate_graph_cache()`
7. **perf: L1 importance pre-filter** — `_fetch_drawers()` tries `importance >= 3` first, falls back to full scan only if < 15 results
8. **fix: MCP stale HNSW index** — `_get_client()` detects external writes via mtime (not just inode), `mempalace_reconnect` MCP tool
9. **fix: diary wing assignment** — `tool_diary_write()` accepts optional `wing` param, stop hook derives project wing from transcript path
10. **fix: `.blob_seq_ids_migrated` marker** — skip Python `sqlite3.connect()` against a live ChromaDB 1.5.x DB after first successful migration; opening the sqlite file from Python corrupts the next `PersistentClient` call
11. **feat: `quarantine_stale_hnsw()`** — rename HNSW segment dirs whose `data_level0.bin` is 1h+ older than `chroma.sqlite3`, sidestepping the read-path SIGSEGV from dangling neighbor pointers (same failure mode as neo-cortex-mcp#2, mempalace#823)
12. **feat: search warnings + sqlite BM25 top-up** — `search_memories()` returns `warnings: [...]` and `available_in_scope: N` whenever the vector path underdelivers (sparse HNSW after repair, `#951` filter-planner failure, drift). Fallback promotes BM25-ranked sqlite candidates tagged `matched_via: "sqlite_bm25_fallback"`. Closes the "silent 0-hit when data is in sqlite" failure mode. CLI `search()` delegates to `search_memories()` so both paths share the fallback.
13. **fix: stop_hook_active guard** — guard only applies in block mode; silent mode skips it so Claude Code 2.1.114's plugin dispatch (which sets `stop_hook_active:true` on every fire after the first) doesn't suppress subsequent auto-saves
14. **fix: `_output()` stdout routing** — uses `sys.modules.get()` to find an already-loaded `mcp_server` and reuse its `_REAL_STDOUT_FD`; otherwise writes directly to fd 1. Avoids importing `mcp_server` cold (which would trigger its stdout→stderr redirect as a side effect). Write-all loop handles partial `os.write()` returns.
15. **fix: `_get_client()` get-then-create guard** — `get_or_create_collection` segfaults ChromaDB 1.5.x when existing collection metadata differs; fork tries `get_collection` first, falls back to `create_collection` only on `InvalidCollectionException`.
16. **perf: `miner.status()` paginated `col.get()`** — upstream's single `col.get(limit=total)` hits SQLite's max-variable limit on palaces with many thousands of drawers; fork paginates in 10 K-drawer batches.
17. **feat: configurable chunking parameters** — `chunk_size` (800), `chunk_overlap` (100), `min_chunk_size` (50) written to `config.json` and exposed via `MempalaceConfig` properties.
18. **fix: PID file guard prevents stacking mine processes** — `_mine_already_running()` checks `hook_state/mine.pid` via `os.kill(pid, 0)`; both `_ingest_transcript` and `_maybe_auto_ingest` bail if a mine is already running. Observed without fix: 4 concurrent mines at ~770% CPU.

### Merged into upstream (post-v3.3.1)

- epsilon mtime comparison (upstream PR #610, merged 2026-04-12 by Arnold Wender — their threshold is 0.001, ours was 0.01, semantically equivalent)
- `None`-metadata guards across 8 read-path loops — searcher.py, miner.status, 4 mcp_server handlers (#999, merged 2026-04-18)

### Merged into upstream v3.3.0

- BLOB seq_id migration repair (#664), --yes flag (#682), Unicode sanitize_name (#683), VAR_KEYWORD kwargs (#684), MCP tools/export (via #667)

### Pulled in from upstream v3.3.1 (merged 2026-04-18)

- Multi-language entity detection (Portuguese, Russian, Italian, Hindi, Indonesian, Chinese); BCP-47 case-insensitive locales; script-aware word boundaries for Devanagari/Arabic/Hebrew/Thai
- UTF-8 encoding on `Path.read_text()` (#946) — fixes Windows GBK/non-UTF-8 locales
- Non-blocking precompact hook (#863) — replaces our fork's blocking precompact
- Basic `silent_save` honoring in stop hook (#966) — narrower than our fork's deterministic-save architecture, so we keep #673's version

### Pulled in from upstream/develop (merged 2026-04-19)

- RFC 002 §9 scaffolding: `BaseSourceAdapter`, `PalaceContext`, registry, transforms (`mempalace/sources/`) — #1014
- `chromadb >=1.5.4,<2` — Python 3.13/3.14 compat, version cap guards future major breakage — #1010
- `Layer3.search_raw` None guard — #1013
- Sweeper + tandem transcript safety net — prevents silent drop of `.jsonl` files — #998
- `_validate_where()` operator validator (RFC 001 §1.4) — unknown operators raise `UnsupportedFilterError` instead of silently dropping — #995
- RFC 002 spec docs (`docs/rfcs/002-source-adapter-plugin-spec.md`) — #990
- Landing page redesign — #984
- `sweep` CLI command added alongside existing `export`
- `.jsonl` added to `READABLE_EXTENSIONS` — same SHA (560fdbd), upstream-authored, not a fork contribution. Related: upstream also raised `MAX_FILE_SIZE` 10MB → 500MB in d137d12.

### Superseded by upstream

- Hybrid keyword fallback (#662) — upstream shipped Okapi-BM25
- Batch ChromaDB writes (#629 partial) — upstream has file-level locking
- Inline transcript mining in hooks — upstream uses `mempalace mine` in background

## Upstream PRs

As of 2026-04-19: 6 merged, 8 open, 7 closed. PRs target `develop`. Fork `main` tracks `upstream/develop`.

| PR | Status | Description |
|----|--------|-------------|
| #659 | open (`MERGEABLE`, waiting review) | Diary wing parameter |
| #660 | open (`MERGEABLE`, waiting review) | L1 importance pre-filter |
| #661 | open (feedback addressed, waiting `@bensig` re-review) | Graph cache with write-invalidation |
| #673 | open (APPROVED externally 2026-04-12, waiting maintainer merge) | Deterministic hook saves (broader than upstream's #966) |
| #681 | open (clean, waiting review) | Unicode checkmark → ASCII (#535) |
| #999 | **merged** 2026-04-18 | `None`-metadata guards in `searcher.py`, `miner.status()`, and 4 `mcp_server.py` handlers |
| #1000 | open (CI green all platforms, Copilot + Dialectician review addressed, waiting maintainer) | `quarantine_stale_hnsw()` for HNSW/sqlite drift |
| #1005 | open (CI green all platforms, Copilot + Dialectician review addressed, waiting maintainer) | Warnings + sqlite BM25 top-up when vector underdelivers (never silent miss) |
| #1021 | open (CI green all platforms, Copilot review addressed, waiting maintainer) | Hook stdout routing + silent_save guard fixes for Claude Code 2.1.114 |
| #629 | **closed** | Superseded — upstream shipped batching + file locking |
| #632 | **closed** | Superseded — `--version`, `purge`, `repair` all shipped in v3.3.0 |
| #664 | **merged** | BLOB seq_id migration repair |
| #682 | **merged** | --yes flag for init (#534) |
| #683 | **merged** | Unicode sanitize_name (#637) |
| #684 | **merged** | VAR_KEYWORD kwargs check (#572) |
| #635 | **merged** via #667 | New MCP tools, export |
| #662 | **closed** | Hybrid search fallback (superseded by upstream BM25) |
| #738 | **closed** | Docs: MCP tools reference (stale after v3.3.0) |
| #663 | **closed** | Stale HNSW mtime detection (upstream wrote #757) |
| #626 | **closed** | Split into #681-684 |
| #633 | **closed** | Resubmitted as #673 |

## Two-Layer Memory Architecture

Claude Code has two complementary memory layers, used in tandem:

- **Auto-memory** (`~/.claude/projects/*/memory/`) — lightweight preferences, context, feedback. Manual writes only. (Unreleased "Auto Dream" consolidation exists in source but is behind a disabled feature flag.)
- **MemPalace** (`~/.mempalace/palace/`, 134K+ drawers) — verbatim conversations, tool output, code. Write-only archive, searchable via MCP. Completeness is the feature.

Both systems coexist. Hook saves are scoped to MemPalace ("For THIS save, use MemPalace MCP tools only") — this is not a permanent ban on auto-memory.

## Hook Save Architecture

Two save modes, controlled by `hook_silent_save` in `~/.mempalace/config.json`:

- **Silent mode** (default, `hook_silent_save: true`): Direct Python API call to `tool_diary_write()`. Plain text, no AI involved, deterministic — save marker advances only after confirmed write. Shows `"✦ N memories woven into the palace"` as terminal notification.
- **Block mode** (legacy, `hook_silent_save: false`): Returns `{"decision": "block"}` asking the AI to call MCP tools. Non-deterministic — AI may ignore, summarize, or fail. Save marker advances before AI acts (data loss risk).

**v3.3.0 change:** Upstream hooks now return `"decision": "allow"` (background save, no AI blocking) instead of `"decision": "block"`. This aligns with our silent mode direction — the AI never needs to act on saves.

## Integration

- **Claude Code plugin**: installed at user scope via marketplace
- **MCP server**: global user scope — available in all projects
- **Stop hook**: fires every 15 messages, saves diary entry + auto-mines transcript
- **PreCompact hook**: emergency save before context compaction, auto-mines transcript, finds transcript by session_id fallback

## Testing

Always run `python -m pytest tests/ -x -q` after changes. Benchmark and stress tests are excluded by default (use `-m benchmark` or `-m stress` to include).
