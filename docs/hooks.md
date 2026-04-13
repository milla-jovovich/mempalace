# Hooks

Auto-save hooks for Claude Code and Gemini CLI that trigger automatic memory saves during work.

## What the hooks do

| Hook | When it fires | What happens |
|------|--------------|-------------|
| **Save hook** | Every 15 human messages | Blocks the AI and instructs it to save key topics, decisions, and quotes to the palace |
| **PreCompact hook** | Before context compression | Emergency save — forces the AI to save everything before the context window shrinks |

The hooks are shell scripts that run locally. They don't call any API. The AI does the actual filing — it knows the conversation context, so it classifies memories into the right wings and rooms.

## Setup

### Claude Code

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

Make the scripts executable:

```bash
chmod +x hooks/mempal_save_hook.sh hooks/mempal_precompact_hook.sh
```

### Gemini CLI

Add to `~/.gemini/settings.json`:

```json
{
  "hooks": {
    "PreCompress": [{
      "matcher": "*",
      "hooks": [{
        "type": "command",
        "command": "/absolute/path/to/hooks/mempal_precompact_hook.sh"
      }]
    }]
  }
}
```

### Codex CLI (OpenAI)

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

| Variable | Default | Description |
|----------|---------|-------------|
| `SAVE_INTERVAL` | `15` | Human messages between saves. Lower = more frequent. |
| `STATE_DIR` | `~/.mempalace/hook_state/` | Where hook state and logs are stored |
| `MEMPAL_DIR` | (empty) | Set to a directory path to auto-run `mempalace mine <dir>` on each save trigger |

## How it works

### Save hook (Stop event)

```
User message → AI responds → Stop hook fires
                                    ↓
                        Count human messages in transcript
                                    ↓
               < 15 since last save → let AI stop normally
               ≥ 15 since last save → block AI, instruct it to save
                                              ↓
                                    AI saves to palace → tries to stop again
                                              ↓
                                    stop_hook_active flag → let it through
```

The `stop_hook_active` flag prevents infinite loops: block once → AI saves → tries to stop → flag is set → hook lets it through.

### PreCompact hook

Always blocks. Context compression always warrants a save.

## Auto-ingest

Set `MEMPAL_DIR` to have the hooks automatically run `mempalace mine` on a directory during each save trigger:

- On stop events: runs in the background (non-blocking).
- On precompact events: runs synchronously (blocks until complete).

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

Zero extra tokens. The hooks are bash scripts that run locally. The only cost is the AI spending a few seconds organizing memories at each checkpoint using context it already has loaded.
