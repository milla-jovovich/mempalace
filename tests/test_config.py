"""Tests for mempalace.config — MempalaceConfig."""

import json

import pytest

from mempalace.config import (
    DEFAULT_COLLECTION_NAME,
    DEFAULT_PALACE_PATH,
    DEFAULT_TOPIC_WINGS,
    MempalaceConfig,
)


class TestDefaults:
    def test_default_palace_path(self, config):
        assert config.palace_path == DEFAULT_PALACE_PATH

    def test_default_collection_name(self, config):
        assert config.collection_name == DEFAULT_COLLECTION_NAME

    def test_default_topic_wings(self, config):
        assert config.topic_wings == DEFAULT_TOPIC_WINGS

    def test_default_people_map_empty(self, config):
        assert config.people_map == {}


class TestConfigFile:
    def test_loads_from_file(self, config_dir):
        (config_dir / "config.json").write_text(
            json.dumps({"palace_path": "/custom/palace", "collection_name": "my_col"})
        )
        cfg = MempalaceConfig(config_dir=str(config_dir))
        assert cfg.palace_path == "/custom/palace"
        assert cfg.collection_name == "my_col"

    def test_malformed_json_falls_back(self, config_dir):
        (config_dir / "config.json").write_text("{bad json")
        cfg = MempalaceConfig(config_dir=str(config_dir))
        assert cfg.palace_path == DEFAULT_PALACE_PATH

    def test_topic_wings_from_file(self, config_dir):
        custom_wings = ["work", "life"]
        (config_dir / "config.json").write_text(json.dumps({"topic_wings": custom_wings}))
        cfg = MempalaceConfig(config_dir=str(config_dir))
        assert cfg.topic_wings == custom_wings


class TestEnvOverride:
    def test_mempalace_env_var(self, config, monkeypatch):
        monkeypatch.setenv("MEMPALACE_PALACE_PATH", "/env/palace")
        assert config.palace_path == "/env/palace"

    def test_legacy_mempal_env_var(self, config, monkeypatch):
        monkeypatch.setenv("MEMPAL_PALACE_PATH", "/legacy/path")
        assert config.palace_path == "/legacy/path"

    def test_env_beats_file(self, config_dir, monkeypatch):
        (config_dir / "config.json").write_text(json.dumps({"palace_path": "/file/path"}))
        monkeypatch.setenv("MEMPALACE_PALACE_PATH", "/env/wins")
        cfg = MempalaceConfig(config_dir=str(config_dir))
        assert cfg.palace_path == "/env/wins"


class TestInit:
    def test_creates_config_dir(self, tmp_path):
        d = tmp_path / "new_config"
        cfg = MempalaceConfig(config_dir=str(d))
        result = cfg.init()
        assert d.exists()
        assert result.exists()

    def test_writes_default_config(self, config_dir):
        cfg = MempalaceConfig(config_dir=str(config_dir))
        cfg.init()
        data = json.loads((config_dir / "config.json").read_text())
        assert data["palace_path"] == DEFAULT_PALACE_PATH
        assert data["collection_name"] == DEFAULT_COLLECTION_NAME

    def test_does_not_overwrite_existing(self, config_dir):
        custom = {"palace_path": "/custom"}
        (config_dir / "config.json").write_text(json.dumps(custom))
        cfg = MempalaceConfig(config_dir=str(config_dir))
        cfg.init()
        data = json.loads((config_dir / "config.json").read_text())
        assert data["palace_path"] == "/custom"


class TestPeopleMap:
    def test_loads_people_map_file(self, config_dir):
        pm = {"bob": "Robert", "al": "Alice"}
        (config_dir / "people_map.json").write_text(json.dumps(pm))
        cfg = MempalaceConfig(config_dir=str(config_dir))
        assert cfg.people_map == pm

    def test_save_people_map(self, config_dir):
        cfg = MempalaceConfig(config_dir=str(config_dir))
        pm = {"test": "Test Person"}
        cfg.save_people_map(pm)
        assert json.loads((config_dir / "people_map.json").read_text()) == pm
