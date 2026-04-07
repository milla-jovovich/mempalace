---
layout: docs
title: Knowledge Graph
description: Temporal entity-relationship triples with validity windows. Like Zep's Graphiti, but SQLite-backed and free.
eyebrow: Core Concepts
heading: Knowledge Graph
subtitle: Temporal entity-relationship triples with validity windows. Facts know when they started, and when they stopped being true.
prev:
  href: /aaak
  label: AAAK Dialect
next:
  href: /mcp
  label: MCP Server
toc:
  - { id: what,           label: What it is }
  - { id: usage,          label: Usage }
  - { id: invalidation,   label: Invalidation }
  - { id: contradictions, label: Contradiction Detection }
  - { id: vs-zep,         label: vs Zep (Graphiti) }
---

## What it is {#what}

The knowledge graph stores structured relationships alongside the verbatim
palace. Think of it as the "facts" layer: who works on what, who decided what,
who reported to whom, when things started, when they stopped.

It's backed by **SQLite**, runs on your machine, costs nothing, and supports
the same temporal validity queries as Zep's Graphiti.

## Usage {#usage}

```python
from mempalace.knowledge_graph import KnowledgeGraph

kg = KnowledgeGraph()

# Add facts with validity windows
kg.add_triple("Kai", "works_on", "Orion", valid_from="2025-06-01")
kg.add_triple("Maya", "assigned_to", "auth-migration", valid_from="2026-01-15")
kg.add_triple("Maya", "completed", "auth-migration", valid_from="2026-02-01")

# What's Kai working on right now?
kg.query_entity("Kai")
# → [Kai → works_on → Orion (current),
#    Kai → recommended → Clerk (2026-01)]

# What was true in January?
kg.query_entity("Maya", as_of="2026-01-20")
# → [Maya → assigned_to → auth-migration (active)]

# Full chronological story
kg.timeline("Orion")
# → ordered events across the whole project
```

Every triple has a `valid_from` timestamp. Queries can be anchored to a
specific point in time with `as_of=`.

## Invalidation {#invalidation}

Facts don't stop being true by vanishing — they get explicitly invalidated
with an end date:

```python
kg.invalidate("Kai", "works_on", "Orion", ended="2026-03-01")
```

Now:

- **Current queries** for Kai's work no longer return Orion
- **Historical queries** (`as_of="2026-02-15"`) still return it
- The full **timeline** still shows Kai's Orion period

This matters for a memory system: you can look back at what the world looked
like six months ago without corrupting the present.

## Contradiction Detection {#contradictions}

MemPalace uses the knowledge graph to catch mistakes before they reach you:

```text
Input:  "Soren finished the auth migration"
Output: 🔴 AUTH-MIGRATION: attribution conflict — Maya was assigned, not Soren

Input:  "Kai has been here 2 years"
Output: 🟡 KAI: wrong_tenure — records show 3 years (started 2023-04)

Input:  "The sprint ends Friday"
Output: 🟡 SPRINT: stale_date — current sprint ends Thursday (updated 2 days ago)
```

Facts are checked against the knowledge graph. Ages, dates, and tenures are
calculated dynamically — not hardcoded. When you or your AI state something
that contradicts a stored fact, MemPalace flags it.

Severity levels:

- 🔴 **Hard conflict** — contradicts a stored fact with high confidence
- 🟡 **Soft conflict** — stale data or approximate mismatch
- 🟢 **Consistent** — matches the graph

## vs Zep (Graphiti) {#vs-zep}

<div class="table-wrap" markdown="1">

| Feature            | MemPalace          | Zep (Graphiti)    |
|--------------------|--------------------|-------------------|
| Storage            | SQLite (local)     | Neo4j (cloud)     |
| Cost               | **Free**           | $25/mo+           |
| Temporal validity  | Yes                | Yes               |
| Self-hosted        | Always             | Enterprise only   |
| Privacy            | Everything local   | SOC 2, HIPAA      |
| Setup complexity   | Zero               | Neo4j cluster     |

</div>

Same temporal model. Same query semantics. A single SQLite file instead of a
Neo4j cluster. No monthly bill.
