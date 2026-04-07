import json
from mempalace.config import MempalaceConfig


def test_default_config(tmp_dir):
    cfg = MempalaceConfig(config_dir=str(tmp_dir))
    assert "palace" in cfg.palace_path
    assert cfg.collection_name == "mempalace_drawers"


def test_config_from_file(tmp_dir):
    with open(tmp_dir / "config.json", "w") as f:
        json.dump({"palace_path": "/custom/palace"}, f)
    cfg = MempalaceConfig(config_dir=str(tmp_dir))
    assert cfg.palace_path == "/custom/palace"


def test_env_override(tmp_dir, monkeypatch):
    monkeypatch.setenv("MEMPALACE_PALACE_PATH", "/env/palace")
    cfg = MempalaceConfig(config_dir=str(tmp_dir))
    assert cfg.palace_path == "/env/palace"


def test_init(tmp_dir):
    cfg = MempalaceConfig(config_dir=str(tmp_dir))
    cfg.init()
    assert (tmp_dir / "config.json").exists()
