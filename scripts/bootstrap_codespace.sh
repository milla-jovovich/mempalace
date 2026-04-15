#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python}"

log() {
  printf '\n[%s] %s\n' "mempalace-bootstrap" "$1"
}

frame_unit() {
  local node_id="$1"
  local out_file="$2"
  "$PYTHON_BIN" tools/mempalace_execution_kit/frame_runtime_registry_from_binding_graph.py \
    semantics/cold/mempalace.binding.graph.jsonld \
    "$node_id" \
    "$out_file"
}

log "upgrading packaging toolchain"
"$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel hatchling

log "installing mempalace editable with dev extras"
"$PYTHON_BIN" -m pip install -e '.[dev]'

log "regenerating runtime and package-local projection views"
"$PYTHON_BIN" tools/mempalace_execution_kit/project_mempalace_integrations.py \
  semantics/hot/mempalace.operations.registry.yamlld \
  semantics/hot/mempalace.integration.profile.yamlld \
  semantics/cold/mempalace.runtime.projected.json \
  "$ROOT_DIR"

log "framing canonical unit nodes from the cold binding graph"
frame_unit 'did:webvh:{SCID}:github.com:Fleet-to-Force:mempalace#op/runtime-registry' 'semantics/cold/runtime-registry.unit.projected.jsonld'
frame_unit 'did:webvh:{SCID}:github.com:Fleet-to-Force:mempalace#op/search' 'semantics/cold/search.unit.projected.jsonld'
frame_unit 'did:webvh:{SCID}:github.com:Fleet-to-Force:mempalace#op/mine' 'semantics/cold/mine.unit.projected.jsonld'
frame_unit 'did:webvh:{SCID}:github.com:Fleet-to-Force:mempalace#op/hook-stop' 'semantics/cold/hook-stop.unit.projected.jsonld'
frame_unit 'did:webvh:{SCID}:github.com:Fleet-to-Force:mempalace#op/hook-precompact' 'semantics/cold/hook-precompact.unit.projected.jsonld'

log "compiling package sources"
"$PYTHON_BIN" -m compileall mempalace >/dev/null

log "validating packaged registry views"
"$PYTHON_BIN" -m mempalace.cli_ld registry runtime >/tmp/mempalace_registry_runtime.json
"$PYTHON_BIN" -m mempalace.cli_ld registry cli >/tmp/mempalace_registry_cli.json
"$PYTHON_BIN" -m mempalace.cli_ld registry mcp >/tmp/mempalace_registry_mcp.json

log "validating runtime adapters and MCP wrapper visibility"
"$PYTHON_BIN" - <<'PY'
from mempalace.operation_registry import cli_registry_view, mcp_tool_registry_view, projected_registry
from mempalace.mcp_server_ld import _visible_tools

runtime = projected_registry()
cli_view = cli_registry_view()
mcp_view = mcp_tool_registry_view()
visible_tools = _visible_tools()

assert runtime.get("module_entry") == "mempalace.mcp_server_ld", runtime
assert any(op.get("name") == "registry" for op in cli_view.get("operations", [])), cli_view
assert any(tool.get("name") == "mempalace_runtime_registry" for tool in mcp_view.get("tools", [])), mcp_view
assert any(tool.get("name") == "mempalace_runtime_registry" for tool in visible_tools), visible_tools

print("runtime module entry:", runtime.get("module_entry"))
print("cli operations:", len(cli_view.get("operations", [])))
print("mcp tools:", len(mcp_view.get("tools", [])))
print("visible MCP wrapper tools:", len(visible_tools))
PY

log "bootstrap complete"
