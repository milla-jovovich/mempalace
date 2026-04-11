# MemPalace Section — MEMORY.md Template

Add this section to your `/workspace/MEMORY.md` to integrate MemPalace.
Replace all `[bracketed]` placeholders with your actual values.
Keep this section under ~2KB so it fits comfortably within the 16KB auto-load limit.

---

```markdown
## Palace Memory

### Location & Status
- **Path**: [/workspace/palace OR /shared/palace]
- **Type**: [private | shared team palace]
- **Total drawers**: ~[N]  |  Wings: [N]  |  KG triples: [N]
- **Last updated**: [YYYY-MM-DDTHH:MMZ]

### Wing Index
| Wing | Drawers | Contains |
|------|:-------:|---------|
| wing_[name] | ~[N] | [one-line description] |
| wing_[name] | ~[N] | [one-line description] |
| wing_[discoveries] | ~[N] | [shared/team knowledge] |

### Key Entities (KG Quick Reference)
- `[entity]` → [predicate] → `[value]`  (valid [date]+)
- `[entity]` → [predicate] → `[value]`  (valid [date]+)
- `[entity]` → [predicate] → `[value]`  (valid [date]+)

### Recent Diary Entries
- [YYYY-MM-DD]: [one-sentence summary of what was stored/accomplished]
- [YYYY-MM-DD]: [one-sentence summary]

### Reconnect Queries (use these after compaction to restore context)
- "[semantic phrase]" → [wing/room]
- "[semantic phrase]" → [wing/room]
```

---

## Filled Example — Research Agent

```markdown
## Palace Memory

### Location & Status
- **Path**: /shared/palace
- **Type**: shared team palace (engineer + researcher + writer)
- **Total drawers**: ~420  |  Wings: 6  |  KG triples: 1,019
- **Last updated**: 2026-04-11T01:45Z

### Wing Index
| Wing | Drawers | Contains |
|------|:-------:|---------|
| wing_researcher | 121 | Hypotheses, experiment designs, literature summaries |
| wing_discoveries | 147 | Breakthrough findings (all agents), validated results |
| wing_engineer | 83 | Code decisions, implementation notes, benchmarks |
| wing_writer | 38 | Document drafts, published doc summaries |
| wing_project | 42 | Integration decisions, status, architecture record |
| wing_scout | 31 | Repo intel, PR reviews, ecosystem intelligence |

### Key Entities (KG Quick Reference)
- `CO2_concentration` → correlates_with → `global_temperature` (2026-01-01+)
- `mdc_parameter` → optimal_value → `5` (2026-04-11+)
- `MemPalace` → current_version → `v4.0-lancedb` (2026-04-11+)
- `novelty_uplift` → measured_value → `1.83×` (2026-04-10, DC-24)

### Recent Diary Entries
- 2026-04-11: DC-27 validated 6/6 pass; mdc=5 confirmed → wing_discoveries/experiments
- 2026-04-10: DC-24 breakthrough 1.83× uplift stored → wing_discoveries/breakthroughs
- 2026-04-10: Phase 15 deep saturation complete; 185 total discoveries logged

### Reconnect Queries (use after compaction)
- "discovery experiment validation results" → wing_discoveries/experiments
- "mdc parameter compute savings" → wing_researcher/experiment-design
- "novelty uplift memory augmentation" → wing_discoveries/breakthroughs
- "ASTRA integration decisions" → wing_project/decisions
```

---

## Notes on Keeping This Section Healthy

- **Update drawer counts** every few runs (or when counts change significantly)
- **Add new KG entries** when important new facts are established
- **Rotate diary entries** — keep only the last 3–5; older ones are in the palace diary
- **Add reconnect queries** for any major new topic you store in the palace
- **Don't copy palace content here** — this is an index, not an archive
- **Prune when this section exceeds ~1.5KB** — move old entries into a palace room instead

Check section size: `grep -A 50 "## Palace Memory" /workspace/MEMORY.md | wc -c`
Should stay under ~1,500 bytes for a comfortable index.
