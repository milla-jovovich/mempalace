# MemPalace — Agent Reference

**What**: Local-only AI memory system. Mines projects and conversations into a ChromaDB vector palace, then searches by meaning. No API key. No cloud.

**Stack**: Python 3.9+, ChromaDB, PyYAML, SQLite (knowledge graph). CLI + MCP server.

## Architecture

```
CLI (cli.py) ──→ miner.py ──────→ palace_db.py ──→ ChromaDB
               ──→ convo_miner.py ─┘                  ↑
               ──→ searcher.py ────────────────────────┘
               ──→ layers.py (L0-L3 memory stack) ─────┘
MCP (mcp_server.py) ──→ same pipeline
```

## Module Map

| Module | Purpose | Key functions |
|---|---|---|
| `cli.py` | CLI entry (`mempalace mine/search/init/compress/wake-up/split/status`) | `main()`, `cmd_*()` |
| `config.py` | Config: env vars > `~/.mempalace/config.json` > defaults | `MempalaceConfig` |
| `constants.py` | Shared constants (`SKIP_DIRS`, `READABLE_EXTENSIONS`, chunk sizes) | — |
| `palace_db.py` | **Singleton ChromaDB client**, collection cache, query helpers | `get_collection()`, `query_palace()`, `build_where_filter()` |
| `miner.py` | Mine project files → rooms → chunks → drawers | `mine()`, `detect_room()`, `chunk_text()` |
| `convo_miner.py` | Mine conversations (Claude/ChatGPT/Slack exports) | `mine_convos()`, `chunk_exchanges()` |
| `normalize.py` | Convert any chat export to `> user / assistant` transcript format | `normalize()` (handles 6 formats) |
| `searcher.py` | Semantic search against palace | `search()`, `search_memories()` |
| `layers.py` | 4-layer memory stack: L0 identity, L1 story, L2 on-demand, L3 search | `MemoryStack`, `wake_up()` |
| `dialect.py` | AAAK symbolic compression (~30x token reduction) | `Dialect.compress()` |
| `general_extractor.py` | Extract 5 memory types: decisions, preferences, milestones, problems, emotional | `extract_memories()` |
| `knowledge_graph.py` | Temporal entity-relationship graph (SQLite) | `KnowledgeGraph`, `add_triple()`, `query_entity()` |
| `entity_registry.py` | Entity lookup with disambiguation (person vs common word) | `EntityRegistry.lookup()` |
| `palace_graph.py` | Graph traversal across wings via shared rooms | `build_graph()`, `traverse()`, `find_tunnels()` |
| `room_detector_local.py` | Auto-detect rooms from folder structure | `detect_rooms_from_folders()` |
| `split_mega_files.py` | Split concatenated transcript files into per-session files | `split_file()` |
| `mcp_server.py` | 14 MCP tools for AI assistant integration | — |
| `onboarding.py` | Interactive first-run setup | — |

## Key Concepts

- **Palace** = ChromaDB persistent store at `~/.mempalace/palace/`
- **Wing** = a project or domain (e.g. `myapp`, `personal`)
- **Room** = a topic within a wing (e.g. `backend`, `architecture`, `bugs`)
- **Drawer** = one chunk of text stored with metadata (`wing`, `room`, `source_file`)
- **Collection** = `mempalace_drawers` (default ChromaDB collection name)

## Data Flow

1. `mempalace init <dir>` → detects rooms from folders → writes `mempalace.yaml`
2. `mempalace mine <dir>` → reads files → `detect_room()` → `chunk_text()` → stores in ChromaDB
3. `mempalace mine <dir> --mode convos` → `normalize()` → `chunk_exchanges()` → stores
4. `mempalace search "query"` → `query_palace()` → ChromaDB semantic search → results

## Rules

- **All ChromaDB access goes through `palace_db.py`** — never import `chromadb` directly elsewhere.
- **Constants live in `constants.py`** — `SKIP_DIRS`, extensions, chunk sizes.
- **`build_where_filter()`** is the single place for ChromaDB where-clause logic.
- No API keys. No network calls (except optional Wikipedia lookup in `entity_registry.py`).
- Metadata always includes `wing`, `room`, `source_file` on every drawer.

## Testing

```bash
pytest                     # 275 tests + coverage report
pytest -n auto             # parallel execution
pytest -m "not integration"  # fast unit tests only (no ChromaDB)
```

- Tests in `tests/`, fixtures in `tests/conftest.py`
- All tests use `tmp_path` — no home directory pollution
- `conftest.py` provides: `palace_path`, `palace_with_data` (5 pre-loaded drawers), `sample_project`, `sample_convos`, `config_dir`, `identity_file`
- Integration tests (marked `@pytest.mark.integration`) need ChromaDB

## File Conventions

- `pyproject.toml` — single source of truth for deps, build, pytest config
- `mempalace.yaml` — per-project config (wing name + rooms), lives in project root
- `~/.mempalace/config.json` — global config (palace path, collection name)
- `~/.mempalace/identity.txt` — L0 identity text (plain text, user-written)
- `~/.mempalace/entity_registry.json` — known people/projects
- `~/.mempalace/knowledge_graph.sqlite3` — temporal KG
