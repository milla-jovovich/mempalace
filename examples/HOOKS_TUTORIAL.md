# How to Use MemPalace Hooks (Auto-Save)

MemPalace hooks act as an "Auto-Save" feature. They help your AI keep a permanent memory without you needing to run manual commands.

### 1. What are these hooks?
* **Save Hook** (`mempal_save_hook.sh`): Saves new facts and decisions every 15 messages.
* **PreCompact Hook** (`mempal_precompact_hook.sh`): Saves your context right before the AI's memory window fills up.

### 2. Setup for Claude Code
Add this to `~/.claude/settings.local.json` to enable automatic background saving globally, or to `.claude/settings.local.json` inside a specific project for project-scoped hooks.

**Important:** Use absolute paths — relative paths like `./hooks/...` will not work because Claude Code resolves hook commands from the working directory at hook fire time, not from the mempalace repo root.

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "*",
        "hooks": [{"type": "command", "command": "/absolute/path/to/mempalace/hooks/mempal_save_hook.sh", "timeout": 30}]
      }
    ],
    "PreCompact": [
      {
        "hooks": [{"type": "command", "command": "/absolute/path/to/mempalace/hooks/mempal_precompact_hook.sh", "timeout": 30}]
      }
    ]
  }
}