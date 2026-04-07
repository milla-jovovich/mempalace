import os
import json
import tempfile
from mempalace.config import MempalaceConfig


def test_default_config():
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    assert "palace" in cfg.palace_path
    assert cfg.collection_name == "mempalace_drawers"


def test_config_from_file():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"palace_path": "/custom/palace"}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.palace_path == "/custom/palace"


def test_env_override():
    os.environ["MEMPALACE_PALACE_PATH"] = "/env/palace"
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    assert cfg.palace_path == "/env/palace"
    del os.environ["MEMPALACE_PALACE_PATH"]


def test_init():
    tmpdir = tempfile.mkdtemp()
    cfg = MempalaceConfig(config_dir=tmpdir)
    cfg.init()
    assert os.path.exists(os.path.join(tmpdir, "config.json"))


# ── Security config ──────────────────────────────────────────────────────


def test_security_config_defaults():
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    assert cfg.auth_enabled is False
    assert cfg.encryption_enabled is False
    assert cfg.max_content_size == 1_048_576


def test_security_config_from_file():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump(
            {
                "security": {
                    "auth_enabled": True,
                    "encryption_enabled": True,
                    "max_content_size": 500_000,
                }
            },
            f,
        )
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.auth_enabled is True
    assert cfg.encryption_enabled is True
    assert cfg.max_content_size == 500_000


def test_security_env_override():
    tmpdir = tempfile.mkdtemp()
    cfg = MempalaceConfig(config_dir=tmpdir)
    os.environ["MEMPALACE_AUTH_ENABLED"] = "true"
    try:
        assert cfg.auth_enabled is True
    finally:
        del os.environ["MEMPALACE_AUTH_ENABLED"]
