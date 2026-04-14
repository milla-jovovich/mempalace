#!/bin/bash
# MEMPALACE SAVE HOOK — Auto-save every N exchanges

SAVE_INTERVAL="${MEMPALACE_SAVE_INTERVAL:-15}"
STATE_DIR="${MEMPALACE_HOOK_STATE_DIR:-$HOME/.mempalace/hook_state}"
MEMPAL_DIR="${MEMPAL_DIR:-}"
MEMPALACE_CMD="${MEMPALACE_COMMAND:-mempalace}"
PYTHON="${MEMPALACE_PYTHON:-$(command -v python 2>/dev/null || command -v python3 2>/dev/null)}"

mkdir -p "$STATE_DIR"

run_mempalace() {
    if command -v "$MEMPALACE_CMD" >/dev/null 2>&1; then
        "$MEMPALACE_CMD" "$@"
    else
        "$PYTHON" -m mempalace "$@"
    fi
}

INPUT=$(cat)

eval $(echo "$INPUT" | "$PYTHON" -c "
import sys, json, re
data = json.load(sys.stdin)
sid = data.get('session_id', 'unknown')
sha = data.get('stop_hook_active', False)
tp = data.get('transcript_path', '')
safe = lambda s: re.sub(r'[^a-zA-Z0-9_/\.\-~]', '', str(s))
print(f'SESSION_ID=\"{safe(sid)}\"')
print(f'STOP_HOOK_ACTIVE=\"{sha}\"')
print(f'TRANSCRIPT_PATH=\"{safe(tp)}\"')
" 2>/dev/null)

TRANSCRIPT_PATH="${TRANSCRIPT_PATH/#\~/$HOME}"

if [ "$STOP_HOOK_ACTIVE" = "True" ] || [ "$STOP_HOOK_ACTIVE" = "true" ]; then
    echo "{}"
    exit 0
fi

if [ -f "$TRANSCRIPT_PATH" ]; then
    EXCHANGE_COUNT=$("$PYTHON" - "$TRANSCRIPT_PATH" <<'PYEOF'
import json, sys
count = 0
with open(sys.argv[1]) as f:
    for line in f:
        try:
            entry = json.loads(line)
            msg = entry.get('message', {})
            if isinstance(msg, dict) and msg.get('role') == 'user':
                content = msg.get('content', '')
                if isinstance(content, str) and '<command-message>' in content:
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

    MINE_DIR=""
    if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ]; then
        MINE_DIR="$(dirname "$TRANSCRIPT_PATH")"
    fi
    if [ -n "$MEMPAL_DIR" ] && [ -d "$MEMPAL_DIR" ]; then
        MINE_DIR="$MEMPAL_DIR"
    fi
    if [ -n "$MINE_DIR" ]; then
        run_mempalace mine "$MINE_DIR" >> "$STATE_DIR/hook.log" 2>&1 &
    fi

    cat << 'HOOKJSON'
{
  "decision": "allow",
  "reason": "MemPalace auto-save checkpoint. Your conversation is being saved verbatim in the background — no action needed from you. Continue working."
}
HOOKJSON
else
    echo "{}"
fi
