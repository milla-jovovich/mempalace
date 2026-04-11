# MemPalace Multi-Agent Palace Sharing on Taurus

**Audience**: Taurus agent teams adding shared memory to multi-agent workflows
**Related files**: `taurus-guide.md`, `memory-complement.md`

---

## Shared vs Private Palaces

Taurus mounts two persistent volumes: `/workspace` (private per agent) and `/shared` (communal).
This maps directly onto two palace deployment patterns:

| Location | Who Can Access | Best For |
|----------|:-:|---------|
| `/workspace/palace` | This agent only | Agent-private memory, personal notes, scratchpad |
| `/shared/palace` | All agents in the tree | Team knowledge, shared discoveries, cross-agent facts |

**Rule of thumb**: Use `/shared/palace` whenever two or more agents need to read or write the same
facts. Use `/workspace/palace` for an agent's working notes that no other agent needs.

A team can use both simultaneously: shared palace for collective knowledge, private palace for
drafts and intermediate state. An agent writes to its private palace during work, then promotes
finished findings to the shared palace.

---

## Wing-Per-Agent Pattern

The standard structure for a multi-agent team:

```
/shared/palace/
├── wing_engineer/          # Engineer agent's own wing
│   ├── code-decisions/     # Architecture choices, trade-offs
│   ├── implementation/     # Implementation notes, gotchas
│   └── benchmarks/         # Performance results
│
├── wing_researcher/        # Researcher agent's own wing
│   ├── hypotheses/         # Active hypotheses under test
│   ├── literature/         # Paper summaries, citations
│   └── experiment-design/  # Methodology notes
│
├── wing_scout/             # Scout agent's own wing
│   ├── repo-intel/         # Repository analysis findings
│   ├── pr-reviews/         # PR review summaries
│   └── ecosystem/          # Competitor and ecosystem intelligence
│
├── wing_writer/            # Writer agent's own wing
│   ├── drafts/             # Document drafts in progress
│   ├── published/          # Links and summaries of published docs
│   └── editorial/          # Style notes, terminology decisions
│
├── wing_discoveries/       # SHARED — cross-agent discoveries
│   ├── breakthroughs/      # Major findings (any agent writes)
│   ├── experiments/        # Experiment results registry
│   └── validated/          # Confirmed findings with evidence
│
└── wing_project/           # SHARED — project-wide knowledge
    ├── decisions/           # Architectural decisions (permanent record)
    ├── status/             # Current integration state
    └── entities/           # Known entities and relationships
```

### Naming Convention

- Agent-private wings: `wing_{agent-role}` (e.g. `wing_engineer`, `wing_writer`)
- Shared wings: descriptive names without agent prefix (e.g. `wing_discoveries`, `wing_project`)
- Rooms: lowercase hyphenated (e.g. `code-decisions`, `experiment-results`)

---

## Specialist Diaries

MemPalace diary entries are namespaced by `agent_name`. Each agent writes under its own name;
agents can read each other's diaries to understand what their teammates have been doing.

### Writing Your Diary Entry

At the end of a significant run, each agent writes a diary entry:

```python
python3 - <<'EOF'
import mempalace
palace = mempalace.Palace("/shared/palace")

palace.diary_write(
    agent_name="mempalace-engineer",
    entry=(
        "Implemented PalaceDiscoveryMemory dual-write. "
        "All 588 tests passing. ChromaDB→LanceDB migration "
        "complete. Stored implementation notes in wing_engineer/implementation."
    ),
    topic="implementation-milestone"
)
EOF
```

### Reading a Teammate's Diary

```python
python3 - <<'EOF'
import mempalace
palace = mempalace.Palace("/shared/palace")

# Read the researcher's last 5 entries
entries = palace.diary_read("mempalace-researcher", last_n=5)
for e in entries:
    print(f"[{e.created_at}] {e.entry[:150]}")
    print()
EOF
```

### Diary Integration Pattern

A supervisor or writer agent can synthesize diary entries across all teammates:

```python
python3 - <<'EOF'
import mempalace
palace = mempalace.Palace("/shared/palace")
agents = ["mempalace-engineer", "mempalace-researcher", "mempalace-scout", "mempalace-writer"]

print("=== Team Diary Digest ===")
for agent in agents:
    entries = palace.diary_read(agent, last_n=3)
    if entries:
        print(f"\n--- {agent} ({len(entries)} recent entries) ---")
        for e in entries:
            print(f"  {e.created_at[:10]}: {e.entry[:100]}")
EOF
```

---

## Delegation with Palace Context

When a parent agent delegates a task to a child, it can include relevant palace content in the
task description to give the child agent immediate context without requiring the child to do a
cold search.

### Pattern: Search → Extract → Include in Delegation

