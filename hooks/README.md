# MemPalace Hooks — Auto-Save for Terminal AI Tools

These hook scripts make MemPalace save automatically. No manual "save" commands needed.

## What They Do

| Hook | When It Fires | What Happens |
|------|--------------|-------------|
| **Save Hook** | Every 15 human messages | Auto-mines transcript (tool output included), then blocks the AI to save topics/decisions/quotes |
| **PreCompact Hook** | Right before context compaction | Auto-mines transcript, then emergency save — forces the AI to save EVERYTHING before losing context |

**Two-layer capture:** Hooks auto-mine the JSONL transcript directly into the palace (capturing raw tool output — Bash results, search findings, build errors). They also block the AI with a reason message telling it to save verbatim tool output and key context. Belt and suspenders — tool output gets stored even if the AI summarizes instead of quoting.

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
- **`MEMPALACE_PYTHON`** — Optional env var. Python interpreter with mempalace + chromadb installed. Auto-detects: `MEMPALACE_PYTHON` env var → repo `venv/bin/python3` → system `python3`. Set this if your venv is in a non-standard location.

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
                                    {"decision": "block", "reason": "save tool output verbatim..."}
                                            ↓
                                    AI saves to palace (topics, decisions, quotes)
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
                                Find transcript (from input or session_id lookup)
                                        ↓
                                Auto-mine transcript → palace (tool output captured)
                                        ↓
                                {"decision": "block", "reason": "save tool output verbatim..."}
                                        ↓
                                AI saves everything
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

## Cost

**Zero extra API tokens.** The hooks are bash scripts that run locally. They don't call any API. The auto-mining uses the local ChromaDB instance. The only "cost" is:
- ~1-13 seconds for transcript mining (depending on session length)
- The AI spending a few seconds organizing memories at each checkpoint — with context it already has loaded
- ChromaDB disk space for the mined chunks (~1KB per exchange pair)
