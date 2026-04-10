---
layout: docs
title: Gemini CLI
description: Set up MemPalace as permanent memory for Gemini CLI with MCP and auto-save hooks.
eyebrow: Integrations
heading: Gemini CLI Integration
subtitle: MemPalace works natively with Gemini CLI. MCP server for tools, PreCompress hook for auto-saving.
prev:
  href: /agents
  label: Specialist Agents
next:
  href: /cli
  label: CLI Commands
toc:
  - { id: prereqs,  label: Prerequisites }
  - { id: install,  label: Installation }
  - { id: init,     label: Initialization }
  - { id: mcp,      label: Connect via MCP }
  - { id: hooks,    label: Auto-Save Hooks }
  - { id: usage,    label: Usage }
---

## Prerequisites {#prereqs}

- Python 3.9+
- [Gemini CLI](https://github.com/google/gemini-cli) installed and configured

## Installation {#install}

We recommend using a virtual environment within the MemPalace directory:

```bash
git clone https://github.com/milla-jovovich/mempalace.git
cd mempalace

python3 -m venv .venv
.venv/bin/pip install -e .
```

## Initialization {#init}

Set up your palace and configure your identity:

```bash
.venv/bin/python3 -m mempalace init .
```

Optionally edit `~/.mempalace/identity.txt` (your role and focus) and
`~/.mempalace/wing_config.json` (projects and name variants mapped to wings).

## Connect via MCP {#mcp}

Register MemPalace as an MCP server so Gemini CLI can use its tools:

```bash
gemini mcp add mempalace /absolute/path/to/mempalace/.venv/bin/python3 -m mempalace.mcp_server --scope user
```

> **Use the absolute path** to the virtual environment Python binary so it works from any directory.
{: .callout}

## Auto-Save Hooks {#hooks}

Add a `PreCompress` hook to `~/.gemini/settings.json` so Gemini CLI
auto-saves memories before context compression:

```json
{
  "hooks": {
    "PreCompress": [{
      "matcher": "*",
      "hooks": [{
        "type": "command",
        "command": "/absolute/path/to/mempalace/hooks/mempal_precompact_hook.sh"
      }]
    }]
  }
}
```

Make sure the hook scripts are executable:

```bash
chmod +x hooks/*.sh
```

## Usage {#usage}

Once connected, Gemini CLI will automatically:

- Start the MemPalace server on launch
- Use `mempalace_search` to find relevant past discussions
- Use the `PreCompress` hook to save new memories before they are lost

### Verification

In a Gemini CLI session:

- `/mcp list` — verify `mempalace` is `CONNECTED`
- `/hooks panel` — verify the `PreCompress` hook is active

### Manual mining

If you want to ingest existing code or docs immediately:

```bash
.venv/bin/python3 -m mempalace mine /path/to/your/project
```
