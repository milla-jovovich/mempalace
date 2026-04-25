#!/bin/bash
# MemPalace remote PreCompact hook — SSH-wraps to the host's mempalace CLI
INPUT=$(cat)
echo "$INPUT" | ssh "${MEMPALACE_REMOTE_HOST:?MEMPALACE_REMOTE_HOST must be set in env}" "${MEMPALACE_REMOTE_BIN:-mempalace} hook run --hook precompact --harness claude-code"