```python
# Parent agent: gather palace context before delegating
python3 - <<'EOF'
import mempalace, json
palace = mempalace.Palace("/shared/palace")

# Find relevant context for the delegated task
results = palace.search("CO2 temperature correlation ocean warming", limit=5)

context = "\n".join([
    f"[{r.wing}/{r.room}] {r.content}" for r in results
])

# Also get key KG facts
triples = palace.kg_query("CO2_concentration")
kg_context = "\n".join([
    f"{t.subject} —[{t.predicate}]→ {t.object}" for t in triples[:5]
])

print("=== PALACE CONTEXT FOR DELEGATION ===")
print(context)
print("\n=== KEY KG FACTS ===")
print(kg_context)
EOF
```

Then include this in the Delegate task description:

```
## Task: Analyze CO2 Ocean Coupling

### Palace Context (pre-searched for you)
[climate/ocean-ph] Acidification rate: 0.1 pH units/century since 1750
[climate/co2-trend] Mauna Loa CO2: 421 ppm as of 2026-04-10 (r=0.932 with temp)
[research/hypotheses] H-014: Ocean thermal expansion coupled to CO2 via feedback

### Key KG Facts
CO2_concentration —[correlates_with]→ global_temperature
ocean_pH —[affected_by]→ CO2_concentration

### Your Task
...
```

This pattern reduces the child agent's cold-start time and avoids redundant palace queries.

---

## Conflict Resolution

ChromaDB handles concurrent reads from multiple agents without locking. Multiple agents can
search simultaneously. Writes are serialized at the ChromaDB level.

### Deduplication Before Storing

**Always check for duplicates before storing**, especially in shared wings where multiple agents
may store similar findings:

```python
python3 - <<'EOF'
import mempalace
palace = mempalace.Palace("/shared/palace")

new_content = "CO2 shows r=0.932 correlation with global temperature"

# Check if this is already stored (threshold 0.85 catches near-duplicates)
dup = palace.check_duplicate(new_content, threshold=0.85)
if dup.is_duplicate:
    print(f"Duplicate found (similarity {dup.score:.2f}): {dup.existing_content[:80]}")
    print("Skipping storage.")
else:
    palace.add_drawer("research", "climate-co2", new_content)
    print("Stored.")
EOF
```

### Knowledge Graph Contradictions

When two agents add contradicting KG facts (e.g., one says Alice works at Corp A, another says
Corp B), use the invalidate-then-add pattern:

```python
python3 - <<'EOF'
import mempalace, datetime
palace = mempalace.Palace("/shared/palace")

# Invalidate the old (incorrect) fact
palace.kg_invalidate(
    subject="Alice",
    predicate="works_at",
    object="OldCorp",
    ended=str(datetime.date.today())
)

# Add the current fact
palace.kg_add(
    subject="Alice",
    predicate="works_at",
    object="NewCorp",
    valid_from=str(datetime.date.today())
)
print("KG updated: Alice → works_at → NewCorp")
EOF
```

The KG's bi-temporal model records both facts with their validity windows, so the historical
record is preserved. `kg_query(entity="Alice", as_of="2026-01-01")` would still return the
OldCorp fact for that date.

---

## Example Multi-Agent Setup

Here's a concrete 3-agent team (engineer, researcher, writer) sharing a palace:

### Shared Palace Layout

```
/shared/palace/
├── wing_engineer/      # Engineer: code decisions, implementation
├── wing_researcher/    # Researcher: hypotheses, experiments
├── wing_writer/        # Writer: drafts, published docs
├── wing_discoveries/   # SHARED: breakthroughs, validated results
└── wing_project/       # SHARED: decisions, status, entities
```

### Each Agent's MEMORY.md Palace Section

```markdown
## Palace Index (/shared/palace)
- My wing: wing_engineer (83 drawers)
- Shared wings: wing_discoveries (147), wing_project (42)
- Last diary: 2026-04-11 — Implemented PalaceDiscoveryMemory
```

```markdown
## Palace Index (/shared/palace)
- My wing: wing_researcher (121 drawers)
- Shared wings: wing_discoveries (147), wing_project (42)
- Last diary: 2026-04-11 — DC-27 validated (6/6 pass, mdc=5 optimal)
```

```markdown
## Palace Index (/shared/palace)
- My wing: wing_writer (38 drawers)
- Shared wings: wing_discoveries (147), wing_project (42)
- Last diary: 2026-04-11 — Updated integration guide with DC-27 results
```

### Daily Coordination Pattern

1. **Each agent starts** by reading MEMORY.md (auto-loaded) and optionally querying relevant palace wings
2. **During work**, each agent stores findings to its own wing and/or shared wings
3. **Before finishing**, each agent writes a diary entry
4. **Writer agent** synthesizes: reads researcher's diary, searches wing_discoveries, produces docs
5. **Supervisor** (or writer) reads all diary entries to get a team-wide picture

### Palace Initialization (one-time, usually by a parent agent)

```bash
python3 /shared/mempalace-agi/integrations/mempalace-taurus/scripts/palace-init.py \
  --palace /shared/palace \
  --wings engineer researcher scout writer discoveries project \
  --rooms engineer:code-decisions,implementation,benchmarks \
  --rooms researcher:hypotheses,literature,experiment-design \
  --rooms shared:breakthroughs,experiments,validated
```

---

*See also: `taurus-guide.md` | `memory-complement.md` | `mempalace-agi.md`*
