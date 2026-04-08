import os
import json
import tempfile
import pytest
from mempalace.config import MempalaceConfig


def test_remote_config_defaults():
    """chroma_host defaults to None; port to 8000; ssl to False."""
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    assert cfg.chroma_host is None
    assert cfg.chroma_port == 8000
    assert cfg.chroma_ssl is False


def test_remote_config_from_file():
    """Config file values are read correctly."""
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"chroma_host": "m1mini.local", "chroma_port": 9000, "chroma_ssl": True}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.chroma_host == "m1mini.local"
    assert cfg.chroma_port == 9000
    assert cfg.chroma_ssl is True


def test_remote_config_env_vars_override_file():
    """Env vars take priority over config file values."""
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"chroma_host": "file-host", "chroma_port": 1234}, f)
    os.environ["MEMPALACE_CHROMA_HOST"] = "env-host"
    os.environ["MEMPALACE_CHROMA_PORT"] = "5678"
    os.environ["MEMPALACE_CHROMA_SSL"] = "true"
    try:
        cfg = MempalaceConfig(config_dir=tmpdir)
        assert cfg.chroma_host == "env-host"
        assert cfg.chroma_port == 5678
        assert cfg.chroma_ssl is True
    finally:
        del os.environ["MEMPALACE_CHROMA_HOST"]
        del os.environ["MEMPALACE_CHROMA_PORT"]
        del os.environ["MEMPALACE_CHROMA_SSL"]


def test_remote_config_env_host_none_when_empty_string():
    """Empty string env var is treated as not set (returns None)."""
    os.environ["MEMPALACE_CHROMA_HOST"] = ""
    try:
        cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
        assert cfg.chroma_host is None
    finally:
        del os.environ["MEMPALACE_CHROMA_HOST"]


def test_remote_config_invalid_port_raises():
    """Non-integer MEMPALACE_CHROMA_PORT raises ValueError."""
    os.environ["MEMPALACE_CHROMA_PORT"] = "not-a-port"
    try:
        cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
        with pytest.raises(ValueError, match="MEMPALACE_CHROMA_PORT"):
            _ = cfg.chroma_port
    finally:
        del os.environ["MEMPALACE_CHROMA_PORT"]


import unittest.mock as mock
import chromadb
from mempalace import palace_db


def test_get_client_returns_persistent_when_no_host(tmp_path):
    """With no chroma_host, get_client returns a local (persistent) client."""
    client = palace_db.get_client(palace_path=str(tmp_path))
    # chromadb.PersistentClient is a factory function, not a class; verify via settings
    assert client.get_settings().is_persistent is True


def test_get_client_returns_http_when_host_configured(tmp_path, monkeypatch):
    """With MEMPALACE_CHROMA_HOST set, get_client calls chromadb.HttpClient."""
    monkeypatch.setenv("MEMPALACE_CHROMA_HOST", "localhost")
    monkeypatch.setenv("MEMPALACE_CHROMA_PORT", "8000")
    monkeypatch.setenv("MEMPALACE_CHROMA_SSL", "false")
    with mock.patch("mempalace.palace_db.chromadb.HttpClient") as mock_http:
        mock_http.return_value = mock.MagicMock()
        client = palace_db.get_client(palace_path=str(tmp_path))
        mock_http.assert_called_once_with(host="localhost", port=8000, ssl=False)


def test_get_collection_creates_if_absent(tmp_path):
    """get_collection creates the collection if it does not yet exist."""
    col = palace_db.get_collection(palace_path=str(tmp_path))
    assert col is not None
    assert col.name == "mempalace_drawers"


def test_get_collection_returns_existing(tmp_path):
    """get_collection returns the same collection on second call."""
    col1 = palace_db.get_collection(palace_path=str(tmp_path))
    col1.add(ids=["x"], documents=["hello"], metadatas=[{"wing": "a", "room": "b"}])
    col2 = palace_db.get_collection(palace_path=str(tmp_path))
    assert col2.count() == 1


import subprocess
import sys


def test_remote_status_local_mode(monkeypatch):
    """'mempalace remote status' prints local mode when no host configured."""
    monkeypatch.delenv("MEMPALACE_CHROMA_HOST", raising=False)
    result = subprocess.run(
        [sys.executable, "-m", "mempalace", "remote", "status"],
        capture_output=True,
        text=True,
        cwd="/Users/cypromis/Projects/claude-code/mempalace",
    )
    assert result.returncode == 0
    assert "local" in result.stdout.lower()
