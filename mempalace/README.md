# mempalace/ — Core Package

The Python package that powers MemPalace. All modules, all logic.

## Modules

| Module | What it does |
|--------|-------------|
| `cli.py` | CLI entry point — routes to mine, search, init, compress, wake-up |
| `config.py` | Configuration loading — `~/.mempalace/config.json`, env vars, defaults |
| `normalize.py` | Converts 5 chat formats (Claude Code JSONL, Claude.ai JSON, ChatGPT JSON, Slack JSON, plain text) to standard transcript format |
| `miner.py` | Project file ingest — scans directories, chunks by paragraph, stores to ChromaDB |
| `convo_miner.py` | Conversation ingest — chunks by exchange pair (Q+A), detects rooms from content |
| `searcher.py` | Semantic search via ChromaDB vectors — filters by wing/room, returns verbatim + scores |
| `layers.py` | 4-layer memory stack: L0 (identity), L1 (critical facts), L2 (room recall), L3 (deep search) |
| `dialect.py` | AAAK compression — entity codes, emotion markers, 30x lossless ratio |
| `knowledge_graph.py` | Temporal entity-relationship graph — SQLite, time-filtered queries, fact invalidation |
| `palace_graph.py` | Room-based navigation graph — BFS traversal, tunnel detection across wings |
| `mcp_server.py` | MCP server — 19 tools, AAAK auto-teach, Palace Protocol, agent diary |
| `onboarding.py` | Guided first-run setup — asks about people/projects, generates AAAK bootstrap + wing config |
| `entity_registry.py` | Entity code registry — maps names to AAAK codes, handles ambiguous names |
| `entity_detector.py` | Auto-detect people and projects from file content |
| `general_extractor.py` | Classifies text into 5 memory types (decision, preference, milestone, problem, emotional) |
| `room_detector_local.py` | Maps folders to room names using 70+ patterns — no API |
| `spellcheck.py` | Name-aware spellcheck — won't "correct" proper nouns in your entity registry |
| `split_mega_files.py` | Splits concatenated transcript files into per-session files |

## Architecture

```
User → CLI → miner/convo_miner → ChromaDB (palace)
                                     ↕
                              knowledge_graph (SQLite)
                                     ↕
User → MCP Server → searcher → results
                  → kg_query → entity facts
                  → diary    → agent journal
```

The palace (ChromaDB) stores verbatim content. The knowledge graph (SQLite) stores structured relationships. The MCP server exposes both to any AI tool.

## Safe Hook Wrappers

If you wire `mempalace mine` into editor, agent, or CI hooks, protect the wrapper against overlapping runs. Frequent save or stop events can otherwise launch multiple concurrent miners for the same path. The data will usually remain correct, but CPU and wall-clock cost can spike.

Recommended protections:

1. Acquire a global or per-target lock before the hook backgrounds any worker process.
2. Add stale-lock expiry so crashed runs do not block future mining forever.
3. Add a kill switch such as `MEMPALACE_AUTOSAVE=0` or `~/.mempalace/disable_autosave`.
4. If you mine many different projects, prefer per-target locks keyed by the path.

Minimal pattern:

```bash
#!/usr/bin/env bash
set -euo pipefail

[ "${MEMPALACE_AUTOSAVE:-1}" = "0" ] && exit 0
[ -f "${HOME}/.mempalace/disable_autosave" ] && exit 0

TARGET="$1"
LOCK_AGE=300
LOCK_KEY="$(printf '%s' "$TARGET" | sha256sum | cut -c1-8)"
LOCKDIR="${HOME}/.mempalace/mine-${LOCK_KEY}.lock"

if [ -d "$LOCKDIR" ]; then
  AGE="$(($(date +%s) - $(stat -c %Y "$LOCKDIR" 2>/dev/null || echo 0)))"
  if [ "$AGE" -gt "$LOCK_AGE" ]; then
    rm -rf "$LOCKDIR"
  fi
fi

if ! mkdir "$LOCKDIR" 2>/dev/null; then
  exit 0
fi

trap 'rm -rf "$LOCKDIR"' EXIT
mempalace mine "$TARGET"
```

Important: take the lock in the foreground hook process. If the script forks into the background before locking, multiple overlapping hook invocations can still start duplicate miners.
