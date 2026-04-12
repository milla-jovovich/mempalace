#!/bin/bash
# MemPalace Stop Hook — thin wrapper calling Python CLI
# All logic lives in mempalace.hooks_cli for cross-harness extensibility
INPUT=$(cat)
echo "$INPUT" | python3 -m mempalace hook run --hook stop --harness claude-code
