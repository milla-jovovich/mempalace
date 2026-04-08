# mempalace-memory skill

A behavioral protocol for AI agents using MemPalace MCP.
Drops into any MCP-compatible IDE to enforce proper retrieval,
write routing, and temporal fact safety.

**Full repo:** https://github.com/Andzdes/mempalace-skill

## Install

```bash
# Claude Code
cp -r mempalace-memory/ ~/.claude/skills/mempalace-memory/

# Antigravity
cp -r mempalace-memory/ ~/.gemini/skills/mempalace-memory/

# Cursor / OpenCode
cp -r mempalace-memory/ .cursor/skills/mempalace-memory/
```

## What it does

Enforces 9 behavioral rules:
1. Session Start — call `mempalace_status` before answering
2. Retrieval First — never guess; check palace progressively
3. Structural Hierarchy — Wing → Room → Closet → Drawer
4. Write Routing — verbatim / KG / diary decision tree
5. Noise Filter — skip chain-of-thought and debug output
6. Canonical Taxonomy — shared room names across all clients
7. Halls Discipline — facts / events / discoveries / preferences / advice
8. Temporal Fact Safety — invalidate → add, never silent overwrite
9. Spec Before Improvisation — check AAAK spec when unsure

## Compatible with
Antigravity · Claude Code · Cursor · OpenCode
