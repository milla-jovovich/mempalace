#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python}"
REPORT_DIR="$ROOT_DIR/.codespaces"
REPORT_FILE="$REPORT_DIR/bootstrap-report.json"
mkdir -p "$REPORT_DIR"

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

log "verifying Python 3.13 runtime"
"$PYTHON_BIN" - <<'PY'
import sys
assert sys.version_info[:2] == (3, 13), f"Expected Python 3.13, got {sys.version}"
print(sys.version)
PY

log "upgrading packaging/runtime tools"
"$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel hatchling uv

log "installing MemPalace editable with dev extras"
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

log "capturing registry surfaces"
"$PYTHON_BIN" -m mempalace.cli_ld registry runtime > "$REPORT_DIR/registry.runtime.json"
"$PYTHON_BIN" -m mempalace.cli_ld registry cli > "$REPORT_DIR/registry.cli.json"
"$PYTHON_BIN" -m mempalace.cli_ld registry mcp > "$REPORT_DIR/registry.mcp.json"
"$PYTHON_BIN" -m mempalace.cli_ld --help > "$REPORT_DIR/cli.help.txt"
"$PYTHON_BIN" -m mempalace.cli_ld mcp > "$REPORT_DIR/mcp.setup.txt"

log "validating runtime adapters and MCP wrapper visibility"
"$PYTHON_BIN" - <<'PY'
import json
import platform
import sys
from pathlib import Path

from mempalace.operation_registry import cli_registry_view, mcp_tool_registry_view, projected_registry, visible_mcp_tools
from mempalace.mcp_server_ld import _visible_tools

runtime = projected_registry()
cli_view = cli_registry_view()
mcp_view = mcp_tool_registry_view()
visible_tools = _visible_tools()
visible_tool_names = [tool.get("name") for tool in visible_tools]

assert sys.version_info[:2] == (3, 13), sys.version
assert runtime.get("module_entry") == "mempalace.mcp_server_ld", runtime
assert any(op.get("name") == "registry" for op in cli_view.get("operations", [])), cli_view
assert any(tool.get("name") == "mempalace_runtime_registry" for tool in mcp_view.get("tools", [])), mcp_view
assert "mempalace_runtime_registry" in visible_tool_names, visible_tool_names
assert "mempalace_search" in visible_tool_names, visible_tool_names

report = {
    "python_version": sys.version,
    "platform": platform.platform(),
    "runtime_module_entry": runtime.get("module_entry"),
    "cli_operation_count": len(cli_view.get("operations", [])),
    "mcp_tool_count": len(mcp_view.get("tools", [])),
    "visible_mcp_wrapper_tools": visible_tool_names,
    "operation_registry_visible_mcp_tools": visible_mcp_tools(),
}

report_path = Path('.codespaces/bootstrap-report.json')
report_path.write_text(json.dumps(report, indent=2) + "\n", encoding='utf-8')
print(json.dumps(report, indent=2))
PY

log "bootstrap complete; report written to $REPORT_FILE"
