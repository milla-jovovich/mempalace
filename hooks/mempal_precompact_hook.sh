#!/bin/bash
# MEMPALACE PRE-COMPACT HOOK — Emergency save before compaction
#
# Claude Code "PreCompact" hook. Fires RIGHT BEFORE the conversation
# gets compressed to free up context window space.
#
# This is the safety net. When compaction happens, the AI loses detailed
# context about what was discussed. This hook forces one final save of
# EVERYTHING before that happens.
#
# Unlike the save hook (which triggers every N exchanges), the precompact
# hook fires exactly once: right before /compact. By default it nudges the
# model to save (via stderr) and returns {} so compaction proceeds. Set
# MEMPAL_BLOCK_COMPACT=1 to opt into a two-phase hard-block (block once,
# allow the retry) for users who want a forced save-before-compact pause.
#
# === INSTALL ===
# Add to .claude/settings.local.json:
#
#   "hooks": {
#     "PreCompact": [{
#       "hooks": [{
#         "type": "command",
#         "command": "/absolute/path/to/mempal_precompact_hook.sh",
#         "timeout": 30
#       }]
#     }]
#   }
#
# For Codex CLI, add to .codex/hooks.json:
#
#   "PreCompact": [{
#     "type": "command",
#     "command": "/absolute/path/to/mempal_precompact_hook.sh",
#     "timeout": 30
#   }]
#
# === HOW IT WORKS ===
#
# Claude Code sends JSON on stdin with:
#   session_id — unique session identifier
#
# Default behavior: print a save nudge to stderr (which Claude Code surfaces
# to the model) and return {} so compaction is not blocked. This restores
# the safety nudge that PR #885 dropped without re-introducing the
# unconditional block from #858 (which had no escape path).
#
# Opt-in hard-block: export MEMPAL_BLOCK_COMPACT=1 to use the two-phase
# behavior — the first /compact attempt this session blocks with the nudge
# as the reason, the next attempt clears the per-session flag and allows
# compaction. This gives users who want a forced save-before-compact pause
# a way to do that without footgunning themselves.
#
# === MEMPALACE CLI ===
# This repo uses: mempalace mine <dir>
# or:            mempalace mine <dir> --mode convos
# Set MEMPAL_DIR below if you want the hook to auto-ingest before compaction.
# Leave blank to rely on the AI's own save instructions.

STATE_DIR="$HOME/.mempalace/hook_state"
mkdir -p "$STATE_DIR"

# Optional: set to the directory you want auto-ingested before compaction.
# Example: MEMPAL_DIR="$HOME/conversations"
# Leave empty to skip auto-ingest (AI handles saving via the block reason).
MEMPAL_DIR=""

# Resolve the Python interpreter. Same contract as mempal_save_hook.sh:
# MEMPAL_PYTHON (explicit override) → $(command -v python3) → bare python3.
MEMPAL_PYTHON_BIN="${MEMPAL_PYTHON:-}"
if [ -z "$MEMPAL_PYTHON_BIN" ] || [ ! -x "$MEMPAL_PYTHON_BIN" ]; then
    MEMPAL_PYTHON_BIN="$(command -v python3 2>/dev/null || echo python3)"
fi

# Read JSON input from stdin
INPUT=$(cat)

SESSION_ID=$(echo "$INPUT" | "$MEMPAL_PYTHON_BIN" -c "import sys,json; print(json.load(sys.stdin).get('session_id','unknown'))" 2>/dev/null)

echo "[$(date '+%H:%M:%S')] PRE-COMPACT triggered for session $SESSION_ID" >> "$STATE_DIR/hook.log"

# Optional: run mempalace ingest synchronously so memories land before compaction
if [ -n "$MEMPAL_DIR" ] && [ -d "$MEMPAL_DIR" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    REPO_DIR="$(dirname "$SCRIPT_DIR")"
    mempalace mine "$MEMPAL_DIR" >> "$STATE_DIR/hook.log" 2>&1
fi

NUDGE="MemPalace: compaction imminent. If you have unsaved topics, decisions, quotes, code, or important context from this session, save them via your memory system NOW. After compaction, detailed context is lost."

# Opt-in hard-block (MEMPAL_BLOCK_COMPACT=1) — two-phase: block once per
# session, then allow on the next attempt. The per-session flag prevents
# the original #858 footgun where the unconditional block had no escape.
if [ "${MEMPAL_BLOCK_COMPACT:-0}" = "1" ]; then
    BLOCKED_FLAG="$STATE_DIR/${SESSION_ID}_blocked_compact"
    if [ -f "$BLOCKED_FLAG" ]; then
        rm -f "$BLOCKED_FLAG"
        echo '{}'
        exit 0
    fi
    touch "$BLOCKED_FLAG"
    NUDGE="$NUDGE" "$MEMPAL_PYTHON_BIN" -c '
import json, os
print(json.dumps({"decision": "block", "reason": os.environ["NUDGE"]}))
'
    exit 0
fi

# Default: print nudge to stderr (Claude Code surfaces it to the model)
# and return {} so compaction proceeds.
echo "$NUDGE" >&2
echo '{}'
