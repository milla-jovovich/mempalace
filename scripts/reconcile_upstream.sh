#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python}"
CURRENT_REF="${CURRENT_REF:-HEAD}"
INCOMING_REF="${INCOMING_REF:-develop}"
REPORT_PATH="${REPORT_PATH:-.codespaces/reconcile-report.json}"

ARGS=(
  --manifest tools/mempalace_execution_kit/mempalace.reconcile.manifest.json
  --current-ref "$CURRENT_REF"
  --incoming-ref "$INCOMING_REF"
  --report "$REPORT_PATH"
)

if [[ "${APPLY_RECONCILE:-0}" == "1" ]]; then
  ARGS+=(--apply)
fi

"$PYTHON_BIN" tools/mempalace_execution_kit/reconcile_refs.py "${ARGS[@]}"
