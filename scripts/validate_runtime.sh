#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python}"
REPORT_DIR="$ROOT_DIR/.codespaces"
REPORT_FILE="$REPORT_DIR/bootstrap-report.json"
mkdir -p "$REPORT_DIR"

"$PYTHON_BIN" - <<'PY'
import sys
assert sys.version_info[:2] == (3, 13), f"Expected Python 3.13, got {sys.version}"
print(sys.version)
PY

"$PYTHON_BIN" -m compileall mempalace >/dev/null
"$PYTHON_BIN" scripts/write_projection_manifest.py > "$REPORT_DIR/projection-integrity.path"

"$PYTHON_BIN" -m mempalace.cli_ld registry runtime > "$REPORT_DIR/registry.runtime.json"
"$PYTHON_BIN" -m mempalace.cli_ld registry cli > "$REPORT_DIR/registry.cli.json"
"$PYTHON_BIN" -m mempalace.cli_ld registry mcp > "$REPORT_DIR/registry.mcp.json"
"$PYTHON_BIN" -m mempalace.cli_ld --help > "$REPORT_DIR/cli.help.txt"
"$PYTHON_BIN" -m mempalace.cli_ld mcp > "$REPORT_DIR/mcp.setup.txt"

"$PYTHON_BIN" - <<'PY'
import json
import platform
import subprocess
import sys
from pathlib import Path

from mempalace.operation_registry import cli_registry_view, mcp_tool_registry_view, projected_registry, visible_mcp_tools
from mempalace.mcp_server_ld import _visible_tools

runtime = projected_registry()
cli_view = cli_registry_view()
mcp_view = mcp_tool_registry_view()
visible_tools = _visible_tools()
visible_tool_names = [tool.get("name") for tool in visible_tools]
projection_manifest_path = Path('.codespaces/projection-integrity.json')
projection_manifest = json.loads(projection_manifest_path.read_text(encoding='utf-8'))

assert sys.version_info[:2] == (3, 13), sys.version
assert runtime.get("module_entry") == "mempalace.mcp_server_ld", runtime
assert any(op.get("name") == "registry" for op in cli_view.get("operations", [])), cli_view
assert any(tool.get("name") == "mempalace_runtime_registry" for tool in mcp_view.get("tools", [])), mcp_view
assert "mempalace_runtime_registry" in visible_tool_names, visible_tool_names
assert "mempalace_search" in visible_tool_names, visible_tool_names
assert projection_manifest.get("algorithm") == "blake3", projection_manifest
assert all(entry.get("exists") for entry in projection_manifest.get("tracked_paths", [])), projection_manifest

try:
    git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
except Exception:
    git_sha = "unknown"

report = {
    "python_version": sys.version,
    "platform": platform.platform(),
    "git_sha": git_sha,
    "runtime_module_entry": runtime.get("module_entry"),
    "cli_operation_count": len(cli_view.get("operations", [])),
    "mcp_tool_count": len(mcp_view.get("tools", [])),
    "visible_mcp_wrapper_tools": visible_tool_names,
    "operation_registry_visible_mcp_tools": visible_mcp_tools(),
    "projection_integrity_algorithm": projection_manifest.get("algorithm"),
    "projection_integrity_path": str(projection_manifest_path),
}

report_path = Path('.codespaces/bootstrap-report.json')
report_path.write_text(json.dumps(report, indent=2) + "\n", encoding='utf-8')
print(json.dumps(report, indent=2))
PY

echo "bootstrap report: $REPORT_FILE"
