---
layout: docs
title: Auto-Save Hooks
description: Automatic memory save for Claude Code and Codex CLI. No manual save commands.
eyebrow: Integrations
heading: Auto-Save Hooks
subtitle: Two hooks that automatically save memories during work. The AI knows what to save — the hooks just tell it when.
prev:
  href: /mcp
  label: MCP Server
next:
  href: /agents
  label: Specialist Agents
toc:
  - { id: what,           label: What they do }
  - { id: claude-code,    label: Claude Code }
  - { id: codex,          label: Codex CLI }
  - { id: how,            label: How the save hook works }
  - { id: config,         label: Configuration }
  - { id: debugging,      label: Debugging }
---

## What they do {#what}

<div class="table-wrap" markdown="1">

| Hook                | When it fires                   | What happens                                                                        |
|---------------------|---------------------------------|-------------------------------------------------------------------------------------|
| **Save Hook**       | Every 15 human messages         | Blocks the AI, tells it to save key topics/decisions/quotes to the palace           |
| **PreCompact Hook** | Right before context compaction | Emergency save — forces the AI to save _everything_ before losing context           |

</div>

The AI does the actual filing — it knows the conversation context, so it
classifies memories into the right wings/halls/closets. The hooks just tell it
_when_ to save.

> **Cost: zero extra tokens.** The hooks are bash scripts that run locally. They don't call any API. The only "cost" is the AI spending a few seconds organizing memories at each checkpoint.
{: .callout .success}

## Claude Code {#claude-code}

Add to `.claude/settings.local.json`:

```json
{
  "hooks": {
    "Stop": [{
      "matcher": "*",
      "hooks": [{
        "type": "command",
        "command": "/absolute/path/to/hooks/mempal_save_hook.sh",
        "timeout": 30
      }]
    }],
    "PreCompact": [{
      "hooks": [{
        "type": "command",
        "command": "/absolute/path/to/hooks/mempal_precompact_hook.sh",
        "timeout": 30
      }]
    }]
  }
}
```

Then make them executable:

```bash
chmod +x hooks/mempal_save_hook.sh hooks/mempal_precompact_hook.sh
```

## Codex CLI {#codex}

Add to `.codex/hooks.json`:

```json
{
  "Stop": [{
    "type": "command",
    "command": "/absolute/path/to/hooks/mempal_save_hook.sh",
    "timeout": 30
  }],
  "PreCompact": [{
    "type": "command",
    "command": "/absolute/path/to/hooks/mempal_precompact_hook.sh",
    "timeout": 30
  }]
}
```

## How the save hook works {#how}

<div class="ascii">User sends message → AI responds → Claude Code fires Stop hook
                                            ↓
                                    Hook counts human messages
                                            ↓
                              ┌─── < 15 since last save ──→ echo "{}" (let AI stop)
                              │
                              └─── ≥ 15 since last save ──→ {"decision": "block"}
                                                                    ↓
                                                            AI saves to palace
                                                                    ↓
                                                            AI tries to stop again
                                                                    ↓
                                                            stop_hook_active = true
                                                                    ↓
                                                            Hook sees flag → {} (through)</div>

The `stop_hook_active` flag prevents infinite loops: block once → AI saves →
tries to stop → flag is true → we let it through.

The PreCompact hook is simpler: it always blocks, forces a save, and lets
compaction proceed.

## Configuration {#config}

Edit `hooks/mempal_save_hook.sh` to change:

<div class="table-wrap" markdown="1">

| Variable          | What                                                                    |
|-------------------|-------------------------------------------------------------------------|
| `SAVE_INTERVAL=15`| Human messages between saves. Lower = more saves.                       |
| `STATE_DIR`       | Where hook state is stored. Defaults to `~/.mempalace/hook_state/`.     |
| `MEMPAL_DIR`      | Optional. Auto-run `mempalace mine <dir>` on each save trigger.         |

</div>

The hooks resolve the repo root automatically from their own path, so they
work regardless of where you install the repo.

## Debugging {#debugging}

Check the hook log:

```bash
cat ~/.mempalace/hook_state/hook.log
```

Example output:

```text
[14:30:15] Session abc123: 12 exchanges, 12 since last save
[14:35:22] Session abc123: 15 exchanges, 15 since last save
[14:35:22] TRIGGERING SAVE at exchange 15
[14:40:01] Session abc123: 18 exchanges, 3 since last save
```

If saves aren't happening: verify the hook path is absolute, check file
permissions, and make sure the MCP server is running so the AI can actually
call `mempalace_add_drawer`.
