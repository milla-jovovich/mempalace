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


def test_config_path_expands_user_home():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"palace_path": "~/.mempalace/custom"}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)
    expected = os.path.expanduser("~/.mempalace/custom")
    assert cfg.palace_path == expected


def test_env_path_expands_user_home():
    os.environ["MEMPALACE_PALACE_PATH"] = "~/.mempalace/env_custom"
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    expected = os.path.expanduser("~/.mempalace/env_custom")
    assert cfg.palace_path == expected
    del os.environ["MEMPALACE_PALACE_PATH"]
