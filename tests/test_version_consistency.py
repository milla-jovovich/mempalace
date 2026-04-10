import re
from pathlib import Path

import pytest

from mempalace import __version__
from mempalace.version import __version__ as version_module_version
from mempalace.mcp_server import handle_request


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


def test_version_module_matches_package():
    """version.py and __init__.py export the same version."""
    assert version_module_version == __version__


def test_version_is_semver():
    """Version string follows semantic versioning (MAJOR.MINOR.PATCH)."""
    assert re.match(r"^\d+\.\d+\.\d+", __version__), f"Invalid semver: {__version__}"


def test_version_not_empty():
    assert __version__
    assert len(__version__) >= 5  # e.g. "1.0.0"


def test_pyproject_version_is_semver():
    version = _expected_version()
    assert re.match(r"^\d+\.\d+\.\d+", version)


def test_mcp_server_info_has_name():
    response = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert response["result"]["serverInfo"]["name"] == "mempalace"
