import re
from pathlib import Path

from mempalace import __version__
from mempalace.mcp_server import handle_request


def _pyproject_version():
    root = Path(__file__).resolve().parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    project_block = re.search(r"(?ms)^\[project\]\n(.*?)(?:^\[|\Z)", pyproject)
    assert project_block is not None

    version_match = re.search(r'^version\s*=\s*"([^"]+)"', project_block.group(1), re.MULTILINE)
    assert version_match is not None
    return version_match.group(1)


def test_runtime_version_matches_pyproject_and_mcp():
    response = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})

    assert _pyproject_version() == __version__
    assert response["result"]["serverInfo"]["version"] == __version__
