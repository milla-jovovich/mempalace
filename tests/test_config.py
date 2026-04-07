import json
import tempfile
from pathlib import Path

from mempalace.config import MempalaceConfig


def test_default_config():
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    assert "palace" in cfg.palace_path
    assert cfg.collection_name == "mempalace_drawers"


def test_config_from_file_expands_user_path():
    tmpdir = tempfile.mkdtemp()
    with open(Path(tmpdir) / "config.json", "w") as f:
        json.dump({"palace_path": "~/custom/palace"}, f)

    cfg = MempalaceConfig(config_dir=tmpdir)

    assert cfg.palace_path == str(Path.home() / "custom" / "palace")


def test_env_override_expands_user_path(monkeypatch):
    monkeypatch.setenv("MEMPALACE_PALACE_PATH", "~/env/palace")

    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())

    assert cfg.palace_path == str(Path.home() / "env" / "palace")


def test_init():
    tmpdir = tempfile.mkdtemp()
    cfg = MempalaceConfig(config_dir=tmpdir)

    cfg.init()

    assert (Path(tmpdir) / "config.json").exists()
