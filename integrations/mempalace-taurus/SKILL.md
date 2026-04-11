---
name: mempalace-taurus
description: >
  MemPalace for Taurus multi-agent platform — persistent semantic memory with 96.6%
  recall. Adds palace architecture (wings/rooms/drawers), temporal knowledge graph,
  and ChromaDB semantic search to Taurus agents. Complements MEMORY.md with unlimited
  long-term memory. Use when agents need cross-session facts, entity tracking,
  multi-agent shared knowledge, or semantic search over past findings.
version: 1.0.0
homepage: https://github.com/milla-jovovich/mempalace
license: MIT
compatibility: >
  Taurus platform with Python 3.10+ and persistent /workspace or /shared volumes.
  Also works on any AgentSkills-compatible platform with MCP support (OpenClaw,
  Claude Code, Cursor, Codex, Gemini CLI, VS Code, etc.).
metadata:
  author: mempalace-agi
  taurus:
    access-pattern: python-library-via-bash
    shared-palace: /shared/palace
    private-palace: /workspace/palace
    shell-init: scripts/taurus-setup.sh
    multi-agent: "true"
    complements: MEMORY.md
  openclaw:
    emoji: "\U0001F3DB"
    os:
      - darwin
      - linux
    requires:
      anyBins:
        - python3
    install:
      - id: mempalace-pip
        kind: uv
        label: "Install MemPalace (Python, local ChromaDB)"
        package: mempalace
        bins:
          - mempalace
---

# MemPalace — Persistent AI Memory for Taurus Agents

You have access to a **memory palace** — a hierarchical, semantically-searchable, persistent knowledge store with 96.6% recall on the LongMemEval benchmark. It stores verbatim content and a temporal knowledge graph, all local, zero cloud, zero API keys.

On Taurus, MemPalace **complements your MEMORY.md** with unlimited long-term memory that survives compaction and scales across thousands of facts.

## When to Use MemPalace vs MEMORY.md

| Use Case | MEMORY.md | MemPalace |
|----------|:---------:|:---------:|
| Current goals and active tasks | ✅ | |
| Session state and recent context | ✅ | |
| Quick index/pointers (< 16KB) | ✅ | |
| Long-term facts about people/projects | | ✅ |
| Semantic search across all history | | ✅ |
| Cross-agent shared knowledge | | ✅ |
| Temporal fact tracking (when things were true) | | ✅ |
| Cross-domain discovery connections | | ✅ |
| Entity relationships (who knows whom, etc.) | | ✅ |

**Rule of thumb**: If it fits in 16KB and you need it every single run → **MEMORY.md**. If it's a growing knowledge base you search into → **MemPalace**.

Keep MEMORY.md as an **index** that points into the palace, not a copy of it. See [references/memory-complement.md](references/memory-complement.md) for the full guide.

## Architecture

- **Wings** = people, projects, or domains (e.g. `wing_research`, `wing_alice`, `wing_myproject`)
- **Rooms** = specific topics within a wing (e.g. `climate-co2`, `riley-school`, `chromadb-setup`)
- **Drawers** = individual memory chunks (verbatim text, semantically searchable)
- **Knowledge Graph** = entity-relationship facts with time validity (subject → predicate → object, with valid_from/valid_to)

Think of it as: a **palace** contains **wings** (like building wings), each wing has **rooms** (topics), each room has **drawers** (memories). The knowledge graph overlays the whole palace with typed, temporal relationships.

## Protocol — FOLLOW EVERY RUN

### 1. On Run Start

Your MEMORY.md is already loaded (Taurus auto-loads the first ~16KB). Check if it references palace content you need:

```bash
# Quick status check — how big is the palace?
python scripts/palace-helper.py status

# If MEMORY.md mentions something you need to recall:
python scripts/palace-helper.py search "the topic you need context on" --limit 3
```

### 2. Before Responding About Facts

**Always search before guessing.** If asked about a person, project, entity, or past event:

```bash
python scripts/palace-helper.py search "alice birthday preferences" --limit 5
python scripts/palace-helper.py kg-query Alice
```

Wrong is worse than slow. Say "let me check my records" and query.

### 3. After Completing Work

Store significant findings, decisions, and facts:

```bash
# Store a finding in a wing/room
python scripts/palace-helper.py store research climate \
  "CO2 shows r=0.932 correlation with temperature (Mauna Loa, NOAA, 2026)"

# Add a knowledge graph fact
python scripts/palace-helper.py kg-add \
  CO2_concentration correlates_with global_temperature \
  --valid-from 2026-04-11

# Write a diary entry summarizing your session
python scripts/palace-helper.py diary-write my-agent-name \
  "Completed climate analysis. Key finding: CO2 r=0.932. Stored in wing_research/climate."
```

### 4. When Facts Change

Invalidate the old fact, then add the new one:

```bash
python scripts/palace-helper.py kg-invalidate Alice works_at OldCorp
python scripts/palace-helper.py kg-add Alice works_at NewCorp --valid-from 2026-04-11
```

### 5. On Compaction

When Taurus triggers compaction and asks you to write a summary, include palace pointers:

