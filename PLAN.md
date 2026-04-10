# MemPalace Upgrade Plan

## Rules

- Every phase MUST update `UPGRADE.md` with user-facing changes and a compact how-to.
- Every phase MUST update this status table and mark its section done.
- Commit message must list files changed, test count, and what's new.

## Status

| Phase | Description | Status |
|-------|-------------|--------|
| **Phase 1** | Database abstraction + LanceDB backend | ✅ Done |
| **Phase 2** | Pluggable vectorizers + `mempalace reindex` | ✅ Done |
| **Phase 3** | Sync metadata in all writes (`node_id`, `seq`, `updated_at`) | ✅ Done |
| **Phase 4** | Sync engine + server + `mempalace serve/sync` CLI | ✅ Done |
| **Phase 5** | Unify knowledge graph into LanceDB tables | ✅ Done |
| **Phase 6** | Benchmarks — LongMemEval comparison across backends | ✅ Done |

---

## Phase 1 — Database Abstraction + LanceDB ✅

**Completed.** Replaced ChromaDB as default with LanceDB. Created `db.py` abstraction
layer (`LanceCollection` / `ChromaCollection`) with identical API. All 534 tests pass.
Added `mempalace migrate` CLI command for ChromaDB → LanceDB migration.

Files: `mempalace/db.py`, `mempalace/embeddings.py`, updated all consumers.

---

## Phase 2 — Pluggable Vectorizers ✅

**Completed.** Added `OllamaEmbedder` for GPU server usage, model aliases
(`bge-small`, `nomic`, etc.), `mempalace reindex` to re-embed with a different
model, `mempalace embedders` to list options, and `embedding_model` tracking
in every record's metadata. 552 tests pass.

### Goal

Make the embedding model explicit and swappable. The `SentenceTransformerEmbedder`
in `embeddings.py` already accepts any model name — Phase 2 adds dedicated backends
for models that need different loading paths (Ollama, ONNX) and a `mempalace reindex`
command to re-embed all drawers when the user changes model.

### Embedder backends to implement

| Class | Model(s) | Dim | Notes |
|-------|----------|-----|-------|
| `SentenceTransformerEmbedder` | `all-MiniLM-L6-v2` (384d), `BAAI/bge-small-en-v1.5` (384d), `BAAI/bge-base-en-v1.5` (768d), `intfloat/e5-base-v2` (768d), `nomic-ai/nomic-embed-text-v1.5` (768d) | varies | Already works — any HuggingFace model via sentence-transformers |
| `OllamaEmbedder` | `nomic-embed-text`, `mxbai-embed-large`, `snowflake-arctic-embed` | varies | HTTP calls to local/remote Ollama server — key for GPU server |

### Config

```json
{
  "embedder": "bge-small",
  "embedder_options": { "device": "cpu" }
}
```

```json
{
  "embedder": "ollama",
  "embedder_options": {
    "model": "nomic-embed-text",
    "base_url": "http://homeserver:11434"
  }
}
```

### `mempalace reindex`

When the user changes vectorizer, existing embeddings are invalid.

1. Read all `(id, document, metadata_json)` from the current table.
2. Drop the vector index.
3. Re-embed all documents in batches with the new embedder.
4. Write back.
5. Store `embedding_model` in palace metadata so mismatches are detected.

### Embedding model tracking

Every record's `metadata_json` gains an `embedding_model` field. On `query()`,
if the stored model differs from the active embedder, log a warning and suggest
`mempalace reindex`.

---

## Phase 3 — Sync Metadata in All Writes ✅

**Completed.** Every LanceCollection write now injects `node_id`, `seq`, and
`updated_at` into stored metadata.  `sync_meta.py` manages a persistent
12-char node ID and an atomic file-locked sequence counter.  568 tests pass.

### Goal

Prepare every record for future multi-node sync by adding three fields to every
write operation:

```python
{
    "node_id": "laptop-abc123",          # unique per machine, generated on first run
    "seq": 4582,                         # monotonic counter per node
    "updated_at": "2026-04-10T14:30:00Z" # wall clock for last-writer-wins
}
```

### Implementation

- **`~/.mempalace/node_id`** — generated once with `uuid4().hex[:12]`, persisted.
- **Sequence counter** — stored in `~/.mempalace/seq` (atomic int file).  Incremented
  on every `upsert`/`add`/`delete`.
- **`updated_at`** — ISO 8601 UTC timestamp, set at write time.
- **Tombstones** — `delete()` doesn't remove rows, it sets `tombstone=true` +
  `updated_at`.  A periodic `compact()` actually removes old tombstones after sync
  confirms both nodes have seen them.

### Files to change

- `mempalace/sync_meta.py` — new: `NodeIdentity` class, seq counter, metadata injector
- `mempalace/db.py` — `LanceCollection.upsert/add/delete` inject sync metadata
- `mempalace/config.py` — `node_id` property
- LanceDB schema gains: `node_id: string`, `seq: int64`, `updated_at: string`,
  `tombstone: bool`

---

## Phase 4 — Sync Engine + Server ✅

**Completed.** Full bidirectional sync with version vectors, last-writer-wins
conflict resolution, FastAPI server, urllib-based client, and CLI commands
(`mempalace serve`, `mempalace sync --server URL [--auto]`).  588 tests pass.

### Architecture

