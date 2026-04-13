"""Extra tests for mempalace.config to cover remaining gaps."""

import json
import os

from mempalace.config import MempalaceConfig


def test_config_bad_json(tmp_path):
    """Bad JSON in config file falls back to empty."""
    (tmp_path / "config.json").write_text("not json", encoding="utf-8")
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    assert cfg.palace_path  # still returns default


def test_people_map_from_file(tmp_path):
    (tmp_path / "people_map.json").write_text(json.dumps({"bob": "Robert"}), encoding="utf-8")
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    assert cfg.people_map == {"bob": "Robert"}


def test_people_map_bad_json(tmp_path):
    (tmp_path / "people_map.json").write_text("bad", encoding="utf-8")
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    assert cfg.people_map == {}


def test_people_map_missing(tmp_path):
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    assert cfg.people_map == {}


def test_topic_wings_default(tmp_path):
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    assert isinstance(cfg.topic_wings, list)
    assert "emotions" in cfg.topic_wings


def test_hall_keywords_default(tmp_path):
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    assert isinstance(cfg.hall_keywords, dict)
    assert "technical" in cfg.hall_keywords


def test_init_idempotent(tmp_path):
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    cfg.init()
    cfg.init()  # second call should not overwrite
    with open(tmp_path / "config.json") as f:
        data = json.load(f)
    assert "palace_path" in data


def test_save_people_map(tmp_path):
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    result = cfg.save_people_map({"alice": "Alice Smith"})
    assert result.exists()
    with open(result) as f:
        data = json.load(f)
    assert data["alice"] == "Alice Smith"


def test_env_mempal_palace_path(tmp_path):
    """MEMPAL_PALACE_PATH (legacy) should also work and be normalized."""
    os.environ.pop("MEMPALACE_PALACE_PATH", None)
    os.environ["MEMPAL_PALACE_PATH"] = "/legacy/path"
    try:
        cfg = MempalaceConfig(config_dir=str(tmp_path))
        result = cfg.palace_path
        assert result.endswith("legacy" + os.sep + "path") or result.endswith("legacy/path")
        assert os.path.isabs(result)
    finally:
        del os.environ["MEMPAL_PALACE_PATH"]


def test_env_palace_path_normalizes_traversal(tmp_path):
    """Env var palace_path with '../' should be resolved to an absolute path."""
    os.environ.pop("MEMPAL_PALACE_PATH", None)
    os.environ["MEMPALACE_PALACE_PATH"] = "../../tmp/evil_palace"
    try:
        cfg = MempalaceConfig(config_dir=str(tmp_path))
        result = cfg.palace_path
        assert ".." not in result
        assert os.path.isabs(result)
    finally:
        del os.environ["MEMPALACE_PALACE_PATH"]


def test_env_palace_path_expands_tilde(tmp_path):
    """Env var palace_path with '~' should be expanded."""
    os.environ.pop("MEMPAL_PALACE_PATH", None)
    os.environ["MEMPALACE_PALACE_PATH"] = "~/my_palace"
    try:
        cfg = MempalaceConfig(config_dir=str(tmp_path))
        result = cfg.palace_path
        # The path should not start with ~ (expanduser resolves it)
        assert not result.startswith("~")
        assert os.path.isabs(result)
        assert "my_palace" in result
    finally:
        del os.environ["MEMPALACE_PALACE_PATH"]


def test_collection_name_from_config(tmp_path):
    (tmp_path / "config.json").write_text(
        json.dumps({"collection_name": "custom_col"}), encoding="utf-8"
    )
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    assert cfg.collection_name == "custom_col"
