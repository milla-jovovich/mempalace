#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from blake3 import blake3

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT_DIR / ".codespaces" / "projection-integrity.json"
TRACKED_PATHS = [
    "semantics/cold/mempalace.runtime.projected.json",
    "semantics/cold/runtime-registry.unit.projected.jsonld",
    "semantics/cold/search.unit.projected.jsonld",
    "semantics/cold/mine.unit.projected.jsonld",
    "semantics/cold/hook-stop.unit.projected.jsonld",
    "semantics/cold/hook-precompact.unit.projected.jsonld",
    "mempalace/runtime_profile.json",
    "mempalace/cli_registry.json",
    "mempalace/mcp_tool_registry.json",
    ".claude-plugin/.mcp.json",
    ".claude-plugin/plugin.json",
    ".claude-plugin/hooks/hooks.json",
    ".codex-plugin/plugin.json",
    ".codex-plugin/hooks.json",
]


@dataclass(frozen=True)
class ProjectionEntry:
    path: str
    exists: bool
    blake3: str | None
    size_bytes: int | None


def hash_file(path: Path) -> tuple[str, int]:
    hasher = blake3()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest(), path.stat().st_size


def build_manifest(paths: Iterable[str]) -> dict:
    entries: list[ProjectionEntry] = []
    for rel_path in paths:
        path = ROOT_DIR / rel_path
        if path.exists() and path.is_file():
            digest, size_bytes = hash_file(path)
            entries.append(
                ProjectionEntry(
                    path=rel_path,
                    exists=True,
                    blake3=digest,
                    size_bytes=size_bytes,
                )
            )
        else:
            entries.append(
                ProjectionEntry(
                    path=rel_path,
                    exists=False,
                    blake3=None,
                    size_bytes=None,
                )
            )
    return {
        "algorithm": "blake3",
        "root": str(ROOT_DIR),
        "tracked_paths": [entry.__dict__ for entry in entries],
    }


def main() -> int:
    output = DEFAULT_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_manifest(TRACKED_PATHS), indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
