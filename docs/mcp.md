---
layout: docs
title: MCP Server
description: 19 tools that expose the MemPalace palace, knowledge graph, and agent diary to any MCP-compatible AI.
eyebrow: Integrations
heading: MCP Server
subtitle: Connect MemPalace to Claude Code, Claude Desktop, Cursor, Gemini CLI, and any other MCP-compatible tool. 19 tools, zero configuration.
prev:
  href: /knowledge-graph
  label: Knowledge Graph
next:
  href: /hooks
  label: Auto-Save Hooks
toc:
  - { id: install,    label: Install }
  - { id: how,        label: How it works }
  - { id: read,       label: Palace — Read }
  - { id: write,      label: Palace — Write }
  - { id: kg,         label: Knowledge Graph }
  - { id: nav,        label: Navigation }
  - { id: diary,      label: Agent Diary }
---

## Install {#install}

### Claude Code (recommended)

**Via plugin (recommended):**

```bash
claude plugin marketplace add milla-jovovich/mempalace
claude plugin install --scope user mempalace
```

Restart Claude Code, then type `/skills` to verify "mempalace" appears.

**Or manually:**

```bash
claude mcp add mempalace -- python -m mempalace.mcp_server
```

You can also run `mempalace mcp` to see the setup command.

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mempalace": {
      "command": "python",
      "args": ["-m", "mempalace.mcp_server"]
    }
  }
}
```

### Gemini CLI

MemPalace works natively with Gemini CLI, which handles the MCP server and
save hooks automatically:

```bash
gemini mcp add mempalace /path/to/venv/bin/python3 -m mempalace.mcp_server --scope user
```

See the full [Gemini CLI Integration Guide]({{ site.github_url }}/blob/main/examples/gemini_cli_setup.md)
for virtual environment setup, hooks configuration, and verification steps.

### Cursor / other MCP clients

Any client that speaks the Model Context Protocol can connect. Point it at
`python -m mempalace.mcp_server` as the command.

## How it works {#how}

On first tool call, the MCP server sends a bootstrap that teaches the AI:

1. The **AAAK dialect** grammar
2. The **Palace Protocol** — how to file and retrieve memories
3. The **current critical facts** (L1 layer)

From that point on, your AI discovers tools, files memories, and retrieves
them without any prompt engineering on your side.

> **Zero configuration required.** You never edit a CLAUDE.md or tweak a system prompt. The server teaches the AI what it needs.
{: .callout}

## Palace — Read {#read}

<div class="table-wrap" markdown="1">

| Tool                          | What                                            |
|-------------------------------|-------------------------------------------------|
| `mempalace_status`            | Palace overview + AAAK spec + memory protocol   |
| `mempalace_list_wings`        | Wings with counts                               |
| `mempalace_list_rooms`        | Rooms within a wing                             |
| `mempalace_get_taxonomy`      | Full wing → room → count tree                   |
| `mempalace_search`            | Semantic search with wing/room filters          |
| `mempalace_check_duplicate`   | Check before filing                             |
| `mempalace_get_aaak_spec`     | AAAK dialect reference                          |

</div>

`mempalace_search` is the one you'll see called most. It accepts a `query`,
optional `wing`, optional `room`, and optional `limit`, and returns verbatim
drawers with scores and locations.

## Palace — Write {#write}

<div class="table-wrap" markdown="1">

| Tool                         | What                    |
|------------------------------|-------------------------|
| `mempalace_add_drawer`       | File verbatim content   |
| `mempalace_delete_drawer`    | Remove by ID            |

</div>

Write tools are intentionally minimal. The AI files verbatim content — it
doesn't summarize, doesn't paraphrase, doesn't decide what matters. The
palace structure does the organizing; the AI's job is just to put the content
in the right wing/room.

## Knowledge Graph {#kg}

<div class="table-wrap" markdown="1">

| Tool                         | What                                        |
|------------------------------|---------------------------------------------|
| `mempalace_kg_query`         | Entity relationships with time filtering    |
| `mempalace_kg_add`           | Add facts                                   |
| `mempalace_kg_invalidate`    | Mark facts as ended                         |
| `mempalace_kg_timeline`      | Chronological entity story                  |
| `mempalace_kg_stats`         | Graph overview                              |

</div>

These map 1:1 to the Python API documented in
[Knowledge Graph]({{ '/knowledge-graph' | relative_url }}). Your AI can
query "what was true in January?" and get a time-anchored answer.

## Navigation {#nav}

<div class="table-wrap" markdown="1">

| Tool                         | What                                        |
|------------------------------|---------------------------------------------|
| `mempalace_traverse`         | Walk the graph from a room across wings     |
| `mempalace_find_tunnels`     | Find rooms bridging two wings               |
| `mempalace_graph_stats`      | Graph connectivity overview                 |

</div>

Navigation tools let the AI follow tunnels between wings without re-running
searches. Useful for "show me everything related to this auth decision across
all projects" — one call returns the whole thread.

## Agent Diary {#diary}

<div class="table-wrap" markdown="1">

| Tool                         | What                           |
|------------------------------|--------------------------------|
| `mempalace_diary_write`      | Write AAAK diary entry         |
| `mempalace_diary_read`       | Read recent diary entries      |

</div>

Specialist agents (see [Agents]({{ '/agents' | relative_url }})) use
these to persist their own expertise across sessions. Each agent writes to
its own diary in AAAK and reads back its history before starting a new task.
