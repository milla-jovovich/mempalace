#!/usr/bin/env python3
"""
agents.py — Specialist agent registry for MemPalace.

The README promises that specialist agents live in ~/.mempalace/agents/*.json
and can be discovered at runtime. This module keeps that contract small and
local: JSON files on disk, a thin loader, and a default scaffold so first-run
users have something usable immediately after `mempalace init`.
"""

import json
from pathlib import Path
from typing import Optional


# These defaults mirror the public README examples. Keeping them in code means
# `mempalace init` can create a working registry instead of leaving the feature
# half-configured for new users.
DEFAULT_AGENT_SPECS = [
    {
        "name": "reviewer",
        "focus": "Code quality, regressions, missing tests, and recurring bug patterns.",
        "description": "Tracks review findings, risky changes, and edge cases worth remembering.",
        "prompt_hint": "Use when reviewing diffs, test gaps, and behavioural regressions.",
    },
    {
        "name": "architect",
        "focus": "Design decisions, tradeoffs, interfaces, and longer-term technical direction.",
        "description": "Keeps the history behind architectural calls so future changes have context.",
        "prompt_hint": "Use when planning refactors, new systems, or cross-cutting design choices.",
    },
    {
        "name": "ops",
        "focus": "Deployments, incidents, infrastructure, and production follow-up.",
        "description": "Remembers outages, mitigation steps, and operational sharp edges.",
        "prompt_hint": "Use when triaging reliability, release, and runtime issues.",
    },
]


def _registry_root(config_dir: Optional[Path] = None) -> Path:
    """Resolve the agent registry directory."""
    base = Path(config_dir) if config_dir else Path.home() / ".mempalace"
    return base / "agents"


def _agent_slug(name: str) -> str:
    """Convert a user-facing agent name into the stable filename/wing slug."""
    return name.strip().lower().replace(" ", "_")


def _agent_path(name: str, config_dir: Optional[Path] = None) -> Path:
    """Map an agent name to the JSON file that stores it."""
    return _registry_root(config_dir) / f"{_agent_slug(name)}.json"


def _normalize_agent(raw: dict, path: Path) -> dict:
    """
    Normalize a JSON record into the shape the MCP tool returns.

    The loader is intentionally forgiving because open-source users will hand-edit
    these files. Missing fields get sensible defaults instead of crashing the tool.
    """
    name = str(raw.get("name") or path.stem.replace("_", " ")).strip()
    slug = _agent_slug(name)
    wing = raw.get("wing") or f"wing_{slug}"
    room = raw.get("diary_room") or "diary"
    return {
        "name": name,
        "slug": slug,
        "focus": str(raw.get("focus", "")).strip(),
        "description": str(raw.get("description", "")).strip(),
        "prompt_hint": str(raw.get("prompt_hint", "")).strip(),
        "wing": wing,
        "diary_room": room,
        "path": str(path),
    }


def write_agent(agent: dict, config_dir: Optional[Path] = None) -> Path:
    """
    Persist one agent definition.

    The JSON is written with explicit fields so people can inspect and edit the
    registry without needing to read Python code first.
    """
    path = _agent_path(agent["name"], config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_agent(agent, path)
    payload = {
        "name": normalized["name"],
        "focus": normalized["focus"],
        "description": normalized["description"],
        "prompt_hint": normalized["prompt_hint"],
        "wing": normalized["wing"],
        "diary_room": normalized["diary_room"],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def ensure_default_agents(config_dir: Optional[Path] = None) -> list:
    """
    Create the README's default specialist agents if they do not exist yet.

    We only create missing files so existing community/user customizations are
    preserved verbatim.
    """
    created = []
    for spec in DEFAULT_AGENT_SPECS:
        path = _agent_path(spec["name"], config_dir)
        if path.exists():
            continue
        created.append(write_agent(spec, config_dir))
    return created


def list_agents(config_dir: Optional[Path] = None) -> dict:
    """
    Load every valid agent file and report parse errors separately.

    Returning errors alongside valid agents is more useful than failing the whole
    tool call because one hand-edited JSON file is malformed.
    """
    root = _registry_root(config_dir)
    root.mkdir(parents=True, exist_ok=True)

    agents = []
    errors = []
    for path in sorted(root.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("agent file must contain a JSON object")
            agents.append(_normalize_agent(raw, path))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append({"path": str(path), "error": str(exc)})

    return {
        "directory": str(root),
        "agents": agents,
        "count": len(agents),
        "errors": errors,
    }
