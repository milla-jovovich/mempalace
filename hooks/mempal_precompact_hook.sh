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
# Unlike the save hook (which triggers every N exchanges), this ALWAYS
# blocks — because compaction is always worth saving before.
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
# We always return decision: "block" with a reason telling the AI
# to save everything. After the AI saves, compaction proceeds normally.
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

# Prefer the MemPalace interpreter when installed via pipx or an active venv.
# Falling back to bare python3 is what broke hook installs in #545.
resolve_python() {
    if [ -n "${MEMPALACE_PYTHON:-}" ] && [ -x "$MEMPALACE_PYTHON" ]; then
        printf '%s\n' "$MEMPALACE_PYTHON"
        return
    fi

    if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
        printf '%s\n' "$VIRTUAL_ENV/bin/python"
        return
    fi

    if command -v mempalace >/dev/null 2>&1; then
        MEMPAL_BIN="$(command -v mempalace)"
        MEMPAL_BIN_DIR="$(cd "$(dirname "$MEMPAL_BIN")" && pwd)"
        if [ -x "$MEMPAL_BIN_DIR/python" ]; then
            printf '%s\n' "$MEMPAL_BIN_DIR/python"
            return
        fi
        if [ -x "$MEMPAL_BIN_DIR/python3" ]; then
            printf '%s\n' "$MEMPAL_BIN_DIR/python3"
            return
        fi
    fi

    if command -v python3 >/dev/null 2>&1; then
        printf '%s\n' "python3"
        return
    fi

    printf '%s\n' "python"
}

PYTHON_BIN="$(resolve_python)"

# Read JSON input from stdin
INPUT=$(cat)

SESSION_ID=$(echo "$INPUT" | "$PYTHON_BIN" -c "import sys,json; print(json.load(sys.stdin).get('session_id','unknown'))" 2>/dev/null)

echo "[$(date '+%H:%M:%S')] PRE-COMPACT triggered for session $SESSION_ID" >> "$STATE_DIR/hook.log"

# Optional: run mempalace ingest synchronously so memories land before compaction
if [ -n "$MEMPAL_DIR" ] && [ -d "$MEMPAL_DIR" ]; then
    "$PYTHON_BIN" -m mempalace mine "$MEMPAL_DIR" >> "$STATE_DIR/hook.log" 2>&1
fi

# Always block — compaction = save everything
cat << 'HOOKJSON'
{
  "decision": "block",
  "reason": "COMPACTION IMMINENT. Save ALL topics, decisions, quotes, code, and important context from this session to your memory system. Be thorough — after compaction, detailed context will be lost. Organize into appropriate categories. Use verbatim quotes where possible. Save everything, then allow compaction to proceed."
}
HOOKJSON
