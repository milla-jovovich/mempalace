# MemPalace Hooks — Auto-Save for Terminal AI Tools

These hook scripts make MemPalace save automatically. No manual "save" commands needed.

## What They Do

| Hook | When It Fires | What Happens |
|------|--------------|-------------|
| **Save Hook** | Every 15 human messages | Saves a diary entry with theme extraction, auto-mines transcript into the palace |
| **PreCompact Hook** | Right before context compaction | Emergency save — diary entry + transcript mining before context is lost |

## Save Architecture

Hooks have two **save modes**, controlled by `hook_silent_save` in `~/.mempalace/config.json`:

| Mode | Config | How It Saves | AAAK? | Deterministic? |
|------|--------|-------------|-------|----------------|
| **Silent** (default) | `hook_silent_save: true` | Direct Python API call — `tool_diary_write()` with plain text, no AI involved | No — plain English | Yes — save always happens |
| **Block** (legacy) | `hook_silent_save: false` | Blocks the AI, shows a reason message, asks AI to call MCP tools | Maybe — AI sees AAAK in MCP tool descriptions and may use it | No — AI may ignore, summarize, or fail |

**Silent mode is recommended.** It calls `tool_diary_write()` directly via Python import — no MCP roundtrip, no blocking, no AI interpretation needed. The save marker only advances after a confirmed write, so data loss is impossible. A one-line terminal notification (`"✦ N memories woven into the palace — themes"`) confirms each save.

**Block mode is the upstream default.** It returns `{"decision": "block", "reason": "..."}` asking the AI to call MemPalace MCP tools. This path is non-deterministic — the AI may ignore the instruction, summarize instead of quoting verbatim, or write to the wrong memory system. The save marker advances before the AI acts, so if the save fails, the checkpoint is silently lost.

Both modes also **auto-mine the JSONL transcript** directly into the palace, capturing raw tool output (Bash results, search findings, build errors) that the AI would otherwise summarize away. This is belt-and-suspenders — tool output is stored regardless of which save mode is active.

### AAAK and Save Paths

AAAK is upstream's compressed symbolic summary format (`mempalace/dialect.py`). It is **not a code feature** — it's a prompt embedded in MCP tool descriptions that coaches the AI to write diary entries in a shorthand notation.

- **Silent mode**: No AI reads the MCP tool descriptions. Diary entries are plain English. AAAK is irrelevant.
- **Block mode**: The AI sees `diary_write`'s tool description ("write in AAAK format"). It may produce AAAK-formatted entries. The `tool_diary_write()` function accepts any string — it doesn't validate or enforce AAAK.

### Tandem Memory Systems

Claude Code has its own auto-memory system (`~/.claude/projects/*/memory/*.md`) alongside MemPalace. Both are useful:

- **Auto-memory**: Lightweight preferences, context, feedback
- **MemPalace**: Verbatim conversations, tool output, code — deep searchable history

The hook block reasons say "For THIS save, use MemPalace MCP tools only" — scoped to the hook save event, not a permanent ban on auto-memory. Both systems are used in tandem during normal conversation.

## Install — Claude Code

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

Make them executable:
```bash
chmod +x hooks/mempal_save_hook.sh hooks/mempal_precompact_hook.sh
```

## Install — Codex CLI (OpenAI)

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

## Configuration

Edit `mempal_save_hook.sh` to change:

- **`SAVE_INTERVAL=15`** — How many human messages between saves. Lower = more frequent saves, higher = less interruption.
- **`STATE_DIR`** — Where hook state is stored (defaults to `~/.mempalace/hook_state/`)
- **`MEMPAL_DIR`** — Optional **project directory** (code, notes, docs) to also mine on each save trigger, with `--mode projects`. The hook ALWAYS mines the active conversation transcript automatically with `--mode convos` — `MEMPAL_DIR` is purely additive, never an override. Leave blank if you don't want to ingest project files.
- **`MEMPAL_PYTHON`** — Optional env var. Python interpreter with mempalace + chromadb installed. Auto-detects: `MEMPAL_PYTHON` env var → repo `venv/bin/python3` → system `python3`. Set this if your venv is in a non-standard location.

### mempalace CLI

The relevant commands are:

```bash
mempalace mine <dir>               # Mine all files in a directory
mempalace mine <dir> --mode convos # Mine conversation transcripts only
```

The hooks resolve the repo root automatically from their own path, so they work regardless of where you install the repo.

## How It Works (Technical)

### Save Hook (Stop event)

