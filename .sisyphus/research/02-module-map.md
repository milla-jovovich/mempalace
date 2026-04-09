# Python Module Map — MemPalace 3.1.0

Source: `explore` task `bg_b0124925` (3m13s). Full map of all 24 Python files in `mempalace/`.

## Sizes (LoC)

| Module | LoC | Notes |
|---|---|---|
| mcp_server.py | 946 | 19 MCP tools + stdio loop |
| dialect.py | 1075 | AAAK compression (self-contained) |
| entity_detector.py | 853 | Regex-heavy entity detection |
| miner.py | 641 | Project ingest, gitignore parser |
| entity_registry.py | 639 | Entity store + Wikipedia lookup |
| cli.py | 574 | CLI dispatch to 11 modules |
| general_extractor.py | 521 | 80+ regex markers for memory classification |
| layers.py | 515 | L0/L1/L2/L3 memory stack |
| onboarding.py | 489 | Interactive setup wizard |
| knowledge_graph.py | 393 | SQLite temporal triples |
| convo_miner.py | 380 | Conversation ingest |
| normalize.py | 334 | 6 chat formats |
| split_mega_files.py | 317 | Mega transcript splitter |
| room_detector_local.py | 310 | Folder→room detection |
| spellcheck.py | 269 | Name-aware spell correction |
| palace_graph.py | 227 | BFS over ChromaDB metadata |
| hooks_cli.py | 226 | Session hook JSON handler |
| config.py | 209 | Config loader + sanitizers |
| searcher.py | 152 | ChromaDB semantic search |
| palace.py | 71 | Shared ChromaDB helper |
| instructions_cli.py | 28 | .md printer |
| __init__.py | 21 | Package init |
| __main__.py | 5 | `python -m` entry |
| version.py | 3 | `__version__` |
| **TOTAL** | **~9083** | |

## Dependency graph (module → internal imports)

```
version.py          → []
__init__.py         → [cli, version]
__main__.py         → [cli]
config.py           → []
spellcheck.py       → [entity_registry (lazy)]
instructions_cli.py → []
general_extractor.py→ []
palace.py           → []
knowledge_graph.py  → []
normalize.py        → [spellcheck (lazy)]
dialect.py          → []
split_mega_files.py → []
entity_detector.py  → []
entity_registry.py  → [entity_detector (lazy)]
hooks_cli.py        → []
room_detector_local.py → [miner (lazy)]
palace_graph.py     → [config]
searcher.py         → []
convo_miner.py      → [normalize, palace, general_extractor (lazy), config (lazy)]
layers.py           → [config]
miner.py            → [palace]
onboarding.py       → [entity_registry, entity_detector]
mcp_server.py       → [config, version, searcher, palace_graph, knowledge_graph]
cli.py              → [config, entity_detector, room_detector_local, convo_miner,
                        miner, searcher, layers, split_mega_files, hooks_cli,
                        instructions_cli, dialect]
```

## Topological order (port leaves first)

**Tier 0 — Pure leaves (parallel porting safe)**
- version.py, config.py, palace.py, knowledge_graph.py, general_extractor.py, dialect.py, entity_detector.py, instructions_cli.py, split_mega_files.py

**Tier 1 — Single dep**
- spellcheck.py → entity_registry
- normalize.py → spellcheck
- hooks_cli.py (no internal deps, touches subprocess+stdio)
- entity_registry.py → entity_detector

**Tier 2 — Multi dep**
- searcher.py (touches ChromaDB)
- palace_graph.py → config + ChromaDB
- layers.py → config + ChromaDB
- miner.py → palace
- convo_miner.py → normalize + palace + general_extractor + config
- room_detector_local.py → miner
- onboarding.py → entity_registry + entity_detector

**Tier 3 — Glue**
- mcp_server.py (19 tools) → config, version, searcher, palace_graph, knowledge_graph
- cli.py → 11 modules

## ChromaDB API surface (full audit)

Operations used in the Python code:
- `PersistentClient(path=...)`
- `get_collection(name)` / `create_collection(name)` / `get_or_create_collection(name)` / `delete_collection(name)`
- `collection.add(documents=[], ids=[], metadatas=[])`
- `collection.upsert(documents=[], ids=[], metadatas=[])`
- `collection.query(query_texts=[], n_results=N, where={}, include=[…])`
- `collection.get(where={}, limit=N, offset=N, include=[…])` and `get(ids=[])`
- `collection.count()`
- `collection.delete(ids=[])`

Where filters used:
- `{"wing": x}`, `{"room": x}`, `{"source_file": x}`
- `{"$and": [{"wing": x}, {"room": y}]}`
- No `$or`, `$in`, `$gt`, `$lt`, `$ne`, `$contains`

Metadata fields stored:
- `wing`, `room`, `source_file`, `chunk_index`, `added_by`, `filed_at`
- `source_mtime` (float), `ingest_mode`, `extract_mode`, `hall`, `topic`, `type`
- `agent`, `date`, `compression_ratio`, `original_tokens`

## SQLite schema (knowledge_graph.py)

```sql
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT DEFAULT 'unknown',
    properties TEXT DEFAULT '{}',      -- JSON text
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS triples (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    confidence REAL DEFAULT 1.0,
    source_closet TEXT,
    source_file TEXT,
    extracted_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (subject) REFERENCES entities(id),
    FOREIGN KEY (object)  REFERENCES entities(id)
);

CREATE INDEX IF NOT EXISTS idx_triples_subject   ON triples(subject);
CREATE INDEX IF NOT EXISTS idx_triples_object    ON triples(object);
CREATE INDEX IF NOT EXISTS idx_triples_predicate ON triples(predicate);
CREATE INDEX IF NOT EXISTS idx_triples_valid     ON triples(valid_from, valid_to);
```

## Regex audit — NO LOOKAROUND

Full audit confirms zero `(?<=…)`, `(?<!…)`, `(?=…)`, `(?!…)` patterns in any file. Safe to use Rust `regex` crate directly. Heaviest users:
- `general_extractor.py`: ~80 marker patterns + 12 code patterns
- `entity_detector.py`: ~47 parameterized patterns (compiled at runtime per-entity)
- `entity_registry.py`: 24 context patterns
- `spellcheck.py`: 8 compiled regexes
- `dialect.py`: 6 patterns

## Side-effect summary

| Module | ChromaDB | SQLite | YAML | JSON | Net | Subprocess | FS W | FS R |
|---|---|---|---|---|---|---|---|---|
| config | | | | R/W | | | R/W | R |
| palace | R/W | | | | | | W | |
| knowledge_graph | | R/W | | R | | | W | |
| miner | R/W | | R | | | | | R |
| convo_miner | R/W | | | | | | | R |
| searcher | R | | | | | | | |
| palace_graph | R | | | | | | | |
| layers | R | | | | | | | R |
| mcp_server | R/W | | | R | | | R/W | |
| entity_registry | | | | R/W | **HTTP** | | R/W | |
| hooks_cli | | | | R | | **Popen** | R/W | |
| split_mega_files | | | | R | | | R/W | R |
| room_detector_local | | | W | | | | W | R |
| normalize | | | | R | | | | R |
| dialect | | | | R/W | | | R/W | R |
| cli | R/W | | | R | | | W | |
