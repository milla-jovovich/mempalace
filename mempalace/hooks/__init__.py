"""MemPalace hooks — auto-save scripts for Claude Code and Codex CLI."""

import importlib.resources
from pathlib import Path


def hooks_dir() -> Path:
    """Return the absolute path to the installed hooks directory."""
    return Path(str(importlib.resources.files("mempalace.hooks")))


def hook_path(name: str) -> Path:
    """Return the absolute path to a specific hook script.

    Raises FileNotFoundError if the named hook does not exist.
    """
    p = hooks_dir() / name
    if not p.exists():
        raise FileNotFoundError(f"Hook not found: {p}")
    return p
