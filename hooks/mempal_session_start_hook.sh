#!/bin/bash
# MEMPALACE SESSION-START HOOK
# Loads palace context (wake-up + cwd-matched wing) and a protocol nudge into the session.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEMPALACE_SRC="$(dirname "$SCRIPT_DIR")"
export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$MEMPALACE_SRC"

# Pin to the mempalace venv (chromadb etc.). Override via MEMPAL_PYTHON.
MEMPAL_PYTHON="${MEMPAL_PYTHON:-$HOME/.mempalace/venv/bin/python}"
[ -x "$MEMPAL_PYTHON" ] || MEMPAL_PYTHON="python3"

INPUT=$(cat)
HARNESS="claude-code"
PARENT_CMD=$(ps -p $PPID -o comm= 2>/dev/null | tr -d ' ' || echo "")
case "$PARENT_CMD" in
  codex|Codex) HARNESS="codex" ;;
  gemini|Gemini|gemini-cli) HARNESS="gemini" ;;
  qwen|Qwen|qwen-code) HARNESS="qwen" ;;
  opencode|Opencode) HARNESS="opencode" ;;
  *) ;;
esac
printf '%s' "$INPUT" | "$MEMPAL_PYTHON" -m mempalace hook run --hook session-start --harness "$HARNESS"

# Pre-warm ChromaDB in background so the first Stop hook doesn't cold-start
"$MEMPAL_PYTHON" -c "
import os, sys
sys.path.insert(0, os.environ.get('PYTHONPATH','').split(':')[0])
try:
    from mempalace.backends.chroma import ChromaBackend
    b = ChromaBackend()
    b.get_collection(os.path.expanduser('~/.mempalace/palace'), 'mempalace_drawers', create=False)
except Exception:
    pass
" >/dev/null 2>&1 &
