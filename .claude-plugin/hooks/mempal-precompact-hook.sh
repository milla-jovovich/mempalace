#!/bin/bash
# MemPalace PreCompact Hook — thin wrapper calling Python CLI
# All logic lives in mempalace.hooks_cli for cross-harness extensibility
#
# Python resolution order:
#   1. MEMPALACE_PYTHON env var (user override)
#   2. Plugin root's venv (development installs)
#   3. System python3 (pip install --user / pipx)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="$(dirname "$SCRIPT_DIR")"

if [ -n "$MEMPALACE_PYTHON" ] && [ -x "$MEMPALACE_PYTHON" ]; then
    PYTHON="$MEMPALACE_PYTHON"
elif [ -x "$PLUGIN_ROOT/venv/bin/python3" ]; then
    PYTHON="$PLUGIN_ROOT/venv/bin/python3"
else
    PYTHON="python3"
fi
INPUT=$(cat)
echo "$INPUT" | "$PYTHON" -m mempalace hook run --hook precompact --harness claude-code
