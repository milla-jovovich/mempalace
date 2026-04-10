---
layout: docs
title: Quick Start
description: Install MemPalace, initialize your palace, mine your first data, and search it — all in four commands.
eyebrow: Getting Started
heading: Quick Start
subtitle: Four commands to a searchable memory. Everything stays on your machine.
prev:
  href: /intro
  label: Introduction
next:
  href: /palace
  label: The Palace
toc:
  - { id: install,  label: Install }
  - { id: init,     label: Initialize }
  - { id: mine,     label: Mine your data }
  - { id: search,   label: Search }
  - { id: wake-up,  label: Wake up your AI }
  - { id: next,     label: Next steps }
---

## Install {#install}

### Claude Code plugin (recommended)

```bash
claude plugin marketplace add milla-jovovich/mempalace
claude plugin install --scope user mempalace
```

Restart Claude Code, then type `/skills` to verify "mempalace" appears. This
gives you MCP tools, auto-save hooks, and slash commands out of the box.

### pip install

```bash
pip install mempalace
```

Or from source for development:

```bash
git clone https://github.com/milla-jovovich/mempalace.git
cd mempalace
pip install -e ".[dev]"
```

**Requirements:** Python 3.9+, `chromadb>=0.4.0`, `pyyaml>=6.0`. That's it. No
API key. No internet after install.

## Initialize {#init}

One-time setup — asks about the people and projects you work with, generates
the wing config, writes your identity file.

```bash
mempalace init ~/projects/myapp
```

Produces:

- `~/.mempalace/wing_config.json` — your people/project wings
- `~/.mempalace/identity.txt` — Layer 0 (always loaded by your AI)
- `~/.mempalace/palace/` — the ChromaDB vector store
- `~/.mempalace/knowledge_graph.db` — SQLite knowledge graph

## Mine your data {#mine}

Ingest files into the palace. Three modes:

```bash
# Projects — code, docs, notes
mempalace mine ~/projects/myapp

# Conversation exports — Claude, ChatGPT, Slack, plain text
mempalace mine ~/chats/ --mode convos

# Auto-classify into decisions, preferences, milestones, problems, emotional context
mempalace mine ~/chats/ --mode convos --extract general
```

The miner chunks by paragraph (projects) or by exchange pair (convos), detects
rooms from content, and stores everything as verbatim drawers.

> **Tip:** If you have transcript files that concatenate multiple sessions, run `mempalace split ~/chats/` first. See the [CLI reference]({{ '/cli#split' | relative_url }}) for options.
{: .callout}

## Search {#search}

Semantic search across everything you've ever filed:

```bash
# Global search
mempalace search "why did we switch to GraphQL"

# Filter by wing (+12% recall)
mempalace search "auth decisions" --wing driftwood

# Filter by room (+34% recall)
mempalace search "rate limiting" --room api-design
```

Results come back as verbatim drawer content with scores, wings, rooms, and
timestamps.

## Wake up your AI {#wake-up}

Load the critical facts layer (~170 tokens in AAAK) into your AI's context:

```bash
# Load your whole world
mempalace wake-up > context.txt

# Or project-specific
mempalace wake-up --wing driftwood > context.txt
```

Paste `context.txt` into your AI's system prompt. Now it knows your team, your
projects, your preferences, your decisions — all in ~170 tokens.

For Claude Code, Cursor, Gemini CLI, and other MCP-compatible tools, you
don't even need this — see [MCP Server]({{ '/mcp' | relative_url }}) for
the automatic flow.

## Next steps {#next}

- **Understand the structure** → [The Palace]({{ '/palace' | relative_url }})
- **Wire it into your AI** → [MCP Server]({{ '/mcp' | relative_url }})
- **Automate saving** → [Auto-Save Hooks]({{ '/hooks' | relative_url }})
- **See every command** → [CLI Reference]({{ '/cli' | relative_url }})
