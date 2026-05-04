#!/bin/bash
# MEMPALACE FRESHNESS HOOK — Check palace freshness on session start
#
# Runs as a "Notification" or "Stop" hook to tell the AI
# whether the palace is current or has stale memories.
#
# === INSTALL ===
# Add to .claude/settings.local.json:
#
#   "hooks": {
#     "Stop": [{
#       "matcher": "*",
#       "hooks": [{
#         "type": "command",
#         "command": "/absolute/path/to/mempal_freshness_hook.sh",
#         "timeout": 30
#       }]
#     }]
#   }
#
# === HOW IT WORKS ===
#
# 1. Reads stdin for session context (JSON with stop_hook_active flag)
# 2. If stop_hook_active is true, allows AI to stop (prevents loops)
# 3. Runs 'mempalace sync --dry-run' on first call per session
# 4. If stale files detected, BLOCKS the AI from stopping
#    and returns a reason asking it to call mempalace_sync_status
# 5. On subsequent calls, allows normal stop
#
# === CONFIGURATION ===
#
# Set CHECK_DIR to limit freshness check to a specific directory.
# Leave empty to check all source files.
CHECK_DIR=""
# Maximum time between checks (seconds). Default: once per session.
CHECK_INTERVAL=3600

# ─── Implementation ──────────────────────────────────────

set -euo pipefail
trap 'echo "{\"decision\": \"allow\"}"'  EXIT

# Read stdin
INPUT=$(cat)

# Check if we're in a save cycle (prevent infinite loop)
STOP_ACTIVE=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('stop_hook_active', False))" 2>/dev/null || echo "False")

if [ "$STOP_ACTIVE" = "True" ] || [ "$STOP_ACTIVE" = "true" ]; then
    exit 0
fi

# Session tracking — only check once per session
SESSION_ID=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('session_id', 'unknown'))" 2>/dev/null || echo "unknown")
# Sanitize session ID to prevent path traversal
SESSION_ID=$(echo "$SESSION_ID" | tr -cd 'A-Za-z0-9_-')
STAMP_FILE="/tmp/mempalace_freshness_${SESSION_ID}"

if [ -f "$STAMP_FILE" ]; then
    LAST_CHECK=$(cat "$STAMP_FILE")
    NOW=$(date +%s)
    ELAPSED=$((NOW - LAST_CHECK))
    if [ "$ELAPSED" -lt "$CHECK_INTERVAL" ]; then
        exit 0
    fi
fi

# Run freshness check — no eval, safe quoting
if [ -n "$CHECK_DIR" ]; then
    SYNC_OUTPUT=$(python3 -m mempalace sync --dry-run --dir "$CHECK_DIR" 2>/dev/null || echo "")
else
    SYNC_OUTPUT=$(python3 -m mempalace sync --dry-run 2>/dev/null || echo "")
fi
STALE_COUNT=$(echo "$SYNC_OUTPUT" | sed -n 's/.*Stale (changed):[[:space:]]*\([0-9]*\).*/\1/p' 2>/dev/null)
STALE_COUNT="${STALE_COUNT:-0}"

# Record check time
date +%s > "$STAMP_FILE"

trap - EXIT
if [ "$STALE_COUNT" -gt "0" ]; then
    # Stale files found — tell AI to check
    cat <<ENDJSON
{"decision": "block", "reason": "Palace freshness check: $STALE_COUNT source files have changed since last mine. Call mempalace_sync_status to see details and get re-mine commands. This ensures your memory is current before answering questions."}
ENDJSON
else
    echo '{"decision": "allow"}'
fi
