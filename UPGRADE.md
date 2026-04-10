# MemPalace v4.0 — Upgrade Changelog

> Covers all changes on the `feat/multishare` branch: LanceDB migration,
> pluggable embedders, multi-device sync.  Each section includes a compact
> how-to so you can start using the feature immediately.

---

## Breaking Changes

| What | Before (v3.x) | After (v4.0) |
|------|---------------|--------------|
| Default database | ChromaDB (embedded SQLite + HNSW) | LanceDB (Lance columnar format) |
| Default dependency | `chromadb>=0.5` | `lancedb>=0.14`, `onnxruntime`, `tokenizers` |
| ChromaDB | Required | Optional — `pip install 'mempalace[chroma]'` |
| Embeddings | Hidden inside ChromaDB (ONNX all-MiniLM-L6-v2) | Explicit, configurable, tracked per record |

Existing ChromaDB palaces are detected automatically and still work.
Run `mempalace migrate` to convert to LanceDB when ready.

---

## 1. LanceDB Backend (Phase 1)

ChromaDB is replaced by LanceDB as the default storage engine.  A database
abstraction layer (`mempalace/db.py`) means all code goes through one
interface regardless of backend.

### Why

- No more ONNX segfaults on Apple Silicon
- Append-only versioned format (foundation for sync)
- ~40 fewer transitive dependencies
- Built-in SQL-like filtering without SQLite

### How-to

**New installs** — LanceDB is used automatically.  No action needed.

**Existing ChromaDB palaces:**

```bash
# 1. Verify current state
mempalace status

# 2. Migrate (transfers embeddings — no re-embedding needed)
mempalace migrate

# 3. Verify
mempalace status
mempalace search "test query"
```

The migrator backs up your ChromaDB data to `<palace>.chroma-backup/` before
converting.

**Force a specific backend** (rare):

```bash
export MEMPALACE_BACKEND=chroma   # or "lance"
```

Or in `~/.mempalace/config.json`:

```json
{"backend": "lance"}
```

---

## 2. Pluggable Embedders (Phase 2)

The embedding model is now explicit, configurable, and tracked.  Every record
stores which model embedded it so mismatches are detectable.

### Available models

| Alias | Full name | Dim | Notes |
|-------|-----------|-----|-------|
| `minilm` | `all-MiniLM-L6-v2` | 384 | Default. Fast, decent. |
| `bge-small` | `BAAI/bge-small-en-v1.5` | 384 | Best quality-at-size. |
| `bge-base` | `BAAI/bge-base-en-v1.5` | 768 | Higher quality, larger. |
| `e5-base` | `intfloat/e5-base-v2` | 768 | Good general purpose. |
| `nomic` | `nomic-ai/nomic-embed-text-v1.5` | 768 | Matryoshka dims. |
| `ollama` | Any Ollama model | varies | GPU server via HTTP. |

### How-to

```bash
# List models with active marker
mempalace embedders

# Switch model (updates config, re-embeds everything)
mempalace reindex --embedder bge-small

# Preview without changing
mempalace reindex --dry-run

# Use a GPU server running Ollama
mempalace reindex --embedder ollama \
    --ollama-model nomic-embed-text \
    --ollama-url http://homeserver:11434

# Set permanently in config
cat > ~/.mempalace/config.json << 'EOF'
{
  "embedder": "bge-small",
  "embedder_options": {"device": "cpu"}
}
EOF
```

**Ollama config** (for GPU server):

```json
{
  "embedder": "ollama",
  "embedder_options": {
    "model": "nomic-embed-text",
    "base_url": "http://homeserver:11434"
  }
}
```

---

## 3. Multi-Device Sync (Phases 3 + 4)

MemPalace now supports hub-and-spoke replication between machines.  A
powerful home server acts as the hub; laptops sync over VPN when connected
and work fully offline in between.

### Architecture

```
┌─────────────────┐         VPN          ┌─────────────────┐
│   HOME SERVER    │◄───────────────────►│     LAPTOP      │
│                  │                      │                  │
│  LanceDB (full) │   sync protocol      │  LanceDB (full) │
│  Ollama (GPU)   │  POST /sync/push     │  local embedder  │
│  Sync Server    │  POST /sync/pull     │  Sync Client     │
│  :7433          │  GET  /sync/status   │                  │
└─────────────────┘                      └─────────────────┘
```

### How it works

1. Each machine gets a unique **node ID** (auto-generated, persisted in
   `~/.mempalace/node_id`).
2. Every write increments a **monotonic sequence counter** and stamps the
   record with `node_id`, `seq`, and `updated_at`.
3. On sync, nodes exchange only the records the other hasn't seen, using
   **version vectors** (`node_id → highest_seq`).
4. **Conflicts** (same drawer edited on both machines) are resolved with
   last-writer-wins by timestamp, with node ID as tiebreaker.

### How-to: Server (home machine)

```bash
pip install 'mempalace[server]'   # adds fastapi + uvicorn

# Start the sync server
mempalace serve --host 0.0.0.0 --port 7433

# Or with a custom palace path
mempalace --palace /data/palace serve --port 7433
```

