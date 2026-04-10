# MemPalace v4.0 — Upgrade Changelog

> Covers all changes on the `feat/multishare` branch: LanceDB migration,
> pluggable embedders.  Each section includes a compact
> how-to so you can start using the feature immediately.

---

## Breaking Changes

| What | Before (v3.x) | After (v4.0) |
|------|---------------|--------------|
| Default database | ChromaDB (embedded SQLite + HNSW) | LanceDB (Lance columnar format) |
| Default dependency | `chromadb>=0.5` | `lancedb>=0.14`, `sentence-transformers>=2.2` |
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

## 4. Unified Knowledge Graph (Phase 5)

The knowledge graph (entities + triples) has moved from a separate SQLite
file into LanceDB tables inside the palace directory.  One data directory,
one format.

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

---

## New Files

| File | Purpose |
|------|---------|
| `mempalace/db.py` | Database abstraction — `LanceCollection`, `ChromaCollection` |
| `mempalace/embeddings.py` | `SentenceTransformerEmbedder`, `OllamaEmbedder`, factory |

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
| `~/.mempalace/seq` | Monotonic write counter |
