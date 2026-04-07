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


def test_palace_path_expanduser_in_config():
    """Tilde in config.json should expand (#40)."""
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"palace_path": "~/mempalace_unit_test_palace_path_expand"}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.palace_path == os.path.join(
        os.path.expanduser("~"), "mempalace_unit_test_palace_path_expand"
    )


def test_palace_path_expanduser_env():
    try:
        os.environ["MEMPALACE_PALACE_PATH"] = "~/from_env_palace_test"
        cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
        assert cfg.palace_path == os.path.join(os.path.expanduser("~"), "from_env_palace_test")
    finally:
        del os.environ["MEMPALACE_PALACE_PATH"]
