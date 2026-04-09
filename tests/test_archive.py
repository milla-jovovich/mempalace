"""Tests for soft-archive wing feature (#332)."""

import json
import tempfile
import shutil
from pathlib import Path

import pytest

from mempalace.config import MempalaceConfig


@pytest.fixture
def temp_config(tmp_path):
    """Create a temporary MempalaceConfig."""
    config = MempalaceConfig(config_dir=str(tmp_path))
    config.init()
    return config


class TestArchiveWing:
    """Test archive/unarchive wing methods on config."""

    def test_archive_wing_creates_flag(self, temp_config):
        temp_config.save_wing_config({"my_project": {"type": "project"}})
        changed = temp_config.archive_wing("my_project")
        assert changed is True
        wc = temp_config.load_wing_config()
        assert wc["my_project"]["archived"] is True

    def test_archive_wing_new_wing(self, temp_config):
        changed = temp_config.archive_wing("unknown_wing")
        assert changed is True
        wc = temp_config.load_wing_config()
        assert wc["unknown_wing"]["archived"] is True

    def test_archive_wing_already_archived(self, temp_config):
        temp_config.archive_wing("my_project")
        changed = temp_config.archive_wing("my_project")
        assert changed is False

    def test_unarchive_wing(self, temp_config):
        temp_config.archive_wing("my_project")
        changed = temp_config.unarchive_wing("my_project")
        assert changed is True
        wc = temp_config.load_wing_config()
        assert wc["my_project"]["archived"] is False

    def test_unarchive_wing_not_archived(self, temp_config):
        changed = temp_config.unarchive_wing("my_project")
        assert changed is False

    def test_get_archived_wings(self, temp_config):
        temp_config.archive_wing("old_project")
        temp_config.archive_wing("dead_project")
        temp_config.save_wing_config({
            "old_project": {"archived": True},
            "dead_project": {"archived": True},
            "active_project": {"archived": False},
            "new_project": {},
        })
        archived = temp_config.get_archived_wings()
        assert archived == {"old_project", "dead_project"}

    def test_archive_preserves_existing_config(self, temp_config):
        temp_config.save_wing_config({
            "my_project": {"type": "project", "path": "/some/path"}
        })
        temp_config.archive_wing("my_project")
        wc = temp_config.load_wing_config()
        assert wc["my_project"]["type"] == "project"
        assert wc["my_project"]["path"] == "/some/path"
        assert wc["my_project"]["archived"] is True

    def test_unarchive_preserves_existing_config(self, temp_config):
        temp_config.save_wing_config({
            "my_project": {"type": "project", "archived": True}
        })
        temp_config.unarchive_wing("my_project")
        wc = temp_config.load_wing_config()
        assert wc["my_project"]["type"] == "project"
        assert wc["my_project"]["archived"] is False


class TestWingConfigIO:
    """Test wing_config.json load/save."""

    def test_load_empty(self, temp_config):
        wc = temp_config.load_wing_config()
        assert wc == {}

    def test_save_and_load(self, temp_config):
        data = {"wing_a": {"archived": True}, "wing_b": {}}
        temp_config.save_wing_config(data)
        loaded = temp_config.load_wing_config()
        assert loaded == data

    def test_load_corrupt_json(self, temp_config):
        with open(temp_config.wing_config_path, "w") as f:
            f.write("{broken json")
        wc = temp_config.load_wing_config()
        assert wc == {}
