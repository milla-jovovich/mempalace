# Copilot Instructions for MemPalace

## Build, Test, and Lint

```bash
pip install -e ".[dev]"          # install with dev deps (pytest, ruff)

pytest tests/ -v                 # full test suite
pytest tests/test_miner.py -v    # single test file
pytest tests/test_miner.py::test_project_mining -v  # single test

ruff check .                     # lint
ruff format --check .            # format check
ruff check --fix . && ruff format .  # auto-fix
```

CI runs on Python 3.9, 3.11, and 3.13. Target compatibility is Python 3.9+.

## Architecture

MemPalace is a local AI memory system backed by ChromaDB (vector search) and SQLite (knowledge graph). It ingests files and conversations into a hierarchical structure modeled on the memory palace mnemonic:

- **Wings** → top-level grouping (a person, project, or topic)
- **Halls** → category within a wing (emotions, technical, etc.)
- **Rooms** → specific aspect (backend, planning, etc.)
- **Drawers** → individual chunks of verbatim text stored in ChromaDB

Two ingest paths feed the same palace:
- `miner.py` — project files (code, docs). Chunks by paragraph, routes to rooms via `mempalace.yaml`.
- `convo_miner.py` — conversation exports (Claude, ChatGPT, Slack). Chunks by exchange pair (Q+A). Normalizes formats via `normalize.py`.

Retrieval uses a 4-layer memory stack (`layers.py`):
- **L0** — Identity (~100 tokens, from `~/.mempalace/identity.txt`)
- **L1** — Essential Story (~500-800 tokens, auto-generated from top drawers)
- **L2** — On-demand wing/room filtered retrieval
- **L3** — Full semantic search via ChromaDB

The `knowledge_graph.py` provides a separate temporal entity-relationship graph in SQLite with time-filtered queries and fact invalidation.

The `mcp_server.py` exposes both ChromaDB and the knowledge graph to AI tools via the Model Context Protocol.

## Key Conventions

### Verbatim storage
Content is stored as exact words — never summarized or paraphrased. This is the core design principle and the reason for the 96.6% LongMemEval score. Don't add summarization to storage paths.

### Local-only, zero API by default
All core features must work without network access or API keys. ChromaDB's built-in embeddings are used. Don't introduce cloud service dependencies.

### Minimal dependencies
Production deps are ChromaDB and PyYAML only. Don't add new dependencies without discussion. Dev deps are pytest and ruff.

### Code style
- **Ruff** for linting and formatting, 100-char line length (configured in `pyproject.toml`)
- `snake_case` for functions/variables, `PascalCase` for classes
- Docstrings on all modules and public functions
- Type hints where they improve readability
- `"double quotes"` for strings (ruff format enforces this)

### Commit messages
Follow [conventional commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `bench:`, etc.

### Test isolation
Tests redirect `HOME`/`USERPROFILE` to a temp directory at import time (in `conftest.py`) so tests never touch real user data. Use the provided fixtures (`tmp_dir`, `palace_path`, `collection`, `kg`) for isolated ChromaDB and SQLite instances. Tests must run without API keys or network access.

### AAAK dialect
`dialect.py` implements a lossy abbreviation format (entity codes, emotion markers, structured summaries). It is an experimental compression layer — not the storage default. The 96.6% benchmark is from raw mode, not AAAK.

### ChromaDB collection name
The primary collection is always `mempalace_drawers`. Compressed content goes to `mempalace_compressed`. Don't rename these.

### Drawer metadata
Every drawer stored in ChromaDB carries metadata: `wing`, `room`, `source_file`, `chunk_index`, `added_by`, `filed_at`. Preserve this schema when adding new ingest paths.
