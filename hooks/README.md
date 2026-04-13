# MemPalace Hooks — Auto-Save for Terminal AI Tools

MemPalace can run hooks directly through `mempalace hook run`. That Python hook
runner is the preferred, tested path for Claude Code and Codex. The shell
scripts in this directory remain available as editable wrappers when you want a
host-specific script instead of a direct CLI command.

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
        "command": "python -m mempalace hook run --hook stop --harness claude-code",
        "timeout": 30
      }]
    }],
    "PreCompact": [{
      "hooks": [{
        "type": "command",
        "command": "python -m mempalace hook run --hook precompact --harness claude-code",
        "timeout": 30
      }]
    }]
  }
}
```

## Install — Codex CLI (OpenAI)

Add to `.codex/hooks.json`:

```json
{
  "Stop": [{
    "type": "command",
    "command": "python -m mempalace hook run --hook stop --harness codex",
    "timeout": 30
  }],
  "PreCompact": [{
    "type": "command",
    "command": "python -m mempalace hook run --hook precompact --harness codex",
    "timeout": 30
  }]
}
```

## Current Behavior

The Python hook runner currently uses:

- **15-message stop cadence** for automatic save checkpoints
- **`~/.mempalace/hook_state/`** for hook state and logs
- **Optional `MEMPAL_DIR`** to auto-run `mempalace mine <dir>` on each save trigger
- **Single-flight stop-hook ingest** so repeated hook firings do not stack concurrent miners
- **Timeout-safe precompact ingest** so a slow `mine` run still returns the block decision

If you need hard-coded local overrides, the legacy shell wrappers in this
directory are still editable. Make them executable first:

```bash
chmod +x hooks/mempal_save_hook.sh hooks/mempal_precompact_hook.sh
```

### mempalace CLI

The relevant commands are:

```bash
mempalace hook run --hook stop --harness codex
mempalace hook run --hook precompact --harness claude-code
mempalace mine <dir>               # Mine all files in a directory
mempalace mine <dir> --mode convos # Mine conversation transcripts only
```

The direct CLI hook path does not depend on repo-relative shell wrappers, which
also makes pipx and venv installs behave more predictably.

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

If `MEMPAL_DIR` is set, the stop hook launches at most one background miner at a
time and cleans up stale pid markers automatically.

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

If `MEMPAL_DIR` is set, precompact runs a best-effort foreground ingest. On slow
or wedged runs it logs, terminates the child process, and still returns the
block response instead of failing open.

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

## Cost

**Zero extra tokens.** The hooks are bash scripts that run locally. They don't call any API. The only "cost" is the AI spending a few seconds organizing memories at each checkpoint — and it's doing that with context it already has loaded.
