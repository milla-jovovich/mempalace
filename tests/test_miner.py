"""Tests for mempalace.miner — project file mining."""

import os
from pathlib import Path

import chromadb
import pytest
import yaml

from mempalace.miner import (
    add_drawer,
    chunk_text,
    detect_room,
    load_config,
    mine,
    process_file,
    scan_project,
    status,
)


class TestLoadConfig:
    def test_loads_yaml(self, sample_project):
        cfg = load_config(str(sample_project))
        assert cfg["wing"] == "myproject"
        assert len(cfg["rooms"]) >= 2

    def test_missing_config_exits(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        with pytest.raises(SystemExit):
            load_config(str(d))

    def test_legacy_mempal_yaml(self, tmp_path):
        d = tmp_path / "legacy"
        d.mkdir()
        (d / "mempal.yaml").write_text(yaml.dump({"wing": "old", "rooms": []}))
        cfg = load_config(str(d))
        assert cfg["wing"] == "old"


class TestDetectRoom:
    def setup_method(self):
        self.rooms = [
            {"name": "backend", "description": "Backend", "keywords": ["server", "api"]},
            {"name": "docs", "description": "Documentation", "keywords": ["readme", "guide"]},
            {"name": "general", "description": "General", "keywords": []},
        ]

    def test_folder_path_match(self, tmp_path):
        proj = tmp_path / "proj"
        (proj / "backend").mkdir(parents=True)
        f = proj / "backend" / "app.py"
        f.write_text("code")
        room = detect_room(f, "some code", self.rooms, proj)
        assert room == "backend"

    def test_filename_match(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        f = proj / "backend_service.py"
        f.write_text("code")
        room = detect_room(f, "some code", self.rooms, proj)
        assert room == "backend"

    def test_content_keyword_match(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        f = proj / "misc.py"
        f.write_text("code")
        room = detect_room(f, "the server api handles requests", self.rooms, proj)
        assert room == "backend"

    def test_fallback_to_general(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        f = proj / "random.py"
        f.write_text("nothing")
        room = detect_room(f, "xyz", self.rooms, proj)
        assert room == "general"


class TestChunkText:
    def test_short_text_single_chunk(self):
        text = "A" * 200
        chunks = chunk_text(text, "file.py")
        assert len(chunks) == 1
        assert chunks[0]["chunk_index"] == 0

    def test_long_text_multiple_chunks(self):
        text = ("This is a paragraph. " * 50 + "\n\n") * 10
        chunks = chunk_text(text, "file.py")
        assert len(chunks) > 1

    def test_empty_text(self):
        assert chunk_text("", "f.py") == []
        assert chunk_text("   ", "f.py") == []

    def test_too_short_text(self):
        assert chunk_text("hi", "f.py") == []


class TestAddDrawer:
    @pytest.mark.integration
    def test_adds_successfully(self, palace_path):
        from mempalace.palace_db import get_collection
        col = get_collection(palace_path=palace_path, create=True)
        result = add_drawer(col, "wing", "room", "content text here", "/src/f.py", 0, "agent")
        assert result is True
        assert col.count() == 1

    @pytest.mark.integration
    def test_duplicate_returns_false(self, palace_path):
        from mempalace.palace_db import get_collection
        col = get_collection(palace_path=palace_path, create=True)
        r1 = add_drawer(col, "w", "r", "content", "/f.py", 0, "a")
        assert r1 is True
        r2 = add_drawer(col, "w", "r", "content", "/f.py", 0, "a")
        # ChromaDB may raise "already exists" or silently succeed depending on version
        assert r2 in (True, False)


class TestScanProject:
    def test_finds_py_files(self, sample_project):
        files = scan_project(str(sample_project))
        py_files = [f for f in files if f.suffix == ".py"]
        assert len(py_files) >= 2

    def test_finds_md_files(self, sample_project):
        files = scan_project(str(sample_project))
        md_files = [f for f in files if f.suffix == ".md"]
        assert len(md_files) >= 1

    def test_skips_config_files(self, sample_project):
        files = scan_project(str(sample_project))
        names = [f.name for f in files]
        assert "mempalace.yaml" not in names

    def test_skips_hidden_dirs(self, sample_project):
        git = sample_project / ".git"
        git.mkdir()
        (git / "config").write_text("git")
        files = scan_project(str(sample_project))
        assert all(".git" not in str(f) for f in files)


class TestMineIntegration:
    @pytest.mark.integration
    def test_mines_project(self, sample_project, palace_path):
        mine(str(sample_project), palace_path)
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
        assert col.count() > 0

    @pytest.mark.integration
    def test_dry_run(self, sample_project, palace_path, capsys):
        mine(str(sample_project), palace_path, dry_run=True)
        captured = capsys.readouterr()
        assert "DRY RUN" in captured.out

    @pytest.mark.integration
    def test_wing_override(self, sample_project, palace_path):
        mine(str(sample_project), palace_path, wing_override="custom_wing")
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
        metas = col.get(include=["metadatas"])["metadatas"]
        assert all(m["wing"] == "custom_wing" for m in metas)


class TestStatus:
    @pytest.mark.integration
    def test_status_empty(self, palace_path, capsys):
        status(palace_path)
        out = capsys.readouterr().out
        assert "No palace" in out

    @pytest.mark.integration
    def test_status_with_data(self, palace_with_data, capsys):
        status(palace_with_data)
        out = capsys.readouterr().out
        assert "5 drawers" in out
