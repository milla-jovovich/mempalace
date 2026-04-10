#!/bin/bash
# MemPalace PreCompact Hook — thin wrapper calling Python CLI
# All logic lives in mempalace.hooks_cli for cross-harness extensibility
# Uses the mempalace venv Python so this works from any project directory.
MEMPALACE_PYTHON="${HOME}/Projects/memorypalace/venv/bin/python3"
if [ ! -x "$MEMPALACE_PYTHON" ]; then
    MEMPALACE_PYTHON="python3"  # fallback to system python
fi
INPUT=$(cat)
echo "$INPUT" | "$MEMPALACE_PYTHON" -m mempalace hook run --hook precompact --harness claude-code
