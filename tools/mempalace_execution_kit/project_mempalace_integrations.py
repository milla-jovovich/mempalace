#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def runtime_projection(ops_doc: dict, profile_doc: dict) -> dict:
    operations = []
    for item in ops_doc.get("operations", []) or []:
        operations.append(
            {
                "id": item.get("@id"),
                "category": item.get("category"),
                "description": item.get("description"),
                "enabled": item.get("enabled", True),
                "cli": item.get("cli", {}),
                "mcp": item.get("mcp", {}),
            }
        )

    return {
        "package": profile_doc.get("packageName", "mempalace"),
        "command": profile_doc.get("commandName", "mempalace"),
        "module_entry": profile_doc.get("moduleEntry", "mempalace.mcp_server"),
        "hidden_dir": profile_doc.get("hiddenDir", ".mempalace"),
        "repo_url": profile_doc.get("repoUrl", "https://github.com/Fleet-to-Force/mempalace"),
        "runtime": profile_doc.get("runtime", {}),
        "operations": operations,
        "plugin_profiles": profile_doc.get("pluginProfiles", []) or [],
        "collections": profile_doc.get("collections", []) or [],
    }


def _find_plugin(runtime: dict, category: str) -> dict:
    for plugin in runtime.get("plugin_profiles", []):
        if plugin.get("category") == category:
            return plugin
    raise KeyError(f"missing plugin profile: {category}")


def claude_mcp_manifest(runtime: dict) -> dict:
    plugin = _find_plugin(runtime, "claude-plugin")
    return {
        runtime["package"]: {
            "command": plugin.get("manifest", {}).get("mcpCommand", runtime.get("runtime", {}).get("mcpCommand", "mempalace-mcp")),
            "args": plugin.get("manifest", {}).get("args", []),
        }
    }


def claude_plugin_manifest(runtime: dict) -> dict:
    return {
        "name": runtime["package"],
        "version": "3.3.0",
        "description": "Give your AI a memory — mine projects and conversations into a searchable palace with MCP tools, auto-save hooks, and guided setup.",
        "author": {"name": "milla-jovovich"},
        "license": "MIT",
        "commands": [],
        "mcpServers": claude_mcp_manifest(runtime),
        "keywords": ["memory", "ai", "rag", "mcp", "chromadb", "palace", "search"],
        "repository": runtime.get("repo_url", "https://github.com/Fleet-to-Force/mempalace"),
    }


def claude_hooks_manifest(runtime: dict) -> dict:
    plugin = _find_plugin(runtime, "claude-plugin")
    hooks = plugin.get("hooks", {})
    return {
        "description": "MemPalace auto-save and pre-compact hooks",
        "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": hooks.get("stop"), "timeout": 30}]}],
            "PreCompact": [{"hooks": [{"type": "command", "command": hooks.get("precompact"), "timeout": 30}]}],
        },
    }


def codex_plugin_manifest(runtime: dict) -> dict:
    plugin = _find_plugin(runtime, "codex-plugin")
    return {
        "name": runtime["package"],
        "version": "3.3.0",
        "description": "Give your AI a memory — mine projects and conversations into a searchable palace with MCP tools, auto-save hooks, and guided setup.",
        "author": {"name": "milla-jovovich"},
        "homepage": runtime.get("repo_url", "https://github.com/Fleet-to-Force/mempalace"),
        "repository": runtime.get("repo_url", "https://github.com/Fleet-to-Force/mempalace"),
        "license": "MIT",
        "keywords": ["memory", "ai", "rag", "mcp", "chromadb", "palace", "search"],
        "skills": "./skills/",
        "hooks": "./hooks.json",
        "mcpServers": {
            runtime["package"]: {
                "command": plugin.get("manifest", {}).get("mcpCommand", runtime.get("runtime", {}).get("mcpCommand", "mempalace-mcp")),
                "args": plugin.get("manifest", {}).get("args", []),
            }
        },
        "interface": {
            "displayName": "MemPalace",
            "shortDescription": "AI memory system for Codex",
            "longDescription": "Give your AI a persistent memory — mine projects and conversations into a searchable palace backed by ChromaDB, with MCP tools, auto-save hooks, and guided skills.",
            "developerName": "milla-jovovich",
            "category": "Coding",
            "capabilities": ["Interactive", "Read", "Write"],
            "websiteURL": runtime.get("repo_url", "https://github.com/Fleet-to-Force/mempalace"),
            "privacyPolicyURL": runtime.get("repo_url", "https://github.com/Fleet-to-Force/mempalace"),
            "termsOfServiceURL": runtime.get("repo_url", "https://github.com/Fleet-to-Force/mempalace"),
            "defaultPrompt": [
                "Search my memories for recent decisions",
                "Mine this project into my memory palace",
                "Show my palace status and room counts",
            ],
            "brandColor": "#7C3AED",
        },
    }


def codex_hooks_manifest(runtime: dict) -> dict:
    plugin = _find_plugin(runtime, "codex-plugin")
    hooks = plugin.get("hooks", {})
    return {
        "hooks": {
            "SessionStart": [{"matcher": "*", "hooks": [{"type": "command", "command": "${CODEX_PLUGIN_ROOT}/hooks/mempal-hook.sh session-start", "timeout": 30}]}],
            "Stop": [{"matcher": "*", "hooks": [{"type": "command", "command": hooks.get("stop"), "timeout": 30}]}],
            "PreCompact": [{"matcher": "*", "hooks": [{"type": "command", "command": hooks.get("precompact"), "timeout": 30}]}],
        }
    }


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    if len(sys.argv) not in (4, 5):
        print("Usage: python project_mempalace_integrations.py <operations.registry.yamlld> <integration.profile.yamlld> <output_runtime.json> [repo_root]")
        return 2

    ops_doc = load_yaml(Path(sys.argv[1]).expanduser().resolve())
    profile_doc = load_yaml(Path(sys.argv[2]).expanduser().resolve())
    runtime = runtime_projection(ops_doc, profile_doc)

    runtime_out = Path(sys.argv[3]).expanduser().resolve()
    write_json(runtime_out, runtime)

    if len(sys.argv) == 5:
        repo_root = Path(sys.argv[4]).expanduser().resolve()
        write_json(repo_root / ".claude-plugin/.mcp.json", claude_mcp_manifest(runtime))
        write_json(repo_root / ".claude-plugin/plugin.json", claude_plugin_manifest(runtime))
        write_json(repo_root / ".claude-plugin/hooks/hooks.json", claude_hooks_manifest(runtime))
        write_json(repo_root / ".codex-plugin/plugin.json", codex_plugin_manifest(runtime))
        write_json(repo_root / ".codex-plugin/hooks.json", codex_hooks_manifest(runtime))

    print(str(runtime_out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
