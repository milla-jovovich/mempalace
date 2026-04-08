---
name: mempalace-memory
description: >
  Use when working with project memory: recalling past decisions,
  storing architectural choices, searching prior context, or when
  user says "remember this", "what did we decide", or "recall".
compatibility: >
  Requires MemPalace MCP server running locally (mempalace mcp).
  Configure in ~/.config/mcp/servers.json or IDE-specific MCP config.
  All tools use prefix mcp_mempalace_.
metadata:
  version: "1.0"
  author: community
---

# MemPalace Memory Protocol

## 0. Session Start
At the start of every session, call `mcp_mempalace_mempalace_status`
before answering memory-dependent questions.
Do not assume prior project state from the current chat alone.
This loads L0/L1 state (~170 tokens), which is often enough.

## 1. Retrieval First — Lazy & Scoped
Never guess about project history, prior decisions, user preferences,
architecture, ownership, or configuration.

Proceed progressively:
1. `mcp_mempalace_mempalace_status` (L0/L1 context)
2. `mcp_mempalace_mempalace_kg_query` or
   `mcp_mempalace_mempalace_diary_read` for facts and chronology
3. Only if still lacking: `mcp_mempalace_mempalace_search` for
   rich semantic context in Drawers

Always filter by `wing`, `room`, or `hall` when known.
Widen scope only if results are missing or conflicting.

## 2. Structural Hierarchy
- Wing: top-level container for a project, domain, or person.
  Create the wing before setting up rooms.
- Room: sub-domain within a wing (e.g. `auth`, `backend`).
- Closet: AAAK-compressed summaries — short, fast context.
- Drawer: raw verbatim text, code, logs — deep retrieval only.

## 3. Write Routing
If the user says "remember this", "important", or "use this later" —
save it as the first action.

Before adding large items:
mcp_mempalace_mempalace_check_duplicate

What to store and where:
- Verbatim code, configs, bug post-mortems, architecture notes → mcp_mempalace_mempalace_add_drawer
- Durable facts and entity relations (A uses B, X owns Y) → mcp_mempalace_mempalace_kg_add
- Session events, decisions, milestones in AAAK format → mcp_mempalace_mempalace_diary_write

## 4. Noise Filter
Do NOT store: chain-of-thought, debug noise, one-off clarifications,
transient scripts, or anything with no likely future value.

## 5. Canonical Taxonomy (Cross-Client)
MemPalace is shared across Antigravity, Claude Code, Cursor, and
ChatGPT Desktop. Do not invent local naming conventions.

Standard rooms for technical projects:
architecture backend frontend database infra deploy
auth integrations testing bugs product users team-process

Do not use synonyms when a canonical room already exists.

## 6. Halls Discipline
- hall_facts — durable truths and system states
- hall_events — incidents, decisions, state changes
- hall_discoveries — learned lessons, root causes
- hall_preferences — recurring user or team preferences
- hall_advice — reusable best practices and recommendations

## 7. Temporal Fact Safety
Never silently overwrite an outdated fact.

When a fact stops being true:
1. mcp_mempalace_mempalace_kg_invalidate (set ended date)
2. mcp_mempalace_mempalace_kg_add (add the new truth)

Use valid_from only when start-time is known and meaningful.

## 8. AAAK Compression
For diary/closet entries, always include five blocks:
Entity | State/Fact | Action/Decision | Rationale | Time
Entry must remain self-decodable by a future agent without context.

Example:
PROJ_N8N | pagination_bug | switched_node_reference_to_absolute | intermediate_nodes_lost_data | 2026-03-26

## 9. Spec Before Improvisation
If AAAK format, taxonomy, or room placement is unclear:
- mcp_mempalace_mempalace_get_aaak_spec
- mcp_mempalace_mempalace_get_taxonomy

Consistency beats cleverness. Never invent a local convention
when the palace has a canonical answer.
