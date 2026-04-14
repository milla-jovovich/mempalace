#!/bin/bash
set -euo pipefail
# MemPalace PreCompact Hook — thin wrapper calling MemPalace CLI
# All logic lives in mempalace.hooks_cli for cross-harness extensibility

INPUT=$(cat)
MEMPALACE_CMD="${MEMPALACE_COMMAND:-mempalace}"
PYTHON="${MEMPALACE_PYTHON:-$(command -v python 2>/dev/null || command -v python3 2>/dev/null)}"

run_mempalace() {
  if command -v "$MEMPALACE_CMD" >/dev/null 2>&1; then
    "$MEMPALACE_CMD" "$@"
  else
    "$PYTHON" -m mempalace "$@"
  fi
}

echo "$INPUT" | run_mempalace hook run --hook precompact --harness claude-code
