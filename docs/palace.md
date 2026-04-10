---
layout: docs
title: The Palace
description: How MemPalace organizes memory. Wings, halls, rooms, closets, drawers — and why the structure boosts retrieval by 34%.
eyebrow: Core Concepts
heading: The Palace
subtitle: Ancient Greek orators memorized speeches by placing ideas in rooms of an imaginary building. MemPalace applies the same principle to AI memory.
prev:
  href: /quick-start
  label: Quick Start
next:
  href: /aaak
  label: AAAK Dialect
toc:
  - { id: idea,            label: The Idea }
  - { id: structure,       label: Structure }
  - { id: wings-rooms,     label: Wings and Rooms }
  - { id: halls,           label: Halls and Tunnels }
  - { id: closets-drawers, label: Closets and Drawers }
  - { id: why,             label: Why Structure Matters }
  - { id: memory-stack,    label: The Memory Stack }
---

## The Idea {#idea}

Every project, person, or topic you're filing gets its own **wing** in the
palace. Each wing has **rooms** — specific topics like auth, billing, or
deploy. Rooms contain **closets** (compressed summaries) that point to
**drawers** (the original verbatim content).

**Halls** connect related rooms within a wing. **Tunnels** connect rooms
across wings — so the same topic threads through your whole history.

No AI decides what matters. You keep every word. The structure does the
finding.

## Structure {#structure}

<div class="ascii">  ┌────────────────────────────────────────────────────────────┐
  │  WING: Person                                              │
  │                                                            │
  │    ┌──────────┐  ──hall──  ┌──────────┐                    │
  │    │  Room A  │            │  Room B  │                    │
  │    └────┬─────┘            └──────────┘                    │
  │         │                                                  │
  │         ▼                                                  │
  │    ┌──────────┐      ┌──────────┐                          │
  │    │  Closet  │ ───▶ │  Drawer  │                          │
  │    └──────────┘      └──────────┘                          │
  └─────────┼──────────────────────────────────────────────────┘
            │
          tunnel
            │
  ┌─────────┼──────────────────────────────────────────────────┐
  │  WING: Project                                             │
  │         │                                                  │
  │    ┌────┴─────┐  ──hall──  ┌──────────┐                    │
  │    │  Room A  │            │  Room C  │                    │
  │    └────┬─────┘            └──────────┘                    │
  │         │                                                  │
  │         ▼                                                  │
  │    ┌──────────┐      ┌──────────┐                          │
  │    │  Closet  │ ───▶ │  Drawer  │                          │
  │    └──────────┘      └──────────┘                          │
  └────────────────────────────────────────────────────────────┘</div>

## Wings and Rooms {#wings-rooms}

A **wing** is a person or project. You create as many as you need — one for
each teammate, one for each product, one for each client.

**Rooms** are named topics within a wing: `auth-migration`, `graphql-switch`,
`ci-pipeline`. MemPalace auto-detects rooms from file content using 70+
patterns, and you can create or rename them manually.

The same room can exist in different wings — and that's where the power
shows up.

## Halls and Tunnels {#halls}

### Halls — memory types

Halls are memory types that repeat in every wing, acting as corridors:

<div class="table-wrap" markdown="1">

| Hall                | What goes in it                      |
|---------------------|--------------------------------------|
| `hall_facts`        | Decisions made, choices locked in    |
| `hall_events`       | Sessions, milestones, debugging      |
| `hall_discoveries`  | Breakthroughs, new insights          |
| `hall_preferences`  | Habits, likes, opinions              |
| `hall_advice`       | Recommendations and solutions        |

</div>

### Tunnels — cross-wing links

When the same room appears in different wings, a **tunnel** is created
automatically:

```text
wing_kai       / hall_events / auth-migration  → "Kai debugged the OAuth token refresh"
wing_driftwood / hall_facts  / auth-migration  → "team decided to migrate auth to Clerk"
wing_priya     / hall_advice / auth-migration  → "Priya approved Clerk over Auth0"
```

Same room. Three wings. The tunnel connects them. A search for `auth-migration`
walks the tunnel and returns all three perspectives.

## Closets and Drawers {#closets-drawers}

**Closets** are compressed summaries that point to where the original content
lives. Fast for AI to read.

**Drawers** are the original verbatim files. The exact words, never summarized,
never paraphrased. When you search, closets help the AI find the right drawer
— and the AI gets the exact text.

This separation matters: closets are optimized for retrieval speed, drawers are
optimized for fidelity. You never lose information.

## Why Structure Matters {#why}

Tested on **22,000+ real conversation memories**:

<div class="table-wrap" markdown="1">

| Search strategy       | R@10      | Delta      |
|-----------------------|-----------|------------|
| Search all closets    | 60.9%     | —          |
| Search within wing    | 73.1%     | **+12%**   |
| Search wing + hall    | 84.8%     | **+24%**   |
| Search wing + room    | **94.8%** | **+34%**   |

</div>

> Wings and rooms aren't cosmetic. They're a **34% retrieval improvement** via wing+room metadata filtering — a standard ChromaDB feature applied to the palace structure. Real and useful, even if it's not a novel retrieval mechanism.
{: .callout .success}

## The Memory Stack {#memory-stack}

Your AI doesn't load everything at once. It loads a 4-layer stack:

<div class="table-wrap" markdown="1">

| Layer  | What                                                 | Size                  | When                   |
|--------|------------------------------------------------------|-----------------------|------------------------|
| **L0** | Identity — who is this AI?                           | ~50 tokens            | Always loaded          |
| **L1** | Critical facts — team, projects, preferences         | ~120 tokens (AAAK)    | Always loaded          |
| **L2** | Room recall — recent sessions, current project       | On demand             | When topic comes up    |
| **L3** | Deep search — semantic query across all closets      | On demand             | When explicitly asked  |

</div>

Your AI wakes up with **L0 + L1 (~170 tokens)** and knows your world. Searches
only fire when needed. See [AAAK]({{ '/aaak' | relative_url }}) for how L1
stays so small.
