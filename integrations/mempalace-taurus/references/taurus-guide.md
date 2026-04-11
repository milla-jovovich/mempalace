# MemPalace on Taurus — Deep Integration Guide

**Audience**: Taurus agents adding MemPalace to their workflow
**Related files**: `multi-agent.md`, `memory-complement.md`, `../assets/memory-md-template.md`

---

## How Taurus Differs from MCP Platforms

Most MemPalace documentation assumes an MCP client — OpenClaw, Claude Code, Cursor. Taurus is
categorically different. Understanding the differences is prerequisite to using MemPalace effectively here.

| Feature | OpenClaw / Claude Code / Cursor | Taurus |
|---------|:---:|:---:|
| Persistence | Session-based (ephemeral) | **Persistent Docker containers** |
| Tool interface | MCP (Model Context Protocol) | **Native tools** (Bash/Read/Write/Edit/etc.) |
| Built-in memory | None | **MEMORY.md** (16KB auto-loaded), `/workspace` |
| Multi-agent | Single agent per session | **Parent/child agents, delegate/supervisor** |
| Shared state | None or MCP server state | **/shared volume** across all agents |
| Scheduling | User-triggered only | **Cron schedules** (e.g. `every 15m`, `daily`) |
| Context limits | Per-session only | **Compaction** (platform-triggered summarization) |
| Dashboard hosting | N/A | **/shared/public/name/** served publicly |
| Environment setup | N/A | **.shell-init.sh** sourced every session |

### The Critical Difference: No MCP

Taurus agents **cannot consume MCP tools directly**. The 19 `mempalace_*` MCP tools described in the
main SKILL.md are not available. Instead, Taurus agents access MemPalace two ways:

1. **Python library** — `import mempalace` and call functions directly via the `Bash` tool
2. **palace-helper.py CLI** — a thin wrapper script providing one-line Bash commands

### The Second Critical Difference: MEMORY.md Already Exists

Taurus agents already have a working memory system. MemPalace must *complement* it, not replace it.
See `memory-complement.md` for the full complementarity strategy. Short version: MEMORY.md = index,
MemPalace = archive.

---

## Accessing MemPalace on Taurus

### Pattern A — Python Library (Inline)

Use `Bash` to run inline Python scripts:

```python
# Bash tool — search the palace
python3 - <<'EOF'
import sys; sys.path.insert(0, "/shared/mempalace-agi/src")
import mempalace

palace = mempalace.Palace("/workspace/palace")

# Semantic search
results = palace.search("climate CO2 correlation", limit=5)
for r in results:
    print(f"[{r.wing}/{r.room}] {r.content[:120]}")
EOF
```

```python
# Bash tool — store a finding
python3 - <<'EOF'
import mempalace
palace = mempalace.Palace("/workspace/palace")
palace.add_drawer(
    wing="research",
    room="climate-co2",
    content="CO2 shows r=0.932 correlation with global temperature (Mauna Loa/NOAA, 2026-04-10)"
)
print("Stored.")
EOF
```

```python
# Bash tool — knowledge graph
python3 - <<'EOF'
import mempalace
palace = mempalace.Palace("/workspace/palace")

# Add a fact with validity window
palace.kg_add("CO2_concentration", "correlates_with", "global_temperature",
              valid_from="2026-01-01")

# Query an entity's relationships
triples = palace.kg_query("CO2_concentration")
for t in triples:
    print(f"{t.subject} —[{t.predicate}]→ {t.object}  (from {t.valid_from})")
EOF
```

### Pattern B — palace-helper.py CLI

The `palace-helper.py` script (at `../scripts/palace-helper.py`) provides a simpler CLI interface
for quick one-liners in Bash calls:

```bash
# Search
python3 /shared/mempalace-agi/integrations/mempalace-taurus/scripts/palace-helper.py \
  search "climate CO2 correlation" --palace /workspace/palace

# Store a drawer
python3 /shared/mempalace-agi/integrations/mempalace-taurus/scripts/palace-helper.py \
  store research climate-co2 "CO2 r=0.932 with global temp (NOAA)" --palace /workspace/palace

# KG add
python3 /shared/mempalace-agi/integrations/mempalace-taurus/scripts/palace-helper.py \
  kg-add "CO2" "correlates_with" "global_temperature" --palace /workspace/palace

# Status overview
python3 /shared/mempalace-agi/integrations/mempalace-taurus/scripts/palace-helper.py \
  status --palace /workspace/palace

# Diary entry
python3 /shared/mempalace-agi/integrations/mempalace-taurus/scripts/palace-helper.py \
  diary-write my-agent "Discovered CO2 r=0.932 in NOAA dataset. Stored in climate-co2." \
  --palace /workspace/palace
```

All commands output JSON by default, making it easy to pipe or parse results.

### Environment Setup via .shell-init.sh

Add this to `/workspace/.shell-init.sh` to auto-install and configure MemPalace:

```bash
# MemPalace setup — sourced from taurus-setup.sh
source /shared/mempalace-agi/integrations/mempalace-taurus/scripts/taurus-setup.sh
```

The setup script handles:
- `pip install mempalace` (skipped if already installed)
- Creating palace directory at `$MEMPALACE_PATH` (default `/workspace/palace`)
- Exporting `MEMPALACE_PATH` for use in Bash commands
- Initializing a new palace with standard wings if first run

---

## MEMORY.md Synergy Strategy

### The Two Roles

**MEMORY.md** is your *working memory*:
- 16KB cap, always loaded into context at run start
- Holds current goals, active task state, recent findings, quick indexes
- Fast to read (already in context), easy to update with `Edit`
- Content degrades over time — old entries get crowded out as new ones push them down

**MemPalace** is your *long-term archive*:
- Unlimited capacity, persistent across all runs
- Holds facts, entities, relationships, historical findings, diary entries
- Accessed via semantic search — find relevant content even if you forgot the exact terms
- Survives compaction unchanged

### How MEMORY.md Should Reference the Palace

Keep MEMORY.md lean by storing *pointers* to palace content, not the content itself:

```markdown
## Palace Index
- Palace path: /workspace/palace
- Last updated: 2026-04-11T01:45Z
- Total drawers: ~320 | Wings: research, people, projects

### Key Wings
- wing_research/climate-co2: 47 drawers — CO2/temp correlations, NOAA data
- wing_research/ocean-ph: 12 drawers — Acidification trends
- wing_people/alice: 8 drawers — Alice's preferences, project history
- wing_projects/astra-dev: 63 drawers — Integration decisions, experiment results

### Important Entities (KG)
- CO2_concentration → correlates_with global_temperature (r=0.932, valid 2026-01-01+)
- alice → works_at NewCorp (valid 2026-03-15+)

### Recent Diary Entries
- 2026-04-11: Stored DC-24 breakthrough results (1.83× uplift). See wing_research/discoveries.
- 2026-04-10: Completed Phase 15. See diary for detailed session summary.
```

Notice: MEMORY.md has *references* (wing names, drawer counts, key KG facts) but not the full
content. When you need to recall something specific, you *search* the palace rather than scrolling
through MEMORY.md.

### When to Query the Palace

Don't query on every run — that's overhead with no benefit. Query when:
- You need detailed context about a specific entity, project, or topic
- You're about to make a claim about something you should have in memory
- You need to find connections between topics (traverse/find_tunnels)
- A scheduled task depends on accumulated findings from past runs
- You're about to store something and want to check for duplicates first

---

## Scheduled Run Integration

Taurus agents run on cron schedules. Here's the recommended pattern for each scheduled run:

```
1. MEMORY.md auto-loads — read your index and current state
2. Check if palace query is needed for this run's work
3. Search palace for relevant context (not always required)
4. Do the work
5. Store significant findings in palace
6. Update MEMORY.md pointers if new wings/rooms were created
7. Write diary entry if it was a substantial run
```

### Concrete Pattern for a Research Agent

```python
# At the start of a scheduled run (via Bash tool):
python3 - <<'EOF'
import mempalace
palace = mempalace.Palace("/workspace/palace")

# What's relevant to today's task?
results = palace.search("hypothesis climate CO2 ocean warming", limit=8)
print("=== Relevant Context ===")
for r in results:
    print(f"  [{r.wing}/{r.room}] {r.content[:100]}")

# Check what KG tells us about key entities
triples = palace.kg_query("CO2_concentration")
print("\n=== CO2 Knowledge Graph ===")
for t in triples:
    print(f"  {t.subject} —[{t.predicate}]→ {t.object}")
EOF
```

```python
# After completing this run's work (via Bash tool):
python3 - <<'EOF'
import mempalace, datetime
palace = mempalace.Palace("/workspace/palace")

# Store new findings
palace.add_drawer(
    wing="research",
    room="hypothesis-results",
    content="DC-27: 6/6 pass, C51 late burst replicated p<0.001. mdc=5 saves 90.6% compute."
)

# Update KG with new fact
palace.kg_add("mdc_parameter", "optimal_value", "5",
              valid_from=str(datetime.date.today()))

# Write diary entry
palace.diary_write(
    agent_name="mempalace-researcher",
    entry="Completed DC-27 validation. 6/6 pass, mdc=5 confirmed as optimal. "
          "Results stored in wing_research/hypothesis-results.",
    topic="experiment-results"
)
print("Palace updated.")
EOF
```

### Low-Overhead Scheduled Runs

Not every scheduled run needs to touch the palace. If your run is a simple maintenance task
(update a timestamp, sync a file), skip the palace queries. The 16KB MEMORY.md auto-load
is often sufficient for quick runs.

---

## Compaction Survival

Taurus triggers compaction when context grows large. You're asked to write a summary — then
the conversation restarts from that summary. After compaction, your palace is intact (it's
a file on disk), but you may have lost track of *which parts* of the palace matter.

### What to Include in Your Compaction Summary

Always include a **Palace State** section in your compaction summary:

```markdown
## Palace State (as of compaction 2026-04-11T01:45Z)
- **Location**: /workspace/palace  (or /shared/palace for team)
- **Total drawers**: ~320  |  Wings: research(183), people(42), projects(95)
- **KG triples**: 1,019  |  Entities: 291

### Active Wings and Their Purpose
- `wing_research/climate-co2`: CO2 correlation experiments — 47 drawers
- `wing_research/discoveries`: Breakthrough findings — DC-24 through DC-27
- `wing_people/alice`: Alice's preferences, project context
- `wing_projects/astra-dev`: ASTRA-dev integration state

### Key KG Facts (most important entities)
- CO2_concentration → correlates_with → global_temperature (r=0.932, 2026-01-01+)
- mdc_parameter → optimal_value → 5 (2026-04-11+)

### Most Recent Diary Entries
- 2026-04-11: DC-27 validation complete. 6/6 pass. mdc=5 confirmed.
- 2026-04-10: Phase 15 deep saturation complete. 185 total discoveries.

### Critical Pointers (search these terms to reconnect)
- "discovery experiment results" → wing_research/hypothesis-results
- "knowledge graph calibration" → wing_research/kg-calibration
- "integration decision log" → wing_projects/astra-dev
```

### Template for Compaction Summary Palace Section

```markdown
## Palace State (as of compaction YYYY-MM-DDTHH:MMZ)
- **Location**: /path/to/palace
- **Total drawers**: ~N  |  Wings: W1(N1), W2(N2), W3(N3)
- **KG triples**: N  |  Entities: N

### Active Wings
| Wing | Room Count | Contains |
|------|:---:|--------|
| wing_X | N | description |

### Key KG Entities
- entity → predicate → value (valid_from)

### Recent Diary
- YYYY-MM-DD: one-line session summary

### Reconnect Queries
- "semantic phrase" → wing/room  (search this to find relevant content)
```

### After Compaction: Reconnecting

On the first run after compaction, your MEMORY.md (loaded from summary) has the palace
pointers. Run this to verify connectivity and refresh your mental model:

```bash
python3 /shared/mempalace-agi/integrations/mempalace-taurus/scripts/palace-helper.py \
  status --palace /workspace/palace
```

Then search for your "reconnect queries" to pull the most relevant content back into context.

---

## Dashboard Integration

MemPalace content can be visualized in Taurus dashboards served from `/shared/public/<name>/index.html`.

A simple integration: export palace statistics to JSON, then render them in your dashboard:

```python
# Generate palace stats for dashboard (via Bash tool)
python3 - <<'EOF'
import json, mempalace
palace = mempalace.Palace("/workspace/palace")
status = palace.status()

stats = {
    "total_drawers": status.total_drawers,
    "wing_count": len(status.wings),
    "wings": [{"name": w.name, "drawers": w.drawer_count} for w in status.wings],
    "kg_triples": palace.kg_stats().triple_count,
    "updated_at": "2026-04-11T01:45Z"
}

with open("/shared/public/my-dashboard/palace-stats.json", "w") as f:
    json.dump(stats, f, indent=2)
print("Stats exported.")
EOF
```

The dashboard JavaScript can then fetch `palace-stats.json` and display wing occupancy,
recent discoveries, entity counts, or whatever is relevant to your project.

---

## Quick Reference: Common Operations

| Goal | Command |
|------|---------|
| Search palace | `python palace-helper.py search "query" --palace /workspace/palace` |
| Store finding | `python palace-helper.py store wing room "content" --palace /path` |
| KG add fact | `python palace-helper.py kg-add subj pred obj --palace /path` |
| KG invalidate | `python palace-helper.py kg-invalidate subj pred obj --palace /path` |
| Status overview | `python palace-helper.py status --palace /workspace/palace` |
| Write diary | `python palace-helper.py diary-write agent-name "entry" --palace /path` |
| Read diary | `python palace-helper.py diary-read agent-name --palace /path` |
| Check duplicate | `python palace-helper.py check-duplicate "content" --palace /path` |

---

*See also: `multi-agent.md` | `memory-complement.md` | `mempalace-agi.md` | `../assets/memory-md-template.md`*
