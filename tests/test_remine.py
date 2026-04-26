"""Tests for the mempalace re-mine command."""

import os
from unittest.mock import MagicMock

import pytest

from mempalace.palace import get_collection


@pytest.fixture(autouse=True)
def reset_embedding_cache():
    import mempalace.config as cfg_mod
    cfg_mod._embedding_cache.clear()
    yield
    cfg_mod._embedding_cache.clear()


@pytest.fixture
def populated_palace(tmp_path, monkeypatch):


    palace_path = str(tmp_path / "palace")
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    (source_dir / "file1.txt").write_text("Hello world content for file one")
    (source_dir / "file2.txt").write_text("Second file with different content")

    col = get_collection(palace_path)
    col.add(
        documents=["Hello world content for file one"],
        ids=["drawer-1"],
        metadatas=[{
            "wing": "test",
            "room": "general",
            "source_file": str(source_dir / "file1.txt"),
        }],
    )
    col.add(
        documents=["Second file with different content"],
        ids=["drawer-2"],
        metadatas=[{
            "wing": "test",
            "room": "general",
            "source_file": str(source_dir / "file2.txt"),
        }],
    )

    return {"palace_path": palace_path, "source_dir": source_dir, "col": col}


class TestRemineExtractSources:
    def test_extracts_unique_source_files(self, populated_palace):
        from mempalace.cli import _extract_source_files
        sources = _extract_source_files(populated_palace["palace_path"])
        assert len(sources) == 2
        assert str(populated_palace["source_dir"] / "file1.txt") in sources
        assert str(populated_palace["source_dir"] / "file2.txt") in sources

    def test_empty_palace_returns_empty(self, tmp_path, monkeypatch):
    
        palace_path = str(tmp_path / "palace")
        get_collection(palace_path)
        from mempalace.cli import _extract_source_files
        sources = _extract_source_files(palace_path)
        assert sources == set()


class TestRemineDryRun:
    def test_dry_run_reports_counts(self, populated_palace, capsys):
        from mempalace.cli import cmd_remine
        args = MagicMock()
        args.palace = populated_palace["palace_path"]
        args.dry_run = True
        args.model = None
        args.chunk_size = None
        args.chunk_overlap = None
        cmd_remine(args)
        output = capsys.readouterr().out
        assert "2" in output
        assert "dry run" in output.lower()

    def test_dry_run_does_not_drop_collection(self, populated_palace):
        from mempalace.cli import cmd_remine
        args = MagicMock()
        args.palace = populated_palace["palace_path"]
        args.dry_run = True
        args.model = None
        args.chunk_size = None
        args.chunk_overlap = None
        cmd_remine(args)
        col = get_collection(populated_palace["palace_path"])
        assert col.count() == 2


class TestRemineMissingFiles:
    def test_reports_missing_files(self, populated_palace, capsys):
        from mempalace.cli import cmd_remine
        os.remove(populated_palace["source_dir"] / "file2.txt")
        args = MagicMock()
        args.palace = populated_palace["palace_path"]
        args.dry_run = True
        args.model = None
        args.chunk_size = None
        args.chunk_overlap = None
        cmd_remine(args)
        output = capsys.readouterr().out
        assert "1" in output
        assert "missing" in output.lower() or "Missing" in output
