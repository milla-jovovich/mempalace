from __future__ import annotations

import json
import os
import shlex
from functools import lru_cache
from pathlib import Path

DEFAULT_CLI_COMMAND = "mempalace"
DEFAULT_SERVER_MODULE = "mempalace.mcp_server_ld"
DEFAULT_MCP_COMMAND = "mempalace-mcp"
DEFAULT_PYTHON_COMMAND = "python"
DEFAULT_HOOK_STATE_DIR = os.path.join(os.path.expanduser("~/.mempalace"), "hook_state")
PACKAGE_RUNTIME_PROFILE_PATH = Path(__file__).resolve().with_name("runtime_profile.json")
REPO_RUNTIME_PROFILE_PATH = (
    Path(__file__).resolve().parent.parent / "semantics" / "cold" / "mempalace.runtime.projected.json"
)


@lru_cache(maxsize=1)
def runtime_profile() -> dict:
    env_path = os.environ.get("MEMPALACE_RUNTIME_PROFILE")
    candidates = []
    if env_path:
        candidates.append(Path(env_path).expanduser())
    candidates.extend([PACKAGE_RUNTIME_PROFILE_PATH, REPO_RUNTIME_PROFILE_PATH])

    for path in candidates:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
    return {}


def _runtime_value(*keys, default=None):
    current = runtime_profile()
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def cli_command() -> str:
    return os.environ.get(
        "MEMPALACE_COMMAND", _runtime_value("command", default=DEFAULT_CLI_COMMAND)
    )


def mcp_command() -> str:
    return os.environ.get(
        "MEMPALACE_MCP_COMMAND",
        _runtime_value("runtime", "mcpCommand", default=DEFAULT_MCP_COMMAND),
    )


def python_command() -> str:
    return os.environ.get(
        "MEMPALACE_PYTHON",
        _runtime_value("runtime", "pythonCommand", default=DEFAULT_PYTHON_COMMAND),
    )


def module_entry() -> str:
    return _runtime_value("module_entry", default=DEFAULT_SERVER_MODULE)


def hook_state_dir() -> str:
    return os.path.expanduser(
        os.environ.get(
            "MEMPALACE_HOOK_STATE_DIR",
            _runtime_value("runtime", "hookStateDir", default=DEFAULT_HOOK_STATE_DIR),
        )
    )


def server_args(palace_path: str | None = None) -> list[str]:
    args = ["-m", module_entry()]
    if palace_path:
        args.extend(["--palace", str(Path(palace_path).expanduser())])
    return args


def server_command(palace_path: str | None = None) -> str:
    parts = [python_command(), *server_args(palace_path)]
    return " ".join(shlex.quote(part) for part in parts)


def manifest_profile() -> dict:
    return {
        "command": mcp_command(),
        "args": [],
    }
