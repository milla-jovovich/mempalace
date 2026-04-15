#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python}"

frame_unit() {
  local node_id="$1"
  local out_file="$2"
  "$PYTHON_BIN" tools/mempalace_execution_kit/frame_runtime_registry_from_binding_graph.py \
    semantics/cold/mempalace.binding.graph.jsonld \
    "$node_id" \
    "$out_file"
}

"$PYTHON_BIN" tools/mempalace_execution_kit/project_mempalace_integrations.py \
  semantics/hot/mempalace.operations.registry.yamlld \
  semantics/hot/mempalace.integration.profile.yamlld \
  semantics/cold/mempalace.runtime.projected.json \
  "$ROOT_DIR"

frame_unit 'did:webvh:{SCID}:github.com:Fleet-to-Force:mempalace#op/runtime-registry' 'semantics/cold/runtime-registry.unit.projected.jsonld'
frame_unit 'did:webvh:{SCID}:github.com:Fleet-to-Force:mempalace#op/search' 'semantics/cold/search.unit.projected.jsonld'
frame_unit 'did:webvh:{SCID}:github.com:Fleet-to-Force:mempalace#op/mine' 'semantics/cold/mine.unit.projected.jsonld'
frame_unit 'did:webvh:{SCID}:github.com:Fleet-to-Force:mempalace#op/hook-stop' 'semantics/cold/hook-stop.unit.projected.jsonld'
frame_unit 'did:webvh:{SCID}:github.com:Fleet-to-Force:mempalace#op/hook-precompact' 'semantics/cold/hook-precompact.unit.projected.jsonld'
