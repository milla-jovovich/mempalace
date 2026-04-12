#!/usr/bin/env bash
# mine-all-sessions.sh — Mine Cursor, Copilot CLI, and Factory sessions into the palace.
#
# Usage:
#   bash mine-all-sessions.sh              # mine everything
#   bash mine-all-sessions.sh --dry-run    # preview only
#   bash mine-all-sessions.sh copilot      # mine one source only
#   bash mine-all-sessions.sh cursor factory
#
# Assumes `mempalace` is on PATH (pip install mempalace, or uv run mempalace from the repo).

set -euo pipefail

DRY=""
SOURCES=()

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY="--dry-run" ;;
    cursor|copilot|factory) SOURCES+=("$arg") ;;
    *) echo "Unknown arg: $arg" >&2; exit 1 ;;
  esac
done

# Default: all sources
if [[ ${#SOURCES[@]} -eq 0 ]]; then
  SOURCES=(cursor copilot factory)
fi

CURSOR_DIR="${HOME}/.cursor/chats"
COPILOT_DIR="${HOME}/.copilot/session-state"
FACTORY_DIR="${HOME}/.factory/sessions"

echo ""
echo "======================================================="
echo "  MemPalace — Mine All Sessions"
echo "======================================================="
[[ -n "$DRY" ]] && echo "  DRY RUN — nothing will be filed"
echo ""

for source in "${SOURCES[@]}"; do
  case "$source" in
    cursor)
      if [[ -d "$CURSOR_DIR" ]]; then
        echo "--- Cursor AI ---"
        mempalace mine "$CURSOR_DIR" --mode cursor --wing cursor_chats $DRY
      else
        echo "  [SKIP] Cursor: $CURSOR_DIR not found"
      fi
      ;;
    copilot)
      if [[ -d "$COPILOT_DIR" ]]; then
        echo "--- GitHub Copilot CLI ---"
        mempalace mine "$COPILOT_DIR" --mode convos --wing copilot_sessions $DRY
      else
        echo "  [SKIP] Copilot: $COPILOT_DIR not found"
      fi
      ;;
    factory)
      if [[ -d "$FACTORY_DIR" ]]; then
        echo "--- Factory.ai ---"
        mempalace mine "$FACTORY_DIR" --mode convos --wing factory_sessions $DRY
      else
        echo "  [SKIP] Factory: $FACTORY_DIR not found"
      fi
      ;;
  esac
done

echo ""
echo "======================================================="
echo "  Done. Search with: mempalace search \"<query>\""
echo "======================================================="
