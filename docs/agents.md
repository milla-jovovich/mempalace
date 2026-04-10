---
layout: docs
title: Specialist Agents
description: Focused agents with their own wings and diaries. Each one builds expertise in a specific domain over time.
eyebrow: Integrations
heading: Specialist Agents
subtitle: Create agents that focus on specific areas. Each agent gets its own wing and diary in the palace — not in your CLAUDE.md.
prev:
  href: /hooks
  label: Auto-Save Hooks
next:
  href: /gemini
  label: Gemini CLI
toc:
  - { id: idea,          label: The Idea }
  - { id: structure,     label: Structure }
  - { id: how-it-works,  label: How it works }
  - { id: example,       label: Example — Reviewer Agent }
  - { id: vs-letta,      label: vs Letta }
---

## The Idea {#idea}

Each agent is a specialist lens on your data:

- The **reviewer** remembers every bug pattern it's seen
- The **architect** remembers every design decision
- The **ops** agent remembers every incident

They don't share a scratchpad — they each maintain their own memory. Add 50
agents, your CLAUDE.md stays the same size, because the agents live in the
palace, not in your config.

## Structure {#structure}

```text
~/.mempalace/agents/
  ├── reviewer.json       # code quality, patterns, bugs
  ├── architect.json      # design decisions, tradeoffs
  └── ops.json            # deploys, incidents, infra
```

Each file defines:

- **Focus** — what the agent pays attention to
- **Wing** — which wing of the palace the agent owns
- **Diary path** — where its AAAK-compressed history lives

Your CLAUDE.md just needs one line:

```text
You have MemPalace agents. Run mempalace_list_agents to see them.
```

The AI discovers its agents from the palace at runtime.

## How it works {#how-it-works}

Each agent:

- **Has a focus** — what it pays attention to
- **Keeps a diary** — written in AAAK, persists across sessions
- **Builds expertise** — reads its own history to stay sharp in its domain

Diaries are stored in the agent's wing and written in AAAK for compact storage
and fast reading. A single session might be 5 tokens of AAAK:

```text
PR#42|auth.bypass.found|missing.middleware.check|pattern:3rd.time.this.quarter|★★★★
```

Readable in milliseconds. Compressed to a fraction of the original text using
AAAK's lossy abbreviation — key entities and patterns are preserved, though
some fidelity is traded for token density.

## Example — Reviewer Agent {#example}

```python
# Agent writes to its diary after a code review
mempalace_diary_write("reviewer",
    "PR#42|auth.bypass.found|missing.middleware.check|pattern:3rd.time.this.quarter|★★★★")

# Later, before starting a new review
mempalace_diary_read("reviewer", last_n=10)
# → last 10 findings, compressed in AAAK
```

The reviewer agent pulls its last 10 findings before starting each new review.
Because it's seen this auth pattern three times this quarter, it catches it on
the first pass instead of the fifth.

Over time, the reviewer accumulates a private expertise your main AI
conversation doesn't clutter with. Same for the architect, ops, security, or
any other lens you create.

## vs Letta {#vs-letta}

Letta charges **$20–200/month** for agent-managed memory. MemPalace does it
with a wing and a diary — for free, running entirely on your machine.

<div class="table-wrap" markdown="1">

| Feature                   | MemPalace Agents | Letta           |
|---------------------------|------------------|-----------------|
| Cost                      | **Free**         | $20–200/mo      |
| Storage                   | Local (SQLite)   | Cloud           |
| Multi-agent support       | Unlimited        | Tier-limited    |
| Custom wings per agent    | Yes              | Varies          |
| AAAK diary compression    | Yes              | No              |
| Self-hosted               | Always           | Enterprise only |

</div>

See [MCP Server → Agent Diary]({{ '/mcp#diary' | relative_url }}) for the
tool reference.