```
## Palace State
- Palace: /shared/palace (1,389 drawers, 291 entities)
- Key wings: wing_research (580 drawers), wing_people (234 drawers)
- Recent diary: see diary entries for my-agent-name
- Important entities: Alice (works_at NewCorp), CO2_concentration, Project_Alpha
```

### 6. Update MEMORY.md Pointers

After storing new content, update your MEMORY.md to point to it rather than duplicating:

```markdown
## Palace Quick Reference
- Alice's preferences → wing_people/alice-prefs (47 drawers)
- Climate findings → wing_research/climate (26 drawers, CO2 r=0.932 ⭐)
- Project Alpha status → wing_projects/alpha (KG: 12 triples)
```

## Available Operations

### Search & Browse

- **search** `query [--wing W] [--room R] [--limit N]` — Semantic search across all memories. Always start here.
- **status** — Palace overview: total drawers, wings, rooms, protocol reminder
- **list-wings** — All wings with drawer counts
- **list-rooms** `[--wing W]` — Rooms within a wing (optional wing filter)
- **taxonomy** — Full wing/room/count tree
- **check-dup** `content [--threshold T]` — Check if content exists before filing (default threshold 0.9; 0.85–0.87 catches more near-duplicates)

### Knowledge Graph (Temporal Facts)

- **kg-query** `entity [--as-of DATE] [--direction DIR]` — Query entity relationships. Supports time filtering (YYYY-MM-DD).
- **kg-add** `subject predicate object [--valid-from DATE] [--source SRC]` — Add a fact: subject → predicate → object
- **kg-invalidate** `subject predicate object [--ended DATE]` — Mark a fact as no longer true
- **kg-timeline** `[entity]` — Chronological story of an entity (all if omitted)
- **kg-stats** — Graph overview: entities, triples, relationship types

### Palace Graph (Cross-Domain Connections)

- **traverse** `start_room [--max-hops N]` — Walk from a room, find connected ideas across wings
- **tunnels** `wing_a wing_b` — Find rooms that bridge two wings
- **graph-stats** — Graph connectivity overview

### Write

- **store** `wing room "content" [--source FILE]` — Store verbatim content (auto-dedup)
- **delete** `drawer_id` — Remove a drawer by ID
- **diary-write** `agent_name "entry" [--topic TOPIC]` — Write a session diary entry
- **diary-read** `agent_name [--last-n N]` — Read recent diary entries

## Setup

### Taurus Setup (Recommended)

Add to your `.shell-init.sh`:

```bash
# MemPalace for Taurus — persistent AI memory
source /shared/mempalace-agi/integrations/mempalace-taurus/scripts/taurus-setup.sh
```

Or see [scripts/taurus-setup.sh](scripts/taurus-setup.sh) and copy the relevant lines.

This will:
1. Install `mempalace` if not already present
2. Set `MEMPALACE_PATH` (default: `/shared/palace` for multi-agent, `/workspace/palace` for single-agent)
3. Create the palace directory if needed
4. Set up a `palace` alias for the helper script

Then initialize your palace structure:

```bash
python scripts/palace-init.py --shared  # For multi-agent (writes to /shared/palace)
python scripts/palace-init.py --private # For single-agent (writes to /workspace/palace)
```

### Multi-Agent Setup

For teams of Taurus agents sharing a palace, see [references/multi-agent.md](references/multi-agent.md). Key pattern: one palace at `/shared/palace`, each agent gets a wing + shared wings for cross-agent knowledge.

### MCP-Compatible Platforms (OpenClaw, Claude Code, Cursor, etc.)

```bash
pip install mempalace
mempalace init ~/palace

# OpenClaw
openclaw mcp set mempalace '{"command":"python3","args":["-m","mempalace.mcp_server"]}'

# Claude Code
claude mcp add mempalace -- python -m mempalace.mcp_server

# Cursor — add to .cursor/mcp.json
# Codex — add to .codex/mcp.json
```

## Tips

- **Search is semantic** (meaning-based), not keyword. "What did we discuss about database performance?" works better than "database".
- **The knowledge graph stores typed relationships with time windows.** Use it for facts about people, projects, and entities — it knows WHEN things were true.
- **Diary entries accumulate across sessions.** Write one at the end of each run to build continuity.
- **Check duplicates first** — use `check-dup` before storing to avoid duplicates. Threshold 0.85–0.87 is recommended.
- **AAAK dialect** (from `status`) is a compressed notation for efficient storage. Read it naturally — expand codes mentally, treat `*markers*` as emotional context.
- **On Taurus: keep MEMORY.md lean** — store pointers to palace content, not copies. The palace is searchable; MEMORY.md is not.
- **Multi-agent teams**: Each agent writes to its own wing. Use shared wings (e.g. `wing_discoveries`) for cross-agent knowledge.
- **Compaction-proof your work**: Always store important findings in the palace, not just in conversation context that gets compacted away.

## Advanced: MemPalace-AGI Integration

For autonomous research with OODA discovery cycles, hypothesis lifecycle, and 28 unified tools, see [references/mempalace-agi.md](references/mempalace-agi.md). This extends standard MemPalace with ASTRA-dev's discovery engine for structured scientific investigation.

## License

[MemPalace](https://github.com/milla-jovovich/mempalace) is MIT licensed. Created by Milla Jovovich, Ben Sigman, Igor Lins e Silva, and contributors.
