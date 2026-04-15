from __future__ import annotations

import json
import sys

from . import mcp_server as legacy_mcp
from .operation_registry import (
    mcp_description,
    mcp_exposure,
    mcp_tool_registry_view,
    projected_registry,
    visible_mcp_tools,
)


def tool_runtime_registry():
    return projected_registry()


TOOLS = {name: dict(spec) for name, spec in legacy_mcp.TOOLS.items()}
TOOLS["mempalace_runtime_registry"] = {
    "description": "Return the projected MemPalace runtime registry, including operations, integration defaults, plugin profiles, and collection identities.",
    "input_schema": {"type": "object", "properties": {}},
    "handler": tool_runtime_registry,
}

for name, spec in list(TOOLS.items()):
    spec["description"] = mcp_description(name, spec.get("description", ""))
    TOOLS[name] = spec


SUPPORTED_PROTOCOL_VERSIONS = legacy_mcp.SUPPORTED_PROTOCOL_VERSIONS


def _visible_tools() -> list[dict]:
    visible = []
    seen: set[str] = set()

    for name in visible_mcp_tools():
        spec = TOOLS.get(name)
        if not spec or mcp_exposure(name, "public") == "hidden":
            continue
        visible.append(
            {
                "name": name,
                "description": spec["description"],
                "inputSchema": spec["input_schema"],
            }
        )
        seen.add(name)

    for name, spec in TOOLS.items():
        if name in seen or mcp_exposure(name, "public") == "hidden":
            continue
        visible.append(
            {
                "name": name,
                "description": spec["description"],
                "inputSchema": spec["input_schema"],
            }
        )
    return visible


def handle_request(request):
    method = request.get("method") or ""
    params = request.get("params") or {}
    req_id = request.get("id")

    if method == "initialize":
        client_version = params.get("protocolVersion", SUPPORTED_PROTOCOL_VERSIONS[-1])
        negotiated = (
            client_version
            if client_version in SUPPORTED_PROTOCOL_VERSIONS
            else SUPPORTED_PROTOCOL_VERSIONS[0]
        )
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": negotiated,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mempalace", "version": legacy_mcp.__version__},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method.startswith("notifications/"):
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": _visible_tools()}}
    if method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments") or {}
        if tool_name not in TOOLS:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
            }

        import inspect

        schema_props = TOOLS[tool_name]["input_schema"].get("properties", {})
        try:
            handler = TOOLS[tool_name]["handler"]
            sig = inspect.signature(handler)
            accepts_var_keyword = any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            )
        except (ValueError, TypeError):
            accepts_var_keyword = False
        if not accepts_var_keyword:
            tool_args = {k: v for k, v in tool_args.items() if k in schema_props}
        for key, value in list(tool_args.items()):
            prop_schema = schema_props.get(key, {})
            declared_type = prop_schema.get("type")
            try:
                if declared_type == "integer" and not isinstance(value, int):
                    tool_args[key] = int(value)
                elif declared_type == "number" and not isinstance(value, (int, float)):
                    tool_args[key] = float(value)
            except (ValueError, TypeError):
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": f"Invalid value for parameter '{key}'"},
                }
        try:
            tool_args.pop("wait_for_previous", None)
            result = TOOLS[tool_name]["handler"](**tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]},
            }
        except Exception:
            legacy_mcp.logger.exception(f"Tool error in {tool_name}")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": "Internal tool error"},
            }

    if req_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"},
    }


def main():
    legacy_mcp.logger.info("MemPalace MCP Server (LD wrapper) starting...")
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            request = json.loads(line)
            response = handle_request(request)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
        except KeyboardInterrupt:
            break
        except Exception as e:
            legacy_mcp.logger.error(f"Server error: {e}")


if __name__ == "__main__":
    main()
