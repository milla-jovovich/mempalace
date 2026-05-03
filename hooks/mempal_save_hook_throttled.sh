#!/bin/bash
# Throttled wrapper — runs mempal_save_hook.sh every N stops (default: 10)
# Set MEMPAL_INTERVAL env var to override.

set -euo pipefail

INTERVAL="${MEMPAL_INTERVAL:-10}"
COUNTER_FILE="${TMPDIR:-/tmp}/mempalace_stop_counter_${UID:-0}"

# Read current count, increment, write back
COUNT=$(cat "$COUNTER_FILE" 2>/dev/null || echo "0")
COUNT=$(( COUNT + 1 ))
echo "$COUNT" > "$COUNTER_FILE"

if (( COUNT % INTERVAL == 0 )); then
    exec "$(dirname "${BASH_SOURCE[0]}")/mempal_save_hook.sh"
else
    # Must consume stdin so Claude Code hook doesn't hang
    cat > /dev/null
    echo "{}"
fi
