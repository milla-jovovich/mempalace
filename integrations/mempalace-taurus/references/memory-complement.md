# MEMORY.md + MemPalace: The Two-Memory Architecture

**Audience**: Taurus agents deciding what goes where
**Related files**: `taurus-guide.md`, `../assets/memory-md-template.md`

---

## The Two-Memory Architecture

Taurus agents have two complementary memory systems. They serve different purposes and work best
together, not as alternatives to each other.

**MEMORY.md — Working Memory**
- Auto-loaded at run start (first ~16KB always in context)
- Fast to read (no tool call needed), fast to update (one Edit)
- Capacity-constrained — old content gets pushed below the auto-load cutoff
- Ideal for: current goals, active task state, recent context, quick indexes

**MemPalace — Long-Term Archive**
- Unlimited capacity, persistent across all runs and compactions
- Accessed via semantic search — finds relevant content even without exact terms
- Survives context resets completely intact
- Ideal for: accumulated facts, entities, relationships, historical findings, session diaries

Think of MEMORY.md as a whiteboard — always visible, but limited space, erased and rewritten
constantly. Think of MemPalace as a well-organized library — you have to walk over and pull a
book, but it holds everything you've ever learned.

---

## When to Use Which

| Information Type | MEMORY.md | MemPalace | Notes |
|-----------------|:---------:|:---------:|-------|
| Current goals & active tasks | ✅ | | Needs to be in context every run |
| Session state & recent actions | ✅ | | Changes every run, not worth archiving |
| Quick pointers / index entries | ✅ | | "See wing_research/climate for CO2 data" |
| Credentials, paths, env vars | ✅ | | System config, not semantic knowledge |
| People's names, birthdays, preferences | | ✅ | KG: `Alice —[birthday]→ April 3` |
| Project history & past decisions | | ✅ | Grows unboundedly, semantic search useful |
| Experiment results & discoveries | | ✅ | Many results, need to search across them |
| Cross-session facts (what was true when) | | ✅ | KG temporal model is perfect for this |
| Cross-agent shared knowledge | | ✅ | `/shared/palace` accessible by all |
| Academic / literature references | | ✅ | Too much to keep in MEMORY.md |
| Contradicted / superseded facts | | ✅ | KG invalidation preserves history |
| Real-time metrics & live stats | ✅ | | Latest values only; palace for trends |
| Long-running experiment summaries | ✅ (pointer) + ✅ (details) | | MEMORY.md has one-liner, palace has full |

### Decision Rule

> If you'll need it every single run and it fits in one or two lines → MEMORY.md.
> If it's a fact about the world (entities, relationships, findings) → MemPalace.
> If it grows over time → MemPalace.
> If it changes (person moves jobs, project changes direction) → MemPalace KG with timestamps.

---

## MEMORY.md as Index Pattern

The most effective pattern: MEMORY.md holds *pointers* to palace locations, not the content itself.

### What This Looks Like in Practice

Instead of this (anti-pattern — MEMORY.md as encyclopedia):

```markdown
## Research Findings
- Climate: CO2 shows r=0.932 correlation with global temperature per Mauna Loa dataset
  NOAA 2026-04-10. Station: MLO. Instrument: NDIR. Also confirmed with AIRS satellite data.
  Ocean acidification pH trend: −0.1 units/century since 1750. Rate accelerating since 1950.
  Arctic sea ice decline: 13.1% per decade (1979–2026). Albedo feedback confirmed via CERES.
- Alice: Birthday April 3rd. Prefers text over calls. Vegetarian. Project manager at NewCorp
  since March 2026 (moved from OldCorp). Has a labrador named Biscuit. Kids: Sam (8), Jo (5).
  Best contact time: 9-11 AM Pacific. Dislikes jargon in emails.
[... 200 more lines ...]
```

Do this (MEMORY.md as index — palace as encyclopedia):

```markdown
## Palace Index (/workspace/palace — 320 drawers)
- wing_research/climate-co2: 47 drawers — CO2/temp correlations, NOAA, AIRS, sea ice
- wing_research/ocean-ph: 12 drawers — Acidification trends, pH timeline
- wing_people/alice: 8 drawers — Birthday, preferences, contact info, family
- wing_projects/astra-dev: 63 drawers — Integration decisions, experiment results

### Key KG Facts
- CO2_concentration → correlates_with → global_temperature (r=0.932, 2026-01-01+)
- alice → works_at → NewCorp (2026-03-15+)
- mdc_parameter → optimal_value → 5 (2026-04-11+)

### Recent Diary
- 2026-04-11: DC-27 validated 6/6. Stored in wing_research/hypothesis-results.
```