```
User sends message → AI responds → Claude Code fires Stop hook
                                            ↓
                                    Hook counts human messages in JSONL transcript
                                            ↓
                              ┌─── < 15 since last save ──→ echo "{}" (let AI stop)
                              │
                              └─── ≥ 15 since last save
                                            ↓
                                    Auto-mine transcript → palace (tool output captured)
                                            ↓
                              ┌─── silent mode (default) ──────────────────────────┐
                              │     _save_diary_direct() — plain text diary entry  │
                              │     Marker advances AFTER confirmed write          │
                              │     {"systemMessage": "✦ N memories woven..."}     │
                              └────────────────────────────────────────────────────┘
                              ┌─── block mode (legacy) ────────────────────────────┐
                              │     {"decision": "block", "reason": "save..."}     │
                              │     Marker advances BEFORE AI acts (data loss risk)│
                              │     AI saves → tries to stop → stop_hook_active    │
                              │     → hook lets it through                         │
                              └────────────────────────────────────────────────────┘
```

In silent mode, no AI interaction is needed — the hook saves and returns immediately. In block mode, the `stop_hook_active` flag prevents infinite loops: block once → AI saves → tries to stop → flag is true → we let it through.

### PreCompact Hook

```
Context window getting full → Claude Code fires PreCompact
                                        ↓
                                Find transcript (from input or session_id lookup)
                                        ↓
                                Auto-mine transcript → palace (tool output captured)
                                        ↓
                              ┌─── silent mode: diary entry + systemMessage
                              │
                              └─── block mode: {"decision": "block", "reason": "save everything..."}
                                        ↓
                                Compaction proceeds
```

No counting needed — compaction always warrants a save. The auto-mine captures raw tool output before the AI gets a chance to summarize it away.

## Debugging

Check the hook log:
```bash
cat ~/.mempalace/hook_state/hook.log
```

Example output:
```
[14:30:15] Session abc123: 12 exchanges, 12 since last save
[14:35:22] Session abc123: 15 exchanges, 15 since last save
[14:35:22] TRIGGERING SAVE at exchange 15
[14:40:01] Session abc123: 18 exchanges, 3 since last save
```

## Backfill Past Conversations

The hooks only capture conversations going forward. To mine **past** Claude Code sessions into your palace, run a one-time backfill:

```bash
mempalace mine ~/.claude/projects/ --mode convos
```

This scans all JSONL transcripts from previous sessions and files them into the `conversations` wing. On a typical developer machine with months of history, this can yield 50K–200K drawers.

For Codex CLI sessions:
```bash
mempalace mine ~/.codex/sessions/ --mode convos
```

This only needs to be done once — after that, the hooks auto-mine each session as you go.

## Known Limitations

**Hooks require session restart after install.** Claude Code loads hooks from `settings.json` at session start only. If you run `mempalace init` or manually edit hook config mid-session, the hooks won’t fire until you restart Claude Code. This is a Claude Code limitation.

**`MEMPAL_PYTHON` override for the hook's internal Python calls.** The save hook parses its JSON input and counts transcript messages with `python3`. When the harness is launched from a GUI on macOS — `open -a`, Spotlight, the dock — its `PATH` is the minimal `/usr/bin:/bin:/usr/sbin:/sbin` inherited from `launchd`, not your shell PATH. If `python3` isn't on that PATH, those internal calls fail and the hook can't count exchanges.

Point the hook at any Python 3 interpreter to fix it:

```bash
export MEMPAL_PYTHON="/usr/bin/python3"                   # system Python is fine
export MEMPAL_PYTHON="$HOME/.venvs/mempalace/bin/python"  # or your venv
```

Resolution priority: `$MEMPAL_PYTHON` (if set and executable) → `$(command -v python3)` → bare `python3`. The interpreter only needs `json` and `sys` from the standard library — `mempalace` itself does not need to be installed in it.

Note: the `mempalace mine` auto-ingest runs via the `mempalace` CLI, so that command also needs to be on the hook's `PATH`. Installing with `pipx install mempalace` or `uv tool install mempalace` puts it on a stable global location; otherwise extend the hook environment's `PATH` to include your venv's `bin/`.

## Backfill Past Conversations

The hooks only capture conversations going forward. To mine **past** Claude Code sessions into your palace, run a one-time backfill:

```bash
mempalace mine ~/.claude/projects/ --mode convos
```

This scans all JSONL transcripts from previous sessions and files them into the `conversations` wing. On a typical developer machine with months of history, this can yield 50K–200K drawers.

For Codex CLI sessions:
```bash
mempalace mine ~/.codex/sessions/ --mode convos
```

This only needs to be done once — after that, the hooks auto-mine each session as you go.

## Cost

**Zero extra tokens.** The hooks save in the background — the AI doesn’t need to write anything in the chat. All filing is handled automatically.
