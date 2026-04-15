from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .integration_profile import runtime_profile

PACKAGE_DIR = Path(__file__).resolve().parent
CLI_REGISTRY_PATH = PACKAGE_DIR / "cli_registry.json"
MCP_TOOL_REGISTRY_PATH = PACKAGE_DIR / "mcp_tool_registry.json"


def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


@lru_cache(maxsize=1)
def operations() -> list[dict]:
    profile = runtime_profile()
    ops = profile.get("operations", [])
    return [op for op in ops if isinstance(op, dict)]


@lru_cache(maxsize=1)
def cli_registry_view() -> dict:
    data = _load_json(CLI_REGISTRY_PATH)
    if data:
        return data

    generated = []
    for op in operations():
        cli = op.get("cli", {})
        command = cli.get("command")
        exposure = cli.get("exposure", "public")
        if not command or exposure == "internal":
            continue
        generated.append(
            {
                "name": command,
                "description": op.get("description", ""),
                "exposure": exposure,
                "capability": op.get("id"),
            }
        )
    return {
        "command": runtime_profile().get("command", "mempalace"),
        "view": "cli-registry",
        "operations": generated,
    }


@lru_cache(maxsize=1)
def mcp_tool_registry_view() -> dict:
    data = _load_json(MCP_TOOL_REGISTRY_PATH)
    if data:
        return data

    generated = []
    for op in operations():
        mcp = op.get("mcp", {})
        tool = mcp.get("tool")
        exposure = mcp.get("exposure", "public")
        if not tool or exposure == "hidden":
            continue
        generated.append(
            {
                "name": tool,
                "description": op.get("description", ""),
                "exposure": exposure,
                "capability": op.get("id"),
            }
        )
    return {
        "server": runtime_profile().get("package", "mempalace"),
        "view": "mcp-tool-registry",
        "tools": generated,
    }


@lru_cache(maxsize=1)
def mcp_operation_map() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for op in operations():
        mcp = op.get("mcp", {})
        tool = mcp.get("tool")
        if tool:
            out[tool] = op
    return out


@lru_cache(maxsize=1)
def cli_operation_map() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for op in operations():
        cli = op.get("cli", {})
        command = cli.get("command")
        if command:
            out[command] = op
    return out


def mcp_description(tool_name: str, fallback: str) -> str:
    for entry in mcp_tool_registry_view().get("tools", []):
        if entry.get("name") == tool_name and entry.get("description"):
            return entry["description"]
    op = mcp_operation_map().get(tool_name)
    if op and op.get("description"):
        return op["description"]
    return fallback


def cli_description(command_name: str, fallback: str) -> str:
    for entry in cli_registry_view().get("operations", []):
        if entry.get("name") == command_name and entry.get("description"):
            return entry["description"]
    op = cli_operation_map().get(command_name)
    if op and op.get("description"):
        return op["description"]
    return fallback


def mcp_exposure(tool_name: str, default: str = "public") -> str:
    for entry in mcp_tool_registry_view().get("tools", []):
        if entry.get("name") == tool_name:
            return entry.get("exposure", default)
    op = mcp_operation_map().get(tool_name)
    if not op:
        return default
    return op.get("mcp", {}).get("exposure", default)


def cli_exposure(command_name: str, default: str = "public") -> str:
    for entry in cli_registry_view().get("operations", []):
        if entry.get("name") == command_name:
            return entry.get("exposure", default)
    op = cli_operation_map().get(command_name)
    if not op:
        return default
    return op.get("cli", {}).get("exposure", default)


def visible_cli_commands() -> list[str]:
    return [entry.get("name") for entry in cli_registry_view().get("operations", []) if entry.get("name")]


def visible_mcp_tools() -> list[str]:
    return [entry.get("name") for entry in mcp_tool_registry_view().get("tools", []) if entry.get("name")]


def projected_registry() -> dict:
    profile = runtime_profile()
    return {
        "package": profile.get("package", "mempalace"),
        "command": profile.get("command", "mempalace"),
        "module_entry": profile.get("module_entry", "mempalace.mcp_server_ld"),
        "hidden_dir": profile.get("hidden_dir", ".mempalace"),
        "runtime": profile.get("runtime", {}),
        "operations": operations(),
        "plugin_profiles": profile.get("plugin_profiles", []),
        "collections": profile.get("collections", []),
    }
