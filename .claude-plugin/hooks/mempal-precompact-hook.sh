#!/bin/bash
# MemPalace PreCompact Hook — thin wrapper calling Python CLI
# All logic lives in mempalace.hooks_cli for cross-harness extensibility
INPUT=$(cat)
echo "$INPUT" | python3 -m mempalace hook run --hook precompact --harness claude-code
