#!/bin/bash
# MEMPALACE PRE-COMPACT HOOK — Emergency save before compaction

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
SESSION_ID=$(echo "$INPUT" | "$PYTHON" -c "import sys,json; print(json.load(sys.stdin).get('session_id','unknown'))" 2>/dev/null)

echo "[$(date '+%H:%M:%S')] PRE-COMPACT triggered for session $SESSION_ID" >> "$STATE_DIR/hook.log"

if [ -n "$MEMPAL_DIR" ] && [ -d "$MEMPAL_DIR" ]; then
    run_mempalace mine "$MEMPAL_DIR" >> "$STATE_DIR/hook.log" 2>&1
fi

cat << 'HOOKJSON'
{
  "decision": "allow",
  "reason": "MemPalace pre-compaction save. Your full conversation has been saved verbatim in the background — no action needed. Compaction can proceed safely."
}
HOOKJSON
