#!/usr/bin/env python3
"""setup_check.py — Verify mempalace is installed when plugin is first enabled.

Setup/SessionStart hook. Checks if the mempalace package is importable.
If not, detects common install locations (pipx, uv) and tells the user
how to fix the MCP server configuration.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def find_mempalace_python():
    """Try to find a Python interpreter that has mempalace installed."""
    candidates = []

    # Check pipx venv
    pipx_venv = Path.home() / ".local" / "share" / "pipx" / "venvs" / "mempalace" / "bin" / "python"
    if pipx_venv.exists():
        candidates.append(str(pipx_venv))

    # Check uv tool
    uv_venv = Path.home() / ".local" / "share" / "uv" / "tools" / "mempalace" / "bin" / "python"
    if uv_venv.exists():
        candidates.append(str(uv_venv))

    # Check common brew python paths
    for brew_python in ["/opt/homebrew/bin/python3", "/usr/local/bin/python3"]:
        if os.path.exists(brew_python):
            candidates.append(brew_python)

    for python_path in candidates:
        try:
            result = subprocess.run(
                [python_path, "-c", "import mempalace"],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                return python_path
        except Exception:
            pass

    return None


def main():
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        pass

    # Check if system python3 can import mempalace
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import mempalace"],
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            return  # All good
    except Exception:
        pass

    # System python can't import it — try to find it elsewhere
    found = find_mempalace_python()

    if found:
        msg = (
            f"MemPalace plugin: the mempalace package is not available to the system python3, "
            f"but it was found at: {found}\n\n"
            f"The MCP server may not work with the default configuration. "
            f"To fix this, run:\n"
            f"  claude mcp add mempalace -- {found} -m mempalace.mcp_server\n\n"
            f"Or reinstall mempalace so it is available to the system Python."
        )
    else:
        msg = (
            "MemPalace plugin: the mempalace Python package is not installed. "
            "The MCP server will not work without it.\n\n"
            "Install with one of:\n"
            "  pipx install mempalace\n"
            "  uv tool install mempalace\n"
            "  pip install --user mempalace\n\n"
            "If you installed via pipx, also run:\n"
            "  claude mcp add mempalace -- "
            "~/.local/share/pipx/venvs/mempalace/bin/python -m mempalace.mcp_server"
        )

    print(json.dumps({"additionalContext": msg}))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
