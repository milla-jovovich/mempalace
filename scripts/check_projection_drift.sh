#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

TRACKED_PATHS=(
  "semantics/cold/mempalace.runtime.projected.json"
  "semantics/cold/runtime-registry.unit.projected.jsonld"
  "semantics/cold/search.unit.projected.jsonld"
  "semantics/cold/mine.unit.projected.jsonld"
  "semantics/cold/hook-stop.unit.projected.jsonld"
  "semantics/cold/hook-precompact.unit.projected.jsonld"
  "mempalace/runtime_profile.json"
  "mempalace/cli_registry.json"
  "mempalace/mcp_tool_registry.json"
  ".claude-plugin/.mcp.json"
  ".claude-plugin/plugin.json"
  ".claude-plugin/hooks/hooks.json"
  ".codex-plugin/plugin.json"
  ".codex-plugin/hooks.json"
)

bash scripts/regen_spine.sh

if ! git diff --quiet -- "${TRACKED_PATHS[@]}"; then
  echo "Projection drift detected in generated runtime artifacts."
  echo
  git diff -- "${TRACKED_PATHS[@]}"
  exit 1
fi

echo "Projection drift check passed."
