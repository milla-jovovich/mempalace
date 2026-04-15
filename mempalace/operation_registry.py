from __future__ import annotations

from functools import lru_cache

from .integration_profile import runtime_profile


@lru_cache(maxsize=1)
def operations() -> list[dict]:
    profile = runtime_profile()
    ops = profile.get("operations", [])
    return [op for op in ops if isinstance(op, dict)]


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
    op = mcp_operation_map().get(tool_name)
    if op and op.get("description"):
        return op["description"]
    return fallback


def mcp_exposure(tool_name: str, default: str = "public") -> str:
    op = mcp_operation_map().get(tool_name)
    if not op:
        return default
    return op.get("mcp", {}).get("exposure", default)


def cli_exposure(command_name: str, default: str = "public") -> str:
    op = cli_operation_map().get(command_name)
    if not op:
        return default
    return op.get("cli", {}).get("exposure", default)


def projected_registry() -> dict:
    profile = runtime_profile()
    return {
        "package": profile.get("package", "mempalace"),
        "command": profile.get("command", "mempalace"),
        "module_entry": profile.get("module_entry", "mempalace.mcp_server"),
        "hidden_dir": profile.get("hidden_dir", ".mempalace"),
        "runtime": profile.get("runtime", {}),
        "operations": operations(),
        "plugin_profiles": profile.get("plugin_profiles", []),
        "collections": profile.get("collections", []),
    }
