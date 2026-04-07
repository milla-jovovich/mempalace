"""Tests for mempalace.room_detector_local — room detection from folder structure."""

import yaml
import pytest

from mempalace.room_detector_local import (
    detect_rooms_from_files,
    detect_rooms_from_folders,
    save_config,
)


class TestDetectRoomsFromFolders:
    def test_detects_known_folders(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "frontend").mkdir()
        (proj / "backend").mkdir()
        (proj / "docs").mkdir()
        rooms = detect_rooms_from_folders(str(proj))
        room_names = [r["name"] for r in rooms]
        assert "frontend" in room_names
        assert "backend" in room_names
        assert "documentation" in room_names

    def test_always_includes_general(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "frontend").mkdir()
        rooms = detect_rooms_from_folders(str(proj))
        room_names = [r["name"] for r in rooms]
        assert "general" in room_names

    def test_skips_hidden_dirs(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / ".git").mkdir()
        (proj / "__pycache__").mkdir()
        (proj / "src").mkdir()
        rooms = detect_rooms_from_folders(str(proj))
        room_names = [r["name"] for r in rooms]
        assert ".git" not in room_names
        assert "__pycache__" not in room_names

    def test_empty_project(self, tmp_path):
        proj = tmp_path / "empty"
        proj.mkdir()
        rooms = detect_rooms_from_folders(str(proj))
        assert len(rooms) >= 1
        assert rooms[-1]["name"] == "general"

    def test_nested_pattern_detection(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "src").mkdir()
        (proj / "src" / "tests").mkdir()
        rooms = detect_rooms_from_folders(str(proj))
        room_names = [r["name"] for r in rooms]
        assert "testing" in room_names

    def test_variant_names(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "front-end").mkdir()
        (proj / "back_end").mkdir()
        rooms = detect_rooms_from_folders(str(proj))
        room_names = [r["name"] for r in rooms]
        assert "frontend" in room_names
        assert "backend" in room_names


class TestDetectRoomsFromFiles:
    def test_detects_from_filenames(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "test_auth.py").write_text("test")
        (proj / "test_api.py").write_text("test")
        (proj / "test_db.py").write_text("test")
        rooms = detect_rooms_from_files(str(proj))
        room_names = [r["name"] for r in rooms]
        assert "testing" in room_names

    def test_empty_project_returns_general(self, tmp_path):
        proj = tmp_path / "empty"
        proj.mkdir()
        rooms = detect_rooms_from_files(str(proj))
        assert rooms[0]["name"] == "general"


class TestSaveConfig:
    def test_saves_yaml(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        rooms = [
            {"name": "backend", "description": "Backend code"},
            {"name": "general", "description": "General"},
        ]
        save_config(str(proj), "myproject", rooms)
        config_path = proj / "mempalace.yaml"
        assert config_path.exists()
        data = yaml.safe_load(config_path.read_text())
        assert data["wing"] == "myproject"
        assert len(data["rooms"]) == 2
