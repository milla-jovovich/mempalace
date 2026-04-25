#!/bin/bash
# MemPalace remote Stop hook — SSH-wraps to the host's mempalace CLI
INPUT=$(cat)
echo "$INPUT" | ssh "${MEMPALACE_REMOTE_HOST:?MEMPALACE_REMOTE_HOST must be set in env}" "mempalace hook run --hook stop --harness claude-code"
