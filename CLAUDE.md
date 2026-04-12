# CLAUDE.md — memorypalace

## What This Is

JP's fork of [milla-jovovich/mempalace](https://github.com/milla-jovovich/mempalace) — a local AI memory system using ChromaDB for verbatim storage and semantic search.

- **Fork**: `jphein/mempalace` (origin) / `milla-jovovich/mempalace` (upstream)
- **Version**: 3.1.0 + local fixes
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
python -m pytest tests/ -x -q           # run tests (701 expected)
mempalace status                         # check palace state
mempalace search "query"                 # test search
python -m mempalace.mcp_server           # run MCP server standalone
```

Ruff for linting (`ruff check`), line length 100, target Python 3.9.

## Fork Changes (ahead of upstream)

1. **fix: epsilon mtime comparison** — `palace.py` uses `abs() < 0.01` instead of `==` for float mtime dedup
2. **feat: bulk_check_mined()** — paginated pre-fetch of all source_file/mtime pairs
3. **fix: MCP server** — search limit capped [1,100], status/taxonomy tools paginated past 10K, duplicate cache decls removed
4. **perf: batch ChromaDB writes** — one upsert per file instead of per chunk in both miners
5. **fix: entity detector STOPWORDS** — 73 technical terms added (Handler, Node, Service, etc.)
6. **feat: similarity threshold** — `max_distance` parameter in search (renamed from `min_similarity`), default 1.5 cosine distance in MCP
7. **feat: hooks_cli** — stop hook saves directly via Python API with systemMessage notification, precompact blocks for AI-driven save, auto-ingest transcripts
8. **feat: --version flag** — CLI supports `mempalace --version` (from upstream PR #559 pattern)
9. **feat: tool output mining** — normalize.py captures tool_use/tool_result blocks from Claude Code JSONL with per-tool formatting strategies (Bash head+tail, Read/Edit/Write path-only, Grep/Glob capped)
10. **fix: dry-run room=None crash** — miner.py handles None room from unreadable files (#586)
11. **fix: precompact hook SESSION_ID sanitization** — applies same safe() regex as save hook (#589)
12. **feat: chromadb >=1.5.4** — upgraded from 0.6.x pin, auto-migrates existing databases (#581)
13. **feat: hooks auto-mine transcript** — both hooks now auto-mine JSONL transcript into palace (captures raw tool output), updated reason messages to request verbatim tool output, MP_PYTHON auto-detection
14. **feat: hybrid search fallback** — keyword text-match via `where_document.$contains` when vector results are poor (best distance > 1.0), `_extract_keyword()` picks most distinctive token, MCP `keyword` param
15. **fix: convo_miner wing assignment** — `_wing_from_transcript_path()` extracts project name from Claude Code transcript path instead of hardcoding `sessions`
16. **fix: chromadb BLOB seq_id migration** — auto-repairs 0.6.x→1.5.x migration bug where `seq_id` stored as BLOB crashes the Rust compactor, runs before every `PersistentClient` init
17. **perf: graph cache** — `build_graph()` cached module-level with 60s TTL, invalidated on writes via `invalidate_graph_cache()`
18. **perf: L1 importance pre-filter** — `_fetch_drawers()` tries `importance >= 3` filter first, falls back to full scan only if < 15 results
19. **fix: MCP stale HNSW index** — `_get_client()` detects external writes via mtime (not just inode), new `mempalace_reconnect` MCP tool for manual cache invalidation
20. **fix: diary wing assignment** — `tool_diary_write()` accepts optional `wing` param, stop hook derives project wing from transcript path instead of hardcoding `wing_session-hook`
21. **merge: upstream/develop** — backend seam (`backends/chroma.py`), expanded room detector, fixed `_fix_blob_seq_ids` import path after upstream refactor
22. **merge: upstream #647 + #667** — security hardening (input validation, WAL hardening, arg whitelisting), plus bensig's 5 fixes from #667 (similarity→distance conversion, structured error reporting, inode cache fix, pagination guard, conditional KG init)

## Upstream PRs

All fork changes submitted as separate focused PRs targeting `develop`. First PR merged 2026-04-12:

| PR | Status | Description |
|----|--------|-------------|
| #626 | **closed** | Standalone bug fixes (split into #681-684) |
| #629 | open | Batch writes, concurrent mining |
| #632 | open | Repair, purge, --version |
| #633 | **closed** | Hook capture (superseded, resubmitted as #673) |
| #635 | **merged** via #667 | New MCP tools, export |
| #659 | open | Diary wing parameter |
| #660 | open | L1 importance pre-filter |
| #661 | open | Graph cache with write-invalidation |
| #662 | open | Hybrid search fallback |
| #663 | open | Stale HNSW mtime detection |
| #664 | **merged** | BLOB seq_id migration repair |
| #673 | open | Deterministic hook saves (replaces #633) |
| #681 | open | Unicode checkmark → ASCII (#535) |
| #682 | open | --yes flag for init (#534) |
| #683 | open | Unicode sanitize_name (#637) |
| #684 | open | VAR_KEYWORD kwargs check (#572) |

## Two-Layer Memory Architecture

Claude Code has two complementary memory layers, used in tandem:

- **Auto-memory** (`~/.claude/projects/*/memory/`) — lightweight preferences, context, feedback. Manual writes only. (Unreleased "Auto Dream" consolidation exists in source but is behind a disabled feature flag.)
- **MemPalace** (`~/.mempalace/palace/`, 134K+ drawers) — verbatim conversations, tool output, code. Write-only archive, searchable via MCP. Completeness is the feature.

Both systems coexist. Hook saves are scoped to MemPalace ("For THIS save, use MemPalace MCP tools only") — this is not a permanent ban on auto-memory.

## Hook Save Architecture

Two save modes, controlled by `hook_silent_save` in `~/.mempalace/config.json`:

- **Silent mode** (default, `hook_silent_save: true`): Direct Python API call to `tool_diary_write()`. Plain text, no AI involved, deterministic — save marker advances only after confirmed write. Shows `"✦ N memories woven into the palace"` as terminal notification.
- **Block mode** (legacy, `hook_silent_save: false`): Returns `{"decision": "block"}` asking the AI to call MCP tools. Non-deterministic — AI may ignore, summarize, or fail. Save marker advances before AI acts (data loss risk).

Both modes also auto-mine the JSONL transcript into the palace (raw tool output capture).

### AAAK and Save Paths

AAAK (`mempalace/dialect.py`) is upstream's compressed symbolic summary format. It is a prompt convention in MCP tool descriptions, not enforced by code. `tool_diary_write()` accepts any string.

- **Silent mode**: No AI reads tool descriptions. Diary entries are plain English. AAAK is irrelevant.
- **Block mode**: AI sees AAAK instructions in `diary_write` tool description and may use the format.

## Integration

- **Claude Code plugin**: installed at user scope via marketplace
- **MCP server**: global user scope — available in all projects
- **Stop hook**: fires every 15 messages, saves diary entry + auto-mines transcript
- **PreCompact hook**: emergency save before context compaction, auto-mines transcript, finds transcript by session_id fallback

## Testing

Always run `python -m pytest tests/ -x -q` after changes. 704 tests expected to pass. Benchmark and stress tests are excluded by default (use `-m benchmark` or `-m stress` to include).
