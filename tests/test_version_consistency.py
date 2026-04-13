import json
import re
from pathlib import Path

from mempalace import __version__
from mempalace.mcp_server import TOOLS, handle_request


def _expected_version() -> str:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    content = pyproject.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    assert match is not None, "Could not find project version in pyproject.toml"
    return match.group(1)


def test_package_version_matches_pyproject():
    assert __version__ == _expected_version()


def test_mcp_initialize_reports_package_version():
    response = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert response["result"]["serverInfo"]["version"] == _expected_version()


def test_plugin_versions_match_package_version():
    root = Path(__file__).resolve().parents[1]
    codex_plugin = json.loads((root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    claude_plugin = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    marketplace = json.loads(
        (root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )

    assert codex_plugin["version"] == __version__
    assert claude_plugin["version"] == __version__
    assert marketplace["plugins"][0]["version"] == __version__


def test_plugin_descriptions_track_actual_tool_count():
    root = Path(__file__).resolve().parents[1]
    tool_count = len(TOOLS)
    expected_phrase = f"{tool_count} MCP tools"
    codex_plugin = json.loads((root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    claude_plugin = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    marketplace = json.loads(
        (root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )

    assert expected_phrase in codex_plugin["description"]
    assert expected_phrase in codex_plugin["interface"]["longDescription"]
    assert expected_phrase in claude_plugin["description"]
    assert expected_phrase in marketplace["plugins"][0]["description"]