```
┌─────────────────┐         VPN          ┌─────────────────┐
│   HOME SERVER    │◄───────────────────► │     LAPTOP      │
│                  │                      │                  │
│  LanceDB (full) │   sync protocol      │  LanceDB (full) │
│  Ollama (GPU)   │                      │  local embedder  │
│  Sync Server    │                      │  Sync Client     │
│  (FastAPI)      │                      │                  │
└─────────────────┘                      └─────────────────┘
```

### Sync protocol

```
POST /sync/push    — laptop sends new/modified records since last sync
POST /sync/pull    — laptop requests records since its last known server seq
GET  /sync/status  — exchange version vectors, record counts
GET  /health       — server health check
```

### Version vectors

Each node maintains a version vector — a dict mapping `node_id → last_seen_seq`:

```json
{
  "server-a1b2c3": 12450,
  "laptop-d4e5f6": 4582
}
```

On sync:
1. Laptop → `GET /sync/status` → gets server's version vector.
2. Laptop → `POST /sync/push` → sends all records where `laptop.seq > server_vv["laptop"]`.
3. Server applies records, updates its version vector.
4. Laptop → `POST /sync/pull` → requests all records where `server.seq > laptop_vv["server"]`.
5. Laptop applies records, updates its version vector.
6. Both nodes now have identical data.

### Conflict resolution

| Operation | Strategy |
|-----------|----------|
| New drawer (no conflict) | Append on both sides |
| Same drawer edited on both | Last-writer-wins by `updated_at`, `node_id` tiebreak |
| Deleted on one, edited on other | Delete wins (tombstone) |
| KG triple added on both | Union — both sides get it |
| KG triple invalidated on one | Invalidation wins |

### Offline operation

The laptop runs fully self-sufficient:
- Local LanceDB with complete data copy
- Local embedder (e.g. `bge-small` on CPU) for mining + search
- All MCP tools work identically offline
- Writes go to local DB with laptop's `node_id`

### Embedding strategy

Both nodes must use the same embedding model so vectors are compatible.
Two options:

- **Option A (recommended):** Same model everywhere.  Laptop uses CPU
  `bge-small`, server also uses `bge-small`.  Vectors compatible.
- **Option B:** Each node embeds locally.  Sync transfers documents +
  metadata but NOT vectors.  Each node re-embeds on receipt.  More flexible
  but doubles compute.

### CLI

```bash
# Server
mempalace serve --host 0.0.0.0 --port 7433

# Laptop
mempalace sync --server https://homeserver:7433
mempalace sync --server https://homeserver:7433 --auto   # every 5 min when reachable
```

### Files

- `mempalace/sync.py` — `SyncEngine`: `get_changes_since()`, `apply_changes()`, `get_version_vector()`
- `mempalace/sync_server.py` — FastAPI app with `/sync/push`, `/sync/pull`, `/sync/status`
- `mempalace/cli.py` — `mempalace serve`, `mempalace sync` commands

### Dependencies

- `fastapi` + `uvicorn` as optional `[server]` extra
- `httpx` for the sync client

---

## Phase 5 — Unify Knowledge Graph into LanceDB ✅

**Completed.** `KnowledgeGraph` now uses LanceDB tables (`kg_entities`,
`kg_triples`) inside the palace directory by default.  SQLite backend
preserved for existing `*.sqlite3` paths.  MCP server updated.  588 tests pass.

### Goal

Move the knowledge graph from a separate SQLite file into LanceDB tables.
One data directory, one format, one sync unit.

### LanceDB tables

```
Table: kg_entities
  id: string
  name: string
  type: string
  properties_json: string
  created_at: string
  node_id: string
  seq: int64
  updated_at: string

Table: kg_triples
  id: string
  subject: string
  predicate: string
  object: string
  valid_from: string
  valid_to: string
  confidence: float
  source_closet: string
  source_file: string
  extracted_at: string
  node_id: string
  seq: int64
  updated_at: string
  tombstone: bool
```

### Migration

`mempalace migrate-kg` reads all entities + triples from SQLite, writes to LanceDB.
KG triples don't need embeddings (they're queried by subject/predicate, not by
vector similarity), so the tables have no vector column.

### Files

- `mempalace/knowledge_graph.py` — rewrite to use LanceDB tables via `db.py`
- `mempalace/cli.py` — `mempalace migrate-kg` command

---

## Phase 6 — Benchmarks ✅

**Completed.** Full 500-question LongMemEval run comparing ChromaDB baseline,
LanceDB+MiniLM, and LanceDB+BGE-small.  LanceDB matches ChromaDB R@5 (0.966)
while being 1.8× faster (638ms vs 1165ms/query).  See `benchmarks/BENCHMARKS_V4.md`.

### Goal

Re-run LongMemEval and other benchmarks with the new infrastructure.  Compare
vectorizer quality across models.

### Benchmark matrix

| Embedder | Dim | LongMemEval R@5 | Ingest speed | Query latency |
|----------|-----|-----------------|--------------|---------------|
| `all-MiniLM-L6-v2` | 384 | (baseline — was 96.6%) | | |
| `bge-small-en-v1.5` | 384 | | | |
| `bge-base-en-v1.5` | 768 | | | |
| `nomic-embed-text-v1.5` | 768 | | | |
| Ollama `nomic-embed-text` | 768 | | | |

### Files

- Update `benchmarks/` runners to use the new `db.py` abstraction
- Update `tests/benchmarks/` stress tests for LanceDB
- Add `benchmarks/embedder_comparison.py`
