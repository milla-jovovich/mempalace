# How to Use MemPalace Hooks (Auto-Save)

MemPalace hooks act as an auto-save feature. They help your AI keep a
permanent memory without you needing to run manual commands.

### 1. What are these hooks?

* **Save Hook**: Saves new facts and decisions every 15 messages.
* **PreCompact Hook**: Saves your context right before the AI's memory window
  fills up.

For Claude Code and Codex, the preferred path is the Python hook runner:
`python -m mempalace hook run ...`. The shell scripts in `hooks/` remain useful
as editable wrappers for other hosts.

### 2. Setup for Claude Code

Add this to your configuration file:

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python -m mempalace hook run --hook stop --harness claude-code"
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python -m mempalace hook run --hook precompact --harness claude-code"
          }
        ]
      }
    ]
  }
}
```

For Codex CLI, use the same commands with `--harness codex`.
