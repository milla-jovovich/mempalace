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


def test_config_file_tilde_is_expanded():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"palace_path": "~/.mempalace/palace"}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert not cfg.palace_path.startswith("~")
    assert cfg.palace_path == os.path.expanduser("~/.mempalace/palace")


def test_env_var_tilde_is_expanded():
    os.environ["MEMPALACE_PALACE_PATH"] = "~/custom/palace"
    try:
        cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
        assert not cfg.palace_path.startswith("~")
        assert cfg.palace_path == os.path.expanduser("~/custom/palace")
    finally:
        del os.environ["MEMPALACE_PALACE_PATH"]


def test_init():
    tmpdir = tempfile.mkdtemp()
    cfg = MempalaceConfig(config_dir=tmpdir)
    cfg.init()
    assert os.path.exists(os.path.join(tmpdir, "config.json"))
