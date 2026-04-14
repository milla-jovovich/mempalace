#!/usr/bin/env bash
set -euo pipefail

HOOK_NAME="${1:?Usage: mempal-hook.sh <hook-name>}"
MEMPALACE_CMD="${MEMPALACE_COMMAND:-mempalace}"
PYTHON="${MEMPALACE_PYTHON:-$(command -v python 2>/dev/null || command -v python3 2>/dev/null)}"

run_mempalace() {
  if command -v "$MEMPALACE_CMD" >/dev/null 2>&1; then
    "$MEMPALACE_CMD" "$@"
  else
    "$PYTHON" -m mempalace "$@"
  fi
}

INPUT_FILE=$(mktemp) || { echo "Failed to create temp file" >&2; exit 1; }
cat > "$INPUT_FILE"
cat "$INPUT_FILE" | run_mempalace hook run --hook "$HOOK_NAME" --harness codex
EXIT_CODE=$?
rm -f "$INPUT_FILE" 2>/dev/null
exit $EXIT_CODE
