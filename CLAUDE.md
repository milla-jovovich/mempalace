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
python -m pytest tests/ -x -q           # run tests (580 expected)
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
6. **feat: similarity threshold** — `max_distance` parameter in search (renamed from `min_similarity`), default 1.5 L2 distance in MCP
7. **feat: hooks_cli** — stop hook saves directly via Python API with systemMessage notification, precompact blocks for AI-driven save, auto-ingest transcripts

## Upstream PRs

- milla-jovovich/mempalace#483 — mtime dedup fix
- milla-jovovich/mempalace#484 — search limit + pagination + cache fix

## Integration

- **Claude Code plugin**: installed at user scope via marketplace
- **MCP server**: global user scope — available in all projects
- **Stop hook**: fires every 15 messages, saves directly via Python API + systemMessage notification + auto-ingests transcript
- **PreCompact hook**: emergency save before context compaction

## Testing

Always run `python -m pytest tests/ -x -q` after changes. 576 tests expected to pass. Benchmark and stress tests are excluded by default (use `-m benchmark` or `-m stress` to include).
