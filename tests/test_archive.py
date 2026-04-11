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


@pytest.fixture
def config(temp_config):
    """Alias for room-archive tests (same setup as temp_config)."""
    return temp_config


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


class TestRoomArchive:
    """Tests for room-level archiving."""

    def test_archive_room(self, config):
        """Room can be archived within a wing."""
        config.archive_room("technical", "old_evidence")
        assert "old_evidence" in config.get_archived_rooms("technical")

    def test_unarchive_room(self, config):
        """Archived room can be restored."""
        config.archive_room("technical", "old_evidence")
        config.unarchive_room("technical", "old_evidence")
        assert "old_evidence" not in config.get_archived_rooms("technical")

    def test_archive_room_idempotent(self, config):
        """Archiving same room twice does not duplicate."""
        config.archive_room("technical", "old_evidence")
        config.archive_room("technical", "old_evidence")
        assert config.get_archived_rooms("technical").count("old_evidence") == 1

    def test_archive_room_preserves_wing_state(self, config):
        """Archiving a room does not archive the wing itself."""
        config.archive_room("technical", "old_evidence")
        assert "technical" not in config.get_archived_wings()

    def test_unarchive_room_nonexistent(self, config):
        """Unarchiving a room that was never archived does not error."""
        config.unarchive_room("technical", "nonexistent_room")
        assert config.get_archived_rooms("technical") == []

    def test_get_archived_rooms_empty_wing(self, config):
        """Wing with no archived rooms returns empty list."""
        assert config.get_archived_rooms("technical") == []

    def test_archive_rooms_multiple_wings(self, config):
        """Rooms can be archived independently across different wings."""
        config.archive_room("technical", "old_api_docs")
        config.archive_room("emotions", "past_events")
        assert "old_api_docs" in config.get_archived_rooms("technical")
        assert "past_events" in config.get_archived_rooms("emotions")
        assert "old_api_docs" not in config.get_archived_rooms("emotions")

    def test_wing_config_schema(self, config):
        """wing_config.json stores archived_rooms as a list under the wing key."""
        config.archive_room("technical", "room_a")
        config.archive_room("technical", "room_b")
        wc = config.load_wing_config()
        assert isinstance(wc["technical"]["archived_rooms"], list)
        assert set(wc["technical"]["archived_rooms"]) == {"room_a", "room_b"}

    def test_cleanup_empty_archived_rooms(self, config):
        """After unarchiving the last room, archived_rooms key is removed."""
        config.archive_room("technical", "only_room")
        config.unarchive_room("technical", "only_room")
        wc = config.load_wing_config()
        assert "archived_rooms" not in wc.get("technical", {})
