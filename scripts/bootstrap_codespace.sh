#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python}"

log() {
  printf '\n[%s] %s\n' "mempalace-bootstrap" "$1"
}

log "verifying Python 3.13 runtime"
"$PYTHON_BIN" - <<'PY'
import sys
assert sys.version_info[:2] == (3, 13), f"Expected Python 3.13, got {sys.version}"
print(sys.version)
PY

log "upgrading packaging/runtime tools"
"$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel hatchling

log "installing MemPalace editable"
"$PYTHON_BIN" -m pip install -e .

log "regenerating spine projections"
bash scripts/regen_spine.sh

log "validating runtime surfaces"
bash scripts/validate_runtime.sh

log "bootstrap complete"
