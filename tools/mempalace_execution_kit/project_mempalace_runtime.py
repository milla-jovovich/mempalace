#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

RUNTIME_REGISTRY_OLD_ID = "did:webvh:{SCID}:github.com:Fleet-to-Force:mempalace#op/registry"
RUNTIME_REGISTRY_CANONICAL_ID = "did:webvh:{SCID}:github.com:Fleet-to-Force:mempalace#op/runtime-registry"


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def canonical_capability_id(value: str | None) -> str | None:
    if value == RUNTIME_REGISTRY_OLD_ID:
        return RUNTIME_REGISTRY_CANONICAL_ID
    return value


def project_runtime(ops_doc: dict, profile_doc: dict) -> dict:
    operations = []
    for item in ops_doc.get("operations", []) or []:
        operations.append(
            {
                "id": canonical_capability_id(item.get("@id")),
                "category": item.get("category"),
                "description": item.get("description"),
                "enabled": item.get("enabled", True),
                "cli": item.get("cli", {}),
                "mcp": item.get("mcp", {}),
            }
        )

    runtime = profile_doc.get("runtime", {})
    plugins = profile_doc.get("pluginProfiles", []) or []
    collections = profile_doc.get("collections", []) or []

    return {
        "package": profile_doc.get("packageName", "mempalace"),
        "command": profile_doc.get("commandName", "mempalace"),
        "module_entry": profile_doc.get("moduleEntry", "mempalace.mcp_server_ld"),
        "hidden_dir": profile_doc.get("hiddenDir", ".mempalace"),
        "repo_url": profile_doc.get("repoUrl", "https://github.com/Fleet-to-Force/mempalace"),
        "runtime": runtime,
        "operations": operations,
        "plugin_profiles": plugins,
        "collections": collections,
    }


def main() -> int:
    if len(sys.argv) not in (3, 4):
        print(
            "Usage: python project_mempalace_runtime.py <operations.registry.yamlld> <integration.profile.yamlld> [output.json]"
        )
        return 2

    ops_doc = load_yaml(Path(sys.argv[1]).expanduser().resolve())
    profile_doc = load_yaml(Path(sys.argv[2]).expanduser().resolve())
    projected = project_runtime(ops_doc, profile_doc)

    if len(sys.argv) == 4:
        out = Path(sys.argv[3]).expanduser().resolve()
        out.write_text(json.dumps(projected, indent=2) + "\n", encoding="utf-8")
        print(str(out))
        return 0

    print(json.dumps(projected, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
