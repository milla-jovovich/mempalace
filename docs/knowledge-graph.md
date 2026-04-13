# Knowledge graph

MemPalace includes a temporal knowledge graph for tracking entity relationships that change over time. Stored in SQLite at `~/.mempalace/knowledge_graph.sqlite3`.

## Concepts

The knowledge graph stores **triples**: `subject → predicate → object`. Each triple has optional temporal validity (`valid_from`, `valid_to`), so you can query what was true at any point in time.

```
Kai → works_on → Orion        (valid_from: 2025-06-01, valid_to: NULL → current)
Maya → assigned_to → auth     (valid_from: 2026-01-15, valid_to: 2026-02-01 → ended)
```

Entities are auto-created when you add triples. Entity IDs are derived from the name (`lowercased`, spaces replaced with `_`).

## Python API

```python
from mempalace.knowledge_graph import KnowledgeGraph
```

### KnowledgeGraph(db_path=None)

Create or connect to a knowledge graph.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `db_path` | `str` | `~/.mempalace/knowledge_graph.sqlite3` | Path to SQLite database |

```python
kg = KnowledgeGraph()
kg = KnowledgeGraph(db_path="/tmp/test_kg.sqlite3")
```

### add_triple(subject, predicate, obj, ...)

Add a relationship. Entities are auto-created if they don't exist. If an identical active triple already exists (same subject, predicate, object, and `valid_to` is NULL), returns the existing triple's ID.

```python
triple_id = kg.add_triple(
    "Kai", "works_on", "Orion",
    valid_from="2025-06-01",
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `subject` | `str` | required | Entity doing/being something |
| `predicate` | `str` | required | Relationship type |
| `obj` | `str` | required | Connected entity |
| `valid_from` | `str` | `None` | When this became true (YYYY-MM-DD or partial) |
| `valid_to` | `str` | `None` | When this stopped being true |
| `confidence` | `float` | `1.0` | Confidence score |
| `source_closet` | `str` | `None` | Closet ID where this fact was found |
| `source_file` | `str` | `None` | Source file reference |

**Returns:** `str` — the triple ID.

### invalidate(subject, predicate, obj, ended=None)

Mark a triple as no longer true by setting its `valid_to` date. Only affects triples where `valid_to` is currently NULL.

```python
kg.invalidate("Kai", "works_on", "Orion", ended="2026-03-01")
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `subject` | `str` | required | Entity |
| `predicate` | `str` | required | Relationship |
| `obj` | `str` | required | Connected entity |
| `ended` | `str` | today's date | When it stopped being true |

### add_entity(name, entity_type="unknown", properties=None)

Explicitly create or update an entity node. Usually unnecessary — `add_triple` creates entities automatically.

```python
kg.add_entity("Kai", entity_type="person", properties={"role": "engineer"})
```

### query_entity(name, as_of=None, direction="outgoing")

Get all relationships for an entity.

```python
facts = kg.query_entity("Kai")
facts = kg.query_entity("Kai", as_of="2026-01-15")
facts = kg.query_entity("Kai", direction="both")
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | required | Entity name |
| `as_of` | `str` | `None` | Only return facts valid at this date |
| `direction` | `str` | `"outgoing"` | `outgoing` (entity→?), `incoming` (?→entity), or `both` |

**Returns:** `list[dict]` — each dict contains:

```python
{
    "direction": "outgoing",
    "subject": "Kai",
    "predicate": "works_on",
    "object": "Orion",
    "valid_from": "2025-06-01",
    "valid_to": None,
    "confidence": 1.0,
    "source_closet": None,
    "current": True,
}
```

### query_relationship(predicate, as_of=None)

Get all triples with a given relationship type.

```python
workers = kg.query_relationship("works_on")
workers_jan = kg.query_relationship("works_on", as_of="2026-01-15")
```

### timeline(entity_name=None)

Chronological list of all facts, optionally filtered to one entity. Limited to 100 results.

```python
all_events = kg.timeline()
kai_history = kg.timeline("Kai")
```

**Returns:** `list[dict]` — ordered by `valid_from` ascending.

### stats()

Overview of the knowledge graph.

```python
kg.stats()
# {
#     "entities": 15,
#     "triples": 47,
#     "current_facts": 38,
#     "expired_facts": 9,
#     "relationship_types": ["child_of", "loves", "works_on", ...],
# }
```

### close()

Close the database connection. Called automatically on garbage collection, but explicit closing is cleaner.

## MCP tools

The knowledge graph is also accessible via MCP:

| Tool | Maps to |
|------|---------|
| `mempalace_kg_query` | `query_entity()` |
| `mempalace_kg_add` | `add_triple()` |
| `mempalace_kg_invalidate` | `invalidate()` |
| `mempalace_kg_timeline` | `timeline()` |
| `mempalace_kg_stats` | `stats()` |

See [mcp-server.md](mcp-server.md) for parameter details.

## Schema

```sql
CREATE TABLE entities (
    id TEXT PRIMARY KEY,          -- lowercased, underscored name
    name TEXT NOT NULL,           -- display name
    type TEXT DEFAULT 'unknown',  -- person, project, tool, concept, animal, ...
    properties TEXT DEFAULT '{}', -- JSON blob
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE triples (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,        -- → entities.id
    predicate TEXT NOT NULL,      -- relationship type (lowercased, underscored)
    object TEXT NOT NULL,         -- → entities.id
    valid_from TEXT,              -- when this became true (ISO date)
    valid_to TEXT,                -- when this stopped being true (NULL = current)
    confidence REAL DEFAULT 1.0,
    source_closet TEXT,           -- reference to palace closet
    source_file TEXT,             -- reference to source file
    extracted_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

Indexes on `subject`, `object`, `predicate`, and `(valid_from, valid_to)`.

The database uses WAL mode for concurrent read access.

## Temporal queries

The `as_of` parameter filters triples to those that were valid at a specific date:

- A triple is valid at date `D` if:
  - `valid_from` is NULL or `valid_from <= D`, AND
  - `valid_to` is NULL or `valid_to >= D`

This means:

- Triples with no dates are always returned (assumed always-valid).
- Triples with a `valid_from` in the future are excluded.
- Triples with a `valid_to` in the past are excluded.

```python
# What's true right now? (valid_to is NULL)
kg.query_entity("Kai")

# What was true on January 15, 2026?
kg.query_entity("Kai", as_of="2026-01-15")

# Full history including expired facts
kg.timeline("Kai")
```
