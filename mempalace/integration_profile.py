from __future__ import annotations

import os
import shlex
from pathlib import Path

DEFAULT_CLI_COMMAND = "mempalace"
DEFAULT_SERVER_MODULE = "mempalace.mcp_server"
DEFAULT_PYTHON_COMMAND = "python"
DEFAULT_HOOK_STATE_DIR = os.path.join(os.path.expanduser("~/.mempalace"), "hook_state")


def cli_command() -> str:
    return os.environ.get("MEMPALACE_COMMAND", DEFAULT_CLI_COMMAND)


def python_command() -> str:
    return os.environ.get("MEMPALACE_PYTHON", DEFAULT_PYTHON_COMMAND)


def hook_state_dir() -> str:
    return os.path.expanduser(
        os.environ.get("MEMPALACE_HOOK_STATE_DIR", DEFAULT_HOOK_STATE_DIR)
    )


def server_args(palace_path: str | None = None) -> list[str]:
    args = ["-m", DEFAULT_SERVER_MODULE]
    if palace_path:
        args.extend(["--palace", str(Path(palace_path).expanduser())])
    return args


def server_command(palace_path: str | None = None) -> str:
    parts = [python_command(), *server_args(palace_path)]
    return " ".join(shlex.quote(part) for part in parts)


def manifest_profile() -> dict:
    return {
        "command": python_command(),
        "args": server_args(),
    }
