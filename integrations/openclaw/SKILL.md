---
name: mempalace
description: "MemPalace — Local AI memory with 96.6% recall. Semantic search over past conversations, knowledge graph with temporal facts, palace architecture (wings/rooms/drawers). Free, no cloud, no API keys. Highest LongMemEval score ever published."
version: 1.4.0
homepage: https://github.com/milla-jovovich/mempalace
user-invocable: true
metadata:
  openclaw:
    emoji: "🏛️"
    requires:
      anyBins:
        - mempalace
        - python3
    install:
      - id: mempalace-pip
        kind: uv
        label: "Install MemPalace (Python, local ChromaDB)"
        package: mempalace
        bins:
          - mempalace
---

# MemPalace — Local AI Memory System

You have access to a local memory palace via MCP tools. The palace stores verbatim conversation history and a temporal knowledge graph — all on the user's machine, zero cloud, zero API calls.

## Architecture

- **Wings** = people or projects (e.g. `wing_alice`, `wing_myproject`)
- **Halls** = categories (facts, events, preferences, advice)
- **Rooms** = specific topics (e.g. `chromadb-setup`, `riley-school`)
- **Drawers** = individual memory chunks (verbatim text)
- **Knowledge Graph** = entity-relationship facts with time validity

## Protocol — FOLLOW THIS EVERY SESSION

1. **ON WAKE-UP**: Call `mempalace_status` to load palace overview.
2. **BEFORE RESPONDING** about any person, project, or past event: call `mempalace_search` or `mempalace_kg_query` FIRST. Never guess from memory — verify from the palace.
3. **IF UNSURE** about a fact (name, age, relationship, preference): say "let me check" and query. Wrong is worse than slow.
4. **AFTER EACH SESSION**: Call `mempalace_diary_write` to record what happened, what you learned, what matters.
5. **WHEN FACTS CHANGE**: Call `mempalace_kg_invalidate` on the old fact, then `mempalace_kg_add` for the new one.

## Available Tools

### Search & Browse
- `mempalace_search` — Semantic search across all memories. Always start here.
  - `query` (required): natural language search
  - `wing`: filter by wing
  - `room`: filter by room
  - `limit`: max results (default 5)
- `mempalace_status` — Palace overview: total drawers, wings, rooms
- `mempalace_list_wings` — All wings with drawer counts
- `mempalace_list_rooms` — Rooms within a wing
- `mempalace_get_taxonomy` — Full wing/room/count tree

### Knowledge Graph (Temporal Facts)
- `mempalace_kg_query` — Query entity relationships. Supports time filtering.
  - `entity` (required): e.g. "Max", "MyProject"
  - `as_of`: date filter (YYYY-MM-DD) — what was true at that time
  - `direction`: "outgoing", "incoming", or "both"
- `mempalace_kg_add` — Add a fact: subject -> predicate -> object
  - `subject`, `predicate`, `object` (required)
  - `valid_from`: when this became true
- `mempalace_kg_invalidate` — Mark a fact as no longer true
  - `subject`, `predicate`, `object` (required)
  - `ended`: when it stopped being true (default: today)
- `mempalace_kg_timeline` — Chronological story of an entity
- `mempalace_kg_stats` — Graph overview: entities, triples, relationship types

### Palace Graph (Cross-Domain Connections)
- `mempalace_traverse` — Walk from a room, find connected ideas across wings
  - `start_room` (required): room to start from
  - `max_hops`: connection depth (default 2)
- `mempalace_find_tunnels` — Rooms that bridge two wings
- `mempalace_graph_stats` — Graph connectivity overview

### Write
- `mempalace_add_drawer` — Store verbatim content into a wing/room
  - `wing`, `room`, `content` (required)
  - Checks for duplicates automatically
- `mempalace_delete_drawer` — Remove a drawer by ID
- `mempalace_diary_write` — Write a session diary entry
  - `agent_name` (required): your name
  - `entry` (required): what happened, what you learned
  - `topic`: category tag
- `mempalace_diary_read` — Read recent diary entries

## Setup

The user needs to initialize and populate the palace first:

```bash
pip install mempalace
mempalace init ~/my-convos
mempalace mine ~/my-convos
```

Then connect via MCP (for Claude Code, Cursor, etc.):

```bash
claude mcp add mempalace -- python -m mempalace.mcp_server
```

For OpenClaw, add to your MCP config:

```json
{
  "mcpServers": {
    "mempalace": {
      "command": "python3",
      "args": ["-m", "mempalace.mcp_server"]
    }
  }
}
```

## Tips

- Search is semantic (meaning-based), not keyword. "What did we discuss about database performance?" works better than "database".
- The knowledge graph stores typed relationships with time windows. Use it for facts about people and projects — it knows WHEN things were true.
- Diary entries accumulate across sessions. Write one at the end of each conversation to build continuity.
- Wings auto-detect from directory names during mining. You can also create custom wings via `mempalace_add_drawer`.

## License & Attribution

This skill is an integration for [MemPalace](https://github.com/milla-jovovich/mempalace), created by **Ben Sigman** ([@bensig](https://github.com/bensig)), **Igor Lins e Silva** ([@igorls](https://github.com/igorls)), **Milla Jovovich** ([@milla-jovovich](https://github.com/milla-jovovich)), and **adv3nt3** ([@adv3nt3](https://github.com/adv3nt3)), licensed under the MIT License.

```
MIT License

Copyright (c) 2026 MemPalace Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