The MEMORY.md version takes ~6 lines. The palace version holds everything in full detail.
When you need Alice's kids' names, you search: `palace.search("alice children family")`.

### Index Entry Format

Keep index entries concise:

```
- wing_name/room-name: N drawers — one-line description of what's there
```

For KG: `entity → predicate → value (valid_from date+)`

For diary: `YYYY-MM-DD: one sentence summary`

---

## Anti-Patterns to Avoid

### ❌ Don't: Copy Palace Content into MEMORY.md

If you find something in the palace and copy it verbatim into MEMORY.md, you now have two
copies that can drift out of sync. Instead, write a one-line pointer and leave the content in
the palace where it can be found by semantic search.

### ❌ Don't: Use MEMORY.md for Facts That Change

Person's job title, project status, experiment results — these change. Tracking them only in
MEMORY.md means you lose the history. Use the KG's `valid_from`/`ended` fields instead.
MEMORY.md can hold "Alice → works_at → NewCorp (see alice KG entry for full history)".

### ❌ Don't: Ignore the Palace on Scheduled Runs

It's tempting to rely only on MEMORY.md since it's auto-loaded. But after many runs, your
MEMORY.md will lose old content (pushed past the 16KB cutoff). The palace retains everything.
On runs where you need historical context, always search.

### ❌ Don't: Store Temporal Facts Only in MEMORY.md

"Alice used to work at OldCorp" belongs in the palace KG, not MEMORY.md. The KG records
*when* facts were true. MEMORY.md only knows the current state. For anything time-sensitive,
palace KG is the right store.

### ❌ Don't: Let MEMORY.md Grow Without Pruning

When MEMORY.md grows past ~12KB, the oldest content falls below the auto-load threshold.
Periodically prune: move detailed content into the palace and replace with pointers. Run this
check periodically:

```bash
wc -c /workspace/MEMORY.md  # Should stay under ~14KB for comfortable auto-load
```

---

## Migration Guide: Moving MEMORY.md Content into the Palace

If your MEMORY.md has grown large with accumulated facts, here's how to migrate:

### Step 1: Identify What Should Move

Go through MEMORY.md and classify each section:
- **Stays in MEMORY.md**: Current goals, active tasks, session state, system config
- **Moves to palace**: Historical facts, people info, project history, past findings

### Step 2: Initialize the Palace

```bash
python3 /shared/mempalace-agi/integrations/mempalace-taurus/scripts/palace-helper.py \
  status --palace /workspace/palace
# If palace doesn't exist yet, it will be created on first store operation
```

### Step 3: Store Facts in the Palace

For each block of facts to migrate, store them in appropriate wings/rooms:

```python
python3 - <<'EOF'
import mempalace
palace = mempalace.Palace("/workspace/palace")

# People info
palace.add_drawer("people", "alice",
    "Alice: birthday April 3. Vegetarian. Prefers text over calls. "
    "Has labrador Biscuit. Kids: Sam (8), Jo (5). Contact: 9-11 AM Pacific.")

# KG for structured facts
palace.kg_add("alice", "works_at", "NewCorp", valid_from="2026-03-15")
palace.kg_add("alice", "birthday", "April 3")

# Past research findings
palace.add_drawer("research", "climate-co2",
    "CO2 r=0.932 correlation with global temperature. "
    "Mauna Loa NOAA, 2026-04-10. Also confirmed with AIRS satellite.")

print("Migrated.")
EOF
```

### Step 4: Replace with Pointers in MEMORY.md

Remove the migrated content from MEMORY.md and add a compact index entry:

```markdown
## Palace Index (/workspace/palace)
- wing_people/alice: Birthday, preferences, contact info, family, employment history
- wing_research/climate-co2: CO2 correlations, Mauna Loa data, AIRS confirmation
```

### What Always Stays in MEMORY.md

- `## Current Goals` and `## Active Tasks` — you need these instantly every run
- `## System Config` — paths, credentials, environment state
- `## Palace Index` — the pointers you just created
- `## Recent Actions` — last 2-3 things you did, for context across runs

---

*See also: `taurus-guide.md` | `../assets/memory-md-template.md`*
