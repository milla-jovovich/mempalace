#!/bin/bash
# MemPalace Stop Hook — thin wrapper calling Python CLI
# All logic lives in mempalace.hooks_cli for cross-harness extensibility
find_python() {
    if [ -n "${MEMPALACE_PYTHON:-}" ]; then echo "$MEMPALACE_PYTHON"
    elif command -v python3 &>/dev/null; then echo "python3"
    elif command -v python &>/dev/null; then echo "python"
    else echo "python3"; fi
}
PYTHON=$(find_python)
INPUT=$(cat)
echo "$INPUT" | $PYTHON -m mempalace hook run --hook stop --harness claude-code
