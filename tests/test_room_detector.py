from pathlib import Path

from mempalace.room_detector_local import (
    detect_rooms_from_folders,
    detect_rooms_from_files,
)


def _write_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_detect_rooms_from_folders_maps_known_dirs(tmp_dir):
    (tmp_dir / "frontend").mkdir()
    (tmp_dir / "backend").mkdir()
    (tmp_dir / "docs").mkdir()
    rooms = detect_rooms_from_folders(str(tmp_dir))
    room_names = {r["name"] for r in rooms}
    assert "frontend" in room_names
    assert "backend" in room_names
    assert "documentation" in room_names


def test_detect_rooms_always_includes_general(tmp_dir):
    rooms = detect_rooms_from_folders(str(tmp_dir))
    room_names = {r["name"] for r in rooms}
    assert "general" in room_names


def test_detect_rooms_skips_venv(tmp_dir):
    (tmp_dir / ".venv").mkdir()
    (tmp_dir / "src").mkdir()
    rooms = detect_rooms_from_folders(str(tmp_dir))
    room_names = {r["name"] for r in rooms}
    assert ".venv" not in room_names
    assert "venv" not in room_names


def test_detect_rooms_from_folders_nested(tmp_dir):
    (tmp_dir / "app" / "components").mkdir(parents=True)
    rooms = detect_rooms_from_folders(str(tmp_dir))
    room_names = {r["name"] for r in rooms}
    assert "frontend" in room_names  # "components" maps to frontend


def test_detect_rooms_from_files(tmp_dir):
    _write_file(tmp_dir / "test_app.py", "x" * 20)
    _write_file(tmp_dir / "test_utils.py", "x" * 20)
    _write_file(tmp_dir / "test_db.py", "x" * 20)
    rooms = detect_rooms_from_files(str(tmp_dir))
    room_names = {r["name"] for r in rooms}
    assert "testing" in room_names


def test_detect_rooms_from_files_fallback_general(tmp_dir):
    _write_file(tmp_dir / "random.xyz", "x" * 20)
    rooms = detect_rooms_from_files(str(tmp_dir))
    room_names = {r["name"] for r in rooms}
    assert "general" in room_names
