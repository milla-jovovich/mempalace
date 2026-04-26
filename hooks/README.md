# MemPalace Hooks — Auto-Save for Terminal AI Tools

These hook scripts make MemPalace save automatically. No manual "save" commands needed.

## What They Do

| Hook | When It Fires | What Happens |
|------|--------------|-------------|
| **Save Hook** | Every 15 human messages | Blocks the AI, tells it to save key topics/decisions/quotes to the palace |
| **PreCompact Hook** | Right before context compaction | Emergency save — forces the AI to save EVERYTHING before losing context |

The AI does the actual filing — it knows the conversation context, so it classifies memories into the right wings/halls/closets. The hooks just tell it WHEN to save.

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
- **`MEMPAL_DIR`** — Optional. Set to a conversations directory to auto-run `mempalace mine <dir>` on each save trigger. Leave blank (default) to let the AI handle saving via the block reason message.

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
                              └─── ≥ 15 since last save ──→ {"decision": "block", "reason": "save..."}
                                                                    ↓
                                                            AI saves to palace
                                                                    ↓
                                                            AI tries to stop again
                                                                    ↓
                                                            stop_hook_active = true
                                                                    ↓
                                                            Hook sees flag → echo "{}" (let it through)
```

The `stop_hook_active` flag prevents infinite loops: block once → AI saves → tries to stop → flag is true → we let it through.

### PreCompact Hook

```
Context window getting full → Claude Code fires PreCompact
                                        ↓
                                Hook ALWAYS blocks
                                        ↓
                                AI saves everything
                                        ↓
                                Compaction proceeds
```

No counting needed — compaction always warrants a save.

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

## Known Limitations

**Hooks require session restart after install.** Claude Code loads hooks from `settings.json` at session start only. If you run `mempalace init` or manually edit hook config mid-session, the hooks won't fire until you restart Claude Code. This is a Claude Code limitation.

**`MEMPAL_PYTHON` override for the hook's internal Python calls.** The save hook parses its JSON input and counts transcript messages with `python3`. When the harness is launched from a GUI on macOS — `open -a`, Spotlight, the dock — its `PATH` is the minimal `/usr/bin:/bin:/usr/sbin:/sbin` inherited from `launchd`, not your shell PATH. If `python3` isn't on that PATH, those internal calls fail and the hook can't count exchanges.

Point the hook at any Python 3 interpreter to fix it:

```bash
export MEMPAL_PYTHON="/usr/bin/python3"                   # system Python is fine
export MEMPAL_PYTHON="$HOME/.venvs/mempalace/bin/python"  # or your venv
```

Resolution priority: `$MEMPAL_PYTHON` (if set and executable) → `$(command -v python3)` → bare `python3`. The interpreter only needs `json` and `sys` from the standard library — `mempalace` itself does not need to be installed in it.

Note: the `mempalace mine` auto-ingest runs via the `mempalace` CLI, so that command also needs to be on the hook's `PATH`. Installing with `pipx install mempalace` or `uv tool install mempalace` puts it on a stable global location; otherwise extend the hook environment's `PATH` to include your venv's `bin/`.

## Cost

**Zero extra tokens.** The hooks notify the AI that saves happened in the background — the AI doesn't need to write anything in the chat. All filing is handled automatically. Previous versions asked the AI to write diary entries and drawer content in the chat window, which cost ~$1/session in retransmitted tokens.
