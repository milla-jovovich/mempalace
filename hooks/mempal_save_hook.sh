#!/bin/bash
# MEMPALACE SAVE HOOK — Auto-detect harness (claude-code, codex, opencode, claude)
#
# Claude Code "Stop" hook. After every assistant response:
# 1. Counts human messages in the session transcript
# 2. Every SAVE_INTERVAL messages, BLOCKS the AI from stopping
# 3. Returns a reason telling the AI to save structured diary + palace entries
# 4. AI does the save (topics, decisions, code, quotes → organized into palace)
# 5. Next Stop fires with stop_hook_active=true → lets AI stop normally
#
# === INSTALL ===
# Add to .claude/settings.local.json:
#
#   "hooks": {
#     "Stop": [{
#       "matcher": "*",
#       "hooks": [{
#         "type": "command",
#         "command": "/absolute/path/to/mempal_save_hook.sh",
#         "timeout": 30
#       }]
#     }]
#   }
#
# For Codex CLI, add to .codex/hooks.json:
#
#   "Stop": [{
#     "type": "command",
#     "command": "/absolute/path/to/mempal_save_hook.sh",
#     "timeout": 30
#   }]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEMPALACE_SRC="$(dirname "$SCRIPT_DIR")"
export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$MEMPALACE_SRC"

# Pin to the mempalace venv (chromadb etc.). Override via MEMPAL_PYTHON.
MEMPAL_PYTHON="${MEMPAL_PYTHON:-$HOME/.mempalace/venv/bin/python}"
[ -x "$MEMPAL_PYTHON" ] || MEMPAL_PYTHON="python3"

# Delegate to Python implementation
exec "$MEMPAL_PYTHON" -m mempalace.hooks stop claude-code
