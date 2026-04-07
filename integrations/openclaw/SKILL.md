---
name: mempalace
description: Local AI memory system — mine conversations and docs, search everything you've ever discussed. 96.6% recall, zero API calls, runs entirely on your machine.
homepage: https://github.com/milla-jovovich/mempalace
author: GraceClaw (akadan18)
metadata:
  {
    "openclaw":
      {
        "emoji": "🏛️",
        "requires": { "bins": ["mempalace"] },
        "install":
          [
            {
              "id": "pip",
              "kind": "exec",
              "command": "pip install mempalace",
              "bins": ["mempalace"],
              "label": "Install mempalace (pip)",
            },
          ],
      },
  }
---

# mempalace

Local-only AI memory. Mine your conversations (Claude exports, ChatGPT, Slack), projects (code + docs), and context. Search anything you've ever discussed. Zero cloud calls.

## Setup (once)

```bash
pip install mempalace

# Initialize a palace (one per project or use a shared one)
mempalace init ~/.mempalace/main

# Mine conversation exports
mempalace mine ~/chats/ --mode convos

# Mine a project's code + docs
mempalace mine ~/projects/myapp

# Auto-classify into decisions, preferences, milestones, problems
mempalace mine ~/chats/ --mode convos --extract general
```

## Common commands

- Search: `mempalace search "why did we switch to X"`
- Status: `mempalace status`
- Wake-up (context summary): `mempalace wake-up`
- Wake-up (AAAK compressed, ~170 tokens): `mempalace wake-up --aaak`
- Add a single memory: `mempalace add "decided to use Postgres because of JSONB support" --type decision`

## MCP server (for Claude Code / Claude Desktop)

```bash
# Register once
claude mcp add mempalace -- python -m mempalace.mcp_server

# Gives you 19 MCP tools including:
# mempalace_search — search all memories
# mempalace_add — add a new memory
# mempalace_wake_up — load compressed context summary
# mempalace_status — palace health check
```

## Mining modes

- `--mode projects` (default) — code, docs, notes
- `--mode convos` — conversation exports (Claude, ChatGPT, Slack JSON exports)
- `--mode convos --extract general` — auto-classifies into: decisions, preferences, milestones, problems, emotional context

## AAAK compression

MemPalace uses AAAK — a lossless shorthand for AI agents. Compresses your entire palace to ~120-170 tokens for loading into system prompts or local models that don't support MCP.

```bash
# Load compressed context before any session
mempalace wake-up --aaak >> /tmp/context.txt
```

## Notes

- Palace is stored at `~/.mempalace/` by default
- All data stays local — no API keys, no cloud
- Works with any model that reads text (via CLI or MCP)
- Re-mine after major new conversations to stay current: `mempalace mine ~/chats/ --mode convos`

---

_Skill by [GraceClaw](https://github.com/akadan18/graceclaw) — Personal Agentic AI OS built on OpenClaw_
