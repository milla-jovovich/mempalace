# Architecture

## Overview

MemPalace has two storage backends:

- **ChromaDB** (vector store) — stores verbatim text chunks (drawers) with metadata, supports semantic search via embeddings.
- **SQLite** (knowledge graph) — stores entity-relationship triples with temporal validity windows.

Both are local files. No network access, no external services.

```
User → CLI / MCP Server → ChromaDB (palace)
                              ↕
                        SQLite (knowledge graph)
```

## Palace model

The palace organizes memories using a spatial metaphor. Each level of the hierarchy corresponds to ChromaDB metadata fields, which enables filtered search.

### Wings

A wing represents a person, project, or domain. Every memory belongs to exactly one wing.

```
myapp             — a project
kai               — a person
hardware          — a domain
```

Wing names are stored as the `wing` metadata field on each ChromaDB document.

### Rooms

A room is a specific topic within a wing. The same room name can appear in multiple wings — when it does, it creates a tunnel (see below).

```
myapp / auth-migration
myapp / pricing-model
myapp / ci-pipeline
```

Room names are stored as the `room` metadata field. Rooms are auto-detected from folder structure during `mempalace init`, or assigned during conversation mining based on content analysis.

### Halls

Halls are memory type corridors — the same set exists in every wing:

| Hall | What it stores |
|------|---------------|
| `hall_facts` | Decisions made, choices locked in |
| `hall_events` | Sessions, milestones, debugging sessions |
| `hall_discoveries` | Breakthroughs, new insights |
| `hall_preferences` | Habits, likes, opinions |
| `hall_advice` | Recommendations and solutions |

Halls are assigned during general extraction mode (`--extract general`). In default mining modes, the hall metadata may not be set.

### Tunnels

When the same room name appears in multiple wings, a tunnel connects them. This enables cross-domain queries.

```
kai       / auth-migration  →  "Kai debugged the OAuth token refresh"
myapp     / auth-migration  →  "team decided to migrate auth to Clerk"
priya     / auth-migration  →  "Priya approved Clerk over Auth0"
```

Same room, three wings. A tunnel connects them. Use `mempalace_find_tunnels` or `mempalace_traverse` to navigate these connections.

Tunnels are not stored explicitly — they're computed from shared room names across wings using the palace graph module (`palace_graph.py`).

### Drawers

Drawers are the verbatim text chunks stored in ChromaDB. Each drawer is a ChromaDB document with metadata fields: `wing`, `room`, `hall`, `source_file`, `chunk_index`, `filed_at`, `added_by`.

Content is never summarized. The exact words from the source file or conversation are preserved.

## Memory layers

MemPalace loads context in four layers, designed to minimize token usage while keeping important information accessible.

### L0 — Identity (~50 tokens)

A plain-text file at `~/.mempalace/identity.txt` describing who the AI is. Loaded every session.

```
I am Atlas, a personal AI assistant for Alice.
Traits: warm, direct, remembers everything.
```

### L1 — Essential story (~500–800 tokens)

Auto-generated from the highest-importance drawers in the palace. Groups content by room and picks the top 15 moments. Generated on each `wake-up` call.

### L2 — On-demand (~200–500 tokens per retrieval)

Wing/room-filtered retrieval from ChromaDB. Loaded when a specific topic comes up in conversation. Not semantic search — direct metadata-filtered reads.

### L3 — Deep search (unlimited)

Full semantic search against the entire palace. Used when the user explicitly asks a question. This is the `mempalace_search` tool.

### Wake-up flow

When an AI session starts, it calls `mempalace_status` (via MCP) or `mempalace wake-up` (via CLI), which loads L0 + L1. L2 and L3 fire on demand during the conversation.

```
Session start → L0 + L1 loaded (~600-900 tokens)
Topic mentioned → L2 retrieval
Explicit question → L3 semantic search
```

## Data flow

### Mining

```
Source files
    ↓
  normalize.py  (convert chat formats to transcript)
    ↓
  miner.py / convo_miner.py  (chunk into paragraphs or exchange pairs)
    ↓
  palace.py  (store in ChromaDB with wing/room/hall metadata)
```

### Search

```
Query string
    ↓
  query_sanitizer.py  (strip prompt contamination)
    ↓
  searcher.py  (ChromaDB vector query with optional wing/room filter)
    ↓
  Results: [{text, wing, room, source_file, similarity}]
```

### Knowledge graph

```
Facts (subject → predicate → object)
    ↓
  knowledge_graph.py  (SQLite with temporal validity)
    ↓
  Queries: entity lookup, time filtering, timeline, relationship traversal
```

## Module map

| Module | Responsibility |
|--------|---------------|
| `cli.py` | CLI entry point, command routing |
| `config.py` | Configuration loading, input validation |
| `normalize.py` | Chat format detection and normalization (6 formats) |
| `miner.py` | Project file ingest (code, docs, notes) |
| `convo_miner.py` | Conversation ingest (exchange-pair chunking) |
| `searcher.py` | Semantic search via ChromaDB |
| `layers.py` | 4-layer memory stack (L0–L3) |
| `palace.py` | Shared ChromaDB access (get_collection, dedup check) |
| `palace_graph.py` | Room graph traversal, tunnel detection |
| `knowledge_graph.py` | Temporal entity-relationship graph (SQLite) |
| `dialect.py` | AAAK compression dialect |
| `mcp_server.py` | MCP server (19 tools, JSON-RPC over stdin/stdout) |
| `onboarding.py` | Interactive first-run setup |
| `query_sanitizer.py` | Strip system prompt contamination from search queries |
| `entity_detector.py` | Auto-detect people and projects from content |
| `entity_registry.py` | Entity code registry for AAAK |
| `general_extractor.py` | Classify text into 5 memory types |
| `room_detector_local.py` | Map folders to room names (70+ patterns) |
| `split_mega_files.py` | Split concatenated transcripts into per-session files |
| `hooks_cli.py` | Hook system for auto-save |
| `normalize.py` | Transcript format detection and normalization |
| `spellcheck.py` | Name-aware spellcheck |
| `dedup.py` | Deduplication utilities |
| `repair.py` | Palace vector index rebuild |
| `migrate.py` | ChromaDB version migration |

## Storage locations

| Path | Contents |
|------|----------|
| `~/.mempalace/config.json` | Global configuration |
| `~/.mempalace/palace/` | ChromaDB vector store (default) |
| `~/.mempalace/identity.txt` | L0 identity text |
| `<project>/mempalace.yaml` | Project-specific wing and room definitions |
| `~/.mempalace/people_map.json` | Name variant mappings |
| `~/.mempalace/knowledge_graph.sqlite3` | Knowledge graph database |
| `~/.mempalace/wal/write_log.jsonl` | Write-ahead log (audit trail) |
| `~/.mempalace/hook_state/` | Hook state and logs |

All paths can be overridden — see [configuration.md](configuration.md).
