#!/bin/bash
# MEMPALACE SAVE HOOK - Auto-save every N exchanges
#
# Claude Code "Stop" hook. After every assistant response:
# 1. Count human messages in the session transcript.
# 2. Every SAVE_INTERVAL messages, block the AI from stopping.
# 3. Return a reason telling the AI a background save is happening.
# 4. Auto-mine the transcript directory in the background.
# 5. Next Stop fires with stop_hook_active=true and the AI can stop.
#
# The AI keeps its conversational context while MemPalace handles filing.
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
#
# === HOW IT WORKS ===
#
# Claude Code sends JSON on stdin with:
#   session_id       unique session identifier
#   stop_hook_active true if AI is already in a save cycle
#   transcript_path  path to the JSONL transcript file
#
# When we block, Claude Code shows our "reason" to the AI as a system message.
# The AI can continue or stop naturally after the background save trigger.
#
# === MEMPALACE CLI ===
# This repo uses: mempalace mine <dir>
# or:            mempalace mine <dir> --mode convos
# Set MEMPAL_DIR below if you want the hook to mine a fixed directory instead.
#
# === CONFIGURATION ===

SAVE_INTERVAL=15
STATE_DIR="$HOME/.mempalace/hook_state"
mkdir -p "$STATE_DIR"

# Optional fixed directory to mine on each save trigger.
# Example: MEMPAL_DIR="$HOME/conversations"
# Leave empty to auto-mine the active transcript directory.
MEMPAL_DIR=""

INPUT=$(cat)

# Parse all fields in a single Python call.
eval $(echo "$INPUT" | python3 -c "
import json, re, sys
data = json.load(sys.stdin)
sid = data.get('session_id', 'unknown')
sha = data.get('stop_hook_active', False)
tp = data.get('transcript_path', '')
safe = lambda s: re.sub(r'[^a-zA-Z0-9_/.\\-~:]', '', str(s))
print(f'SESSION_ID=\"{safe(sid)}\"')
print(f'STOP_HOOK_ACTIVE=\"{sha}\"')
print(f'TRANSCRIPT_PATH=\"{safe(tp)}\"')
" 2>/dev/null)

TRANSCRIPT_PATH="${TRANSCRIPT_PATH/#\~/$HOME}"

if [ "$STOP_HOOK_ACTIVE" = "True" ] || [ "$STOP_HOOK_ACTIVE" = "true" ]; then
    echo "{}"
    exit 0
fi

# Count human messages in the JSONL transcript.
if [ -f "$TRANSCRIPT_PATH" ]; then
    EXCHANGE_COUNT=$(python3 - "$TRANSCRIPT_PATH" <<'PYEOF'
import json
import sys

count = 0
with open(sys.argv[1], encoding="utf-8") as f:
    for line in f:
        try:
            entry = json.loads(line)
            msg = entry.get("message", {})
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str) and "<command-message>" in content:
                    continue
                count += 1
        except Exception:
            pass
print(count)
PYEOF
2>/dev/null)
else
    EXCHANGE_COUNT=0
fi

LAST_SAVE_FILE="$STATE_DIR/${SESSION_ID}_last_save"
LAST_SAVE=0
if [ -f "$LAST_SAVE_FILE" ]; then
    LAST_SAVE=$(cat "$LAST_SAVE_FILE")
fi

SINCE_LAST=$((EXCHANGE_COUNT - LAST_SAVE))

echo "[$(date '+%H:%M:%S')] Session $SESSION_ID: $EXCHANGE_COUNT exchanges, $SINCE_LAST since last save" >> "$STATE_DIR/hook.log"

if [ "$SINCE_LAST" -ge "$SAVE_INTERVAL" ] && [ "$EXCHANGE_COUNT" -gt 0 ]; then
    echo "$EXCHANGE_COUNT" > "$LAST_SAVE_FILE"
    echo "[$(date '+%H:%M:%S')] TRIGGERING SAVE at exchange $EXCHANGE_COUNT" >> "$STATE_DIR/hook.log"

    PYTHON="$(command -v python3)"
    MINE_DIR=""

    if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ]; then
        MINE_DIR="$(dirname "$TRANSCRIPT_PATH")"
    fi

    if [ -n "$MEMPAL_DIR" ] && [ -d "$MEMPAL_DIR" ]; then
        MINE_DIR="$MEMPAL_DIR"
    fi

    if [ -n "$MINE_DIR" ]; then
        "$PYTHON" -m mempalace mine "$MINE_DIR" >> "$STATE_DIR/hook.log" 2>&1 &
    fi

    cat <<'HOOKJSON'
{
  "decision": "allow",
  "reason": "MemPalace auto-save checkpoint. Your conversation is being saved verbatim in the background; no action needed."
}
HOOKJSON
else
    echo "{}"
fi
