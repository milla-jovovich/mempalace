"""Tests for mempalace-mcp entry point and uv compatibility."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class TestMcpEntryPoint:
    """Verify mempalace-mcp console_script is properly configured."""

    def test_mcp_server_main_is_importable_and_callable(self):
        from mempalace.mcp_server import main

        assert callable(main)

    def test_pyproject_defines_mempalace_mcp_entry_point(self):
        pyproject = (ROOT / "pyproject.toml").read_text()
        assert 'mempalace-mcp = "mempalace.mcp_server:main"' in pyproject


class TestMcpConfigs:
    """MCP config files must use mempalace-mcp, not python3."""

    def test_claude_plugin_mcp_json_uses_entry_point(self):
        config = json.loads((ROOT / ".claude-plugin" / ".mcp.json").read_text())
        server = config["mempalace"]
        assert server["command"] == "mempalace-mcp"
        assert "-m" not in server.get("args", [])

    def test_claude_plugin_json_uses_entry_point(self):
        config = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
        server = config["mcpServers"]["mempalace"]
        assert server["command"] == "mempalace-mcp"
        assert "-m" not in server.get("args", [])

    def test_codex_plugin_json_uses_entry_point(self):
        config = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text())
        server = config["mcpServers"]["mempalace"]
        assert server["command"] == "mempalace-mcp"
        assert "-m" not in server.get("args", [])


class TestHookScripts:
    """Hook scripts must use `mempalace` entry point, not `python3 -m mempalace`."""

    @pytest.mark.parametrize(
        "hook_path",
        [
            ".claude-plugin/hooks/mempal-stop-hook.sh",
            ".claude-plugin/hooks/mempal-precompact-hook.sh",
            ".codex-plugin/hooks/mempal-hook.sh",
            "hooks/mempal_save_hook.sh",
            "hooks/mempal_precompact_hook.sh",
        ],
    )
    def test_hook_does_not_use_python3_m_mempalace(self, hook_path):
        content = (ROOT / hook_path).read_text()
        # python3 -c is fine (stdlib JSON parsing), only python3 -m mempalace is wrong
        for line in content.splitlines():
            if "python3 -m mempalace" in line:
                pytest.fail(f"{hook_path} still uses 'python3 -m mempalace': {line.strip()}")
