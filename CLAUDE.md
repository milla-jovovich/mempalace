# CLAUDE.md — memorypalace

## What This Is

JP's fork of [milla-jovovich/mempalace](https://github.com/milla-jovovich/mempalace) — a local AI memory system using ChromaDB for verbatim storage and semantic search.

- **Fork**: `jphein/mempalace` (origin) / `milla-jovovich/mempalace` (upstream)
- **Version**: 3.3.0 (merged upstream v3.3.0 on 2026-04-16)
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
python -m pytest tests/ -q              # ~900 tests (benchmarks deselected)
mempalace status                         # check palace state
mempalace search "query"                 # test search
python -m mempalace.mcp_server           # run MCP server standalone
```

Ruff for linting (`ruff check`), line length 100, target Python 3.9.

## Fork Changes (still ahead of upstream after v3.3.0 merge)

1. **fix: epsilon mtime comparison** — `palace.py` uses `abs() < 0.01` instead of `==` for float mtime dedup
2. **feat: bulk_check_mined()** — paginated pre-fetch of all source_file/mtime pairs for concurrent mining
3. **feat: similarity threshold** — `max_distance` parameter in search, default 1.5 cosine distance in MCP
4. **feat: hooks_cli silent save** — stop hook saves directly via Python API with systemMessage notification, deterministic, zero data loss
5. **feat: tool output mining** — normalize.py captures tool_use/tool_result blocks from Claude Code JSONL with per-tool formatting strategies
6. **fix: convo_miner wing assignment** — `_wing_from_transcript_path()` extracts project name from Claude Code transcript path
7. **perf: graph cache** — `build_graph()` cached module-level with 60s TTL, invalidated on writes via `invalidate_graph_cache()`
8. **perf: L1 importance pre-filter** — `_fetch_drawers()` tries `importance >= 3` first, falls back to full scan only if < 15 results
9. **fix: MCP stale HNSW index** — `_get_client()` detects external writes via mtime (not just inode), `mempalace_reconnect` MCP tool
10. **fix: diary wing assignment** — `tool_diary_write()` accepts optional `wing` param, stop hook derives project wing from transcript path

### Merged into upstream v3.3.0

- BLOB seq_id migration repair (#664), --yes flag (#682), Unicode sanitize_name (#683), VAR_KEYWORD kwargs (#684), MCP tools/export (via #667)

### Superseded by upstream v3.3.0

- Hybrid keyword fallback (#662) — upstream shipped Okapi-BM25
- Batch ChromaDB writes (#629 partial) — upstream has file-level locking
- Inline transcript mining in hooks — upstream uses `mempalace mine` in background

## Upstream PRs

As of 2026-04-16: 5 merged, 7 open, 5 closed. PRs target `develop`.

| PR | Status | Description |
|----|--------|-------------|
| #629 | open (dirty, lower priority) | Batch writes, concurrent mining |
| #632 | open (dirty, lower priority) | Repair, purge, --version |
| #659 | open (clean, waiting review) | Diary wing parameter |
| #660 | open (clean, waiting review) | L1 importance pre-filter |
| #661 | open (feedback addressed, waiting re-review) | Graph cache with write-invalidation |
| #673 | open (clean, rebased against #863) | Deterministic hook saves |
| #681 | open (clean, waiting review) | Unicode checkmark → ASCII (#535) |
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