### How-to: Client (laptop)

```bash
# One-shot sync
mempalace sync --server http://homeserver:7433

# Auto-sync every 5 minutes (stop with Ctrl+C)
mempalace sync --server http://homeserver:7433 --auto

# Custom interval (seconds)
mempalace sync --server http://homeserver:7433 --auto --interval 60
```

### Offline operation

The laptop is fully self-sufficient between syncs:

- Local LanceDB with a copy of all synced drawer data
- Local embedder runs on CPU (e.g. `bge-small`)
- All MCP tools, mining, and search work against local drawers
- Writes accumulate locally with the laptop's node ID
- Sync replicates drawers only; knowledge graph tables are node-local

When the laptop reconnects, `mempalace sync` pushes local drawer changes and
pulls remote drawer changes.  After sync, both machines have identical
drawer data.

### Embedding consistency

Both nodes **must use the same embedding model** for vectors to be
compatible.  Configure both machines with the same `embedder` in
`config.json`.  If you change model, run `mempalace reindex` on both sides.

### Conflict resolution

| Scenario | Resolution |
|----------|------------|
| New drawer (exists only on one side) | Copied to both sides |
| Same ID edited on both sides | Newer `updated_at` wins |
| Same timestamp | Higher `node_id` wins (deterministic) |

---

## 4. Unified Knowledge Graph (Phase 5)

The knowledge graph (entities + triples) has moved from a separate SQLite
file into LanceDB tables inside the palace directory.  One data directory,
one format, one sync unit.

### What changed

- **Before:** `~/.mempalace/knowledge_graph.sqlite3` (separate file)
- **After:** `kg_entities` and `kg_triples` tables inside `<palace>/` (LanceDB)

Existing SQLite knowledge graphs still work — if you pass a `.sqlite3` path
the old backend is used.  The MCP server now defaults to the LanceDB backend.

### How-to

No action needed for new installs.  The knowledge graph is created inside
the palace directory automatically.

For existing installs, the MCP server will start using a fresh LanceDB KG
in the palace directory.  To preserve your old SQLite KG data, re-add the
triples via the MCP tools or seed from entity facts.

---

## 5. Benchmark Results (Phase 6)

Full 500-question LongMemEval benchmark run comparing the v3.x ChromaDB
baseline with the new v4.0 LanceDB backends.

### Results

| Backend + Embedder | R@5 | R@10 | NDCG@5 | ms/query |
|---|---|---|---|---|
| ChromaDB + MiniLM (v3.x) | 0.966 | 0.982 | 0.888 | 1165 |
| **LanceDB + MiniLM (v4.0)** | **0.966** | **0.982** | **0.888** | **638** |
| LanceDB + BGE-small | 0.962 | 0.978 | 0.895 | 2624 |

**Zero retrieval regression.** LanceDB produces identical recall to ChromaDB
while being **1.8× faster** (638ms vs 1165ms per query).

Full details: `benchmarks/BENCHMARKS_V4.md`

### How-to

```bash
# Quick test (20 questions, ~2 min)
python benchmarks/longmemeval_v4.py DATA --mode quick --limit 20

# Full comparison (500 questions, ~45 min)
python benchmarks/longmemeval_v4.py DATA --mode all

# Compare all embedders
python benchmarks/longmemeval_v4.py DATA --mode embedders
```

---

## New CLI Commands (summary)

| Command | Description |
|---------|-------------|
| `mempalace migrate` | Convert ChromaDB palace to LanceDB |
| `mempalace reindex [--embedder NAME]` | Re-embed all drawers with a different model |
| `mempalace embedders` | List available embedding models |
| `mempalace serve [--host H --port P]` | Start the sync server |
| `mempalace sync --server URL [--auto]` | Sync with a remote server |

---

## New Files

| File | Purpose |
|------|---------|
| `mempalace/db.py` | Database abstraction — `LanceCollection`, `ChromaCollection` |
| `mempalace/embeddings.py` | `SentenceTransformerEmbedder`, `OllamaEmbedder`, factory |
| `mempalace/sync_meta.py` | `NodeIdentity`, atomic sequence counter |
| `mempalace/sync.py` | `SyncEngine`, `VersionVector`, `ChangeSet` |
| `mempalace/sync_server.py` | FastAPI sync server |
| `mempalace/sync_client.py` | HTTP sync client |

---

## Configuration Reference

All settings in `~/.mempalace/config.json`:

```json
{
  "palace_path": "~/.mempalace/palace",
  "backend": "lance",
  "embedder": "bge-small",
  "embedder_options": {
    "device": "cpu"
  }
}
```

### Environment variables

| Variable | Purpose |
|----------|---------|
| `MEMPALACE_PALACE_PATH` | Override palace directory |
| `MEMPALACE_BACKEND` | Force `lance` or `chroma` |

### Generated files

| File | Purpose |
|------|---------|
| `~/.mempalace/node_id` | This machine's unique 12-char sync ID |
| `~/.mempalace/seq` | Monotonic write counter |
| `<palace>/version_vector.json` | Sync state (node→seq mapping) |
