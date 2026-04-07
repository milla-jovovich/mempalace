# Agent Setup Guide

> **For AI agents:** If you are reading this file, follow the instructions below. All commands are designed to run without interactive prompts.

## TL;DR — One Line

```bash
mempalace agent-setup /path/to/your/data
```

This single command runs the full pipeline non-interactively:
1. Scans for entities (people, projects) — auto-accepts all
2. Detects room structure from your folder layout
3. Auto-detects content type (projects vs conversations)
4. Mines the content into the palace
5. Verifies the setup

Zero prompts. Zero ambiguity. Exit code 0 = success.

## Prerequisites

- Python 3.9+ already installed
- `pip` available
- Target directory with data (code, docs, conversation exports, or both)

## Install

```bash
pip install mempalace
```

## Setup — Three Levels of Detail

### Level 1: One-Shot (Recommended for Agents)

```bash
mempalace agent-setup /path/to/data
```

Optional flags:
- `--wing <name>` — override the wing name (default: directory name)
- `--agent <name>` — your identifier, recorded on every memory drawer (default: `mempalace`)
- `--limit <n>` — cap the number of files/convos to process (default: 0 = all)
- `--palace /custom/path` — non-standard palace location

### Level 2: Step-by-Step (Agent Control)

If you need more control over each phase:

```bash
# Phase 1: Initialize (non-interactive)
mempalace init /path/to/data --yes

# Phase 2: Mine with auto-detection
mempalace mine /path/to/data --auto

# Phase 3: Verify
mempalace status
mempalace search "any term from the source data"
```

### Level 3: Full Manual (Legacy)

```bash
# Init with entity auto-accept
mempalace init /path/to/data --yes

# Mine manually — pick the mode yourself:
mempalace mine /path/to/data                    # code, docs, notes
mempalace mine /path/to/data --mode convos      # chat exports
mempalace mine /path/to/data --mode convos --extract general  # 5-type classification

# Verify
mempalace status
```

## Environment Variables

| Variable | Purpose | Values |
|----------|---------|--------|
| `MEMPALACE_NONINTERACTIVE` | Kill switch for ALL interactive prompts | `1`, `true`, `yes` (case-insensitive) |
| `MEMPALACE_PALACE_PATH` | Override palace data directory | Any absolute path |

Example:

```bash
MEMPALACE_NONINTERACTIVE=1 MEMPALACE_PALACE_PATH=/mnt/data/palace mempalace init ~/project
```

These work on every command, not just `agent-setup`.

## Mining Auto-Detection Logic

When you use `--auto` or `agent-setup`, the system inspects the target directory:

1. Scans up to 30 files with extensions `.txt`, `.md`, `.json`, `.jsonl`
2. Reads the first 8KB of each file
3. Checks for conversation indicators:

| Indicator | Matches |
|-----------|---------|
| `> ` (blockquote) x3+ | Claude, ChatGPT, transcript exports |
| `You:` + `Assistant:` or `User:` | Generic chat format |
| `"user":` + `"type":` (JSON) | Slack/WhatsApp exports |
| `[Human:` or `[User:` | Tagged dialogue |
| `"role":` + `"user"`/`"assistant"` | OpenAI API JSON format |

4. If >50% of scanned files match any indicator → `convos` mode
5. Otherwise → `projects` mode

## Flags Reference

| Flag | Command | Effect |
|------|---------|--------|
| `--yes` | `init` | Auto-accept all detected entities without prompting |
| `--mode auto` | `mine` | Auto-detect content type and select mining mode |
| `--mode projects` | `mine` | Force project mining (code, docs, notes) |
| `--mode convos` | `mine` | Force conversation mining (chat exports) |
| `--extract exchange` | `mine --mode convos` | One chunk per Q+A exchange (default) |
| `--extract general` | `mine --mode convos` | Classify into 5 memory types: decisions, preferences, milestones, problems, emotional context |
| `--dry-run` | `mine` | Preview what will be filed without writing |
| `--wing <name>` | `init`, `mine`, `agent-setup` | Override auto-detected wing name |
| `--palace /path` | All commands | Custom palace location |
| `--limit <n>` | `mine`, `agent-setup` | Max files/convos to process (0 = all) |

## After Setup — Using the Palace

### Via MCP (Recommended for Claude, Cursor, etc.)

```bash
claude mcp add mempalace -- python -m mempalace.mcp_server
```

Your AI agent now has 19 memory tools available. No manual CLI calls needed.

### Via CLI (Any AI)

```bash
# Search
mempalace search "why did we switch to GraphQL"
mempalace search "pricing decision" --wing my_app --room costs

# Wake-up context (~170 tokens for local models)
mempalace wake-up > context.txt

# Status
mempalace status
```

### Via Python API

```python
from mempalace.searcher import search_memories

results = search_memories("auth decisions", palace_path="~/.mempalace/palace")
# Inject results into your model's context
```

## Verification Checklist

After setup, confirm:

- [ ] `mempalace status` shows non-zero filing count
- [ ] `mempalace search "<term from source data>"` returns results
- [ ] Palace directory exists at `~/.mempalace/palace` (or custom `--palace` path)
- [ ] Exit code was 0

## Troubleshooting

**"No palace found"** — Run `mempalace agent-setup <dir>` or `mempalace init <dir> --yes` first.

**No search results** — Ensure the directory was mined: check `mempalace status` shows files filed.

**Wrong content type detected** — Override with `--mode projects` or `--mode convos`.

**Interactive prompt still appeared** — Set `MEMPALACE_NONINTERACTIVE=1` in the environment before running.

**`agent-setup` not found** — Upgrade to the version that includes this command, or use Level 2 step-by-step above.
