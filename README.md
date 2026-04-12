<div align="center">

<img src="assets/mempalace_logo.png" alt="MemPalace" width="280">

# MemPalace (jphein fork)

**JP's production fork of [milla-jovovich/mempalace](https://github.com/milla-jovovich/mempalace)**

[![version-shield]][release-link]
[![python-shield]][python-link]
[![license-shield]][license-link]

</div>

---

## What This Is

A local AI memory system that stores every conversation, decision, and debugging session verbatim in ChromaDB. Semantic search finds anything instantly. No cloud, no API keys, no summarization — raw storage with structure.

This fork runs in production on my workstation with 134K+ drawers across 60+ rooms. Everything below is battle-tested.

## What's Different From Upstream

21 fork changes, all submitted as [upstream PRs](#upstream-prs). The highlights:

### Reliability
- **Stale HNSW detection** — MCP server detects external writes via mtime, auto-reconnects. Manual `mempalace_reconnect` tool for cache invalidation.
- **BLOB seq_id auto-repair** — Fixes the chromadb 0.6.x to 1.5.x migration crash (`Rust type u64 is not compatible with SQL type BLOB`) automatically before every client init.
- **Epsilon mtime comparison** — `abs() < 0.01` instead of `==` for float mtime dedup, preventing unnecessary re-mining.

### Performance
- **Batch ChromaDB writes** — One upsert per file instead of per chunk. Concurrent mining with ThreadPoolExecutor.
- **Graph cache** — `build_graph()` cached module-level with 60s TTL, invalidated on writes.
- **L1 importance pre-filter** — Tries `importance >= 3` first, falls back to full scan only if < 15 results.

### Features
- **Hybrid search fallback** — Keyword text-match via `where_document.$contains` when vector results are poor. Auto-extracts most distinctive token.
- **Tool output mining** — `normalize.py` captures tool_use/tool_result blocks from Claude Code JSONL with per-tool formatting (Bash head+tail, Read/Edit/Write path-only, Grep/Glob capped).
- **Hook system** — Stop hook saves directly via Python API with single-line `systemMessage` notification. Auto-mines JSONL transcripts. PreCompact hook for emergency save before context compression.
- **Diary wing routing** — `diary_write`/`diary_read` accept optional `wing` param. Stop hook derives project wing from transcript path.
- **New MCP tools** — `get_drawer`, `list_drawers`, `update_drawer`, `hook_settings`, `memories_filed_away`, `reconnect`. Palace export to markdown/JSON.
- **Entity detector** — 73 technical STOPWORDS added (Handler, Node, Service, etc.) to reduce false positives.

### Infrastructure
- **chromadb >= 1.5.4** — Upgraded from 0.6.x pin with auto-migration support.
- **CLI** — `mempalace --version`, repair nuke-rebuild, purge command.
- **Search** — `max_distance` parameter (L2 distance threshold), default 1.5 in MCP.

## Setup

```bash
git clone https://github.com/jphein/mempalace.git
cd mempalace
python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"

mempalace init ~/Projects --yes
mempalace mine ~/Projects/myproject
mempalace status
```

### MCP Server (Claude Code / Cursor / Gemini)

```bash
# Claude Code plugin (recommended)
claude plugin marketplace add milla-jovovich/mempalace
claude plugin install --scope user mempalace

# Or manual MCP
claude mcp add mempalace -- python -m mempalace.mcp_server
```

22 MCP tools available: search, diary, drawers, knowledge graph, palace graph traversal, taxonomy, export.

### Hooks

The plugin includes auto-save hooks:

- **Stop hook** — Every 15 messages, auto-mines the JSONL transcript into the palace, then saves a diary entry with theme extraction. Shows `"✦ N memories woven into the palace"` as a terminal notification.
- **PreCompact hook** — Fires before context compression. Emergency save of everything before context is lost.

Set `MEMPAL_DIR` to auto-mine a directory on each save trigger. Set `MEMPAL_PYTHON` to specify the Python interpreter (auto-detects repo venv if not set).

## Development

```bash
source venv/bin/activate
python -m pytest tests/ -x -q           # 701 tests expected
mempalace status                         # palace health
ruff check . && ruff format --check .    # lint + format
```

## Upstream PRs

All fork changes submitted as separate focused PRs to [milla-jovovich/mempalace](https://github.com/milla-jovovich/mempalace), targeting `develop`:

| PR | Type | Description |
|----|------|-------------|
| [#626](https://github.com/milla-jovovich/mempalace/pull/626) | fix | Standalone bug fixes |
| [#629](https://github.com/milla-jovovich/mempalace/pull/629) | perf | Batch writes, concurrent mining |
| [#632](https://github.com/milla-jovovich/mempalace/pull/632) | feat | Repair, purge, --version |
| [#633](https://github.com/milla-jovovich/mempalace/pull/633) | feat | Hook capture, auto-mine transcripts |
| [#635](https://github.com/milla-jovovich/mempalace/pull/635) | feat | New MCP tools, export |
| [#659](https://github.com/milla-jovovich/mempalace/pull/659) | fix | Diary wing parameter |
| [#660](https://github.com/milla-jovovich/mempalace/pull/660) | perf | L1 importance pre-filter |
| [#661](https://github.com/milla-jovovich/mempalace/pull/661) | perf | Graph cache with write-invalidation |
| [#662](https://github.com/milla-jovovich/mempalace/pull/662) | feat | Hybrid search fallback |
| [#663](https://github.com/milla-jovovich/mempalace/pull/663) | fix | Stale HNSW mtime detection |
| [#664](https://github.com/milla-jovovich/mempalace/pull/664) | fix | BLOB seq_id migration repair |

## License

MIT — see [LICENSE](LICENSE).

<!-- Link Definitions -->
[version-shield]: https://img.shields.io/badge/version-3.1.0-4dc9f6?style=flat-square&labelColor=0a0e14
[release-link]: https://github.com/jphein/mempalace/releases
[python-shield]: https://img.shields.io/badge/python-3.9+-7dd8f8?style=flat-square&labelColor=0a0e14&logo=python&logoColor=7dd8f8
[python-link]: https://www.python.org/
[license-shield]: https://img.shields.io/badge/license-MIT-b0e8ff?style=flat-square&labelColor=0a0e14
[license-link]: https://github.com/jphein/mempalace/blob/main/LICENSE
