"""Tests for convo_miner integration — mine_convos and scan_convos."""

import os
import tempfile
import shutil

import chromadb

from mempalace.convo_miner import mine_convos, scan_convos, MIN_CHUNK_SIZE, MAX_FILE_SIZE


# ── Integration: mine_convos end-to-end ────────────────────────────────


class TestMineConvosIntegration:
    def test_basic_mining(self, tmp_path):
        """Basic exchange-pair mining creates drawers."""
        convo_file = tmp_path / "chat.txt"
        convo_file.write_text(
            "> What is memory?\nMemory is persistence.\n\n"
            "> Why does it matter?\nIt enables continuity.\n\n"
            "> How do we build it?\nWith structured storage.\n",
            encoding="utf-8",
        )
        palace_path = str(tmp_path / "palace")
        mine_convos(str(tmp_path), palace_path, wing="test_convos")

        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
        assert col.count() >= 2

    def test_search_after_mining(self, tmp_path):
        """Mined content is searchable."""
        convo_file = tmp_path / "chat.txt"
        convo_file.write_text(
            "> What is memory?\nMemory is persistence of information.\n\n"
            "> Why does it matter?\nIt enables continuity and recall.\n",
            encoding="utf-8",
        )
        palace_path = str(tmp_path / "palace")
        mine_convos(str(tmp_path), palace_path, wing="test_convos")

        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
        results = col.query(query_texts=["memory persistence"], n_results=1)
        assert len(results["documents"][0]) > 0

    def test_skip_already_mined_files(self, tmp_path):
        """Running mine_convos twice does not duplicate drawers (upsert)."""
        convo_file = tmp_path / "chat.txt"
        convo_file.write_text(
            "> What is memory?\nMemory is persistence of data over time.\n\n"
            "> Why does it matter?\nIt enables continuity across sessions.\n",
            encoding="utf-8",
        )
        palace_path = str(tmp_path / "palace")
        mine_convos(str(tmp_path), palace_path, wing="test_convos")

        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
        count_first = col.count()

        mine_convos(str(tmp_path), palace_path, wing="test_convos")
        assert col.count() == count_first

    def test_metadata_set_correctly(self, tmp_path):
        """Drawers have correct wing and metadata fields."""
        convo_file = tmp_path / "chat.txt"
        convo_file.write_text(
            "> Tell me about code\nHere is how to debug python function and fix the error.\n",
            encoding="utf-8",
        )
        palace_path = str(tmp_path / "palace")
        mine_convos(str(tmp_path), palace_path, wing="my_wing")

        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
        data = col.get(include=["metadatas"])
        assert len(data["metadatas"]) >= 1
        meta = data["metadatas"][0]
        assert meta["wing"] == "my_wing"
        assert "room" in meta
        assert "source_file" in meta
        assert meta["ingest_mode"] == "convos"

    def test_dry_run_does_not_create_palace(self, tmp_path):
        """dry_run=True should not create the palace directory."""
        convo_file = tmp_path / "chat.txt"
        convo_file.write_text(
            "> What is memory?\nMemory is persistence.\n\n"
            "> Why does it matter?\nIt enables continuity.\n",
            encoding="utf-8",
        )
        palace_path = str(tmp_path / "palace")
        mine_convos(str(tmp_path), palace_path, wing="test", dry_run=True)
        # Palace directory shouldn't have a chromadb collection
        assert not os.path.exists(os.path.join(palace_path, "chroma.sqlite3"))

    def test_empty_directory_no_crash(self, tmp_path):
        """Mining an empty directory should succeed without errors."""
        palace_path = str(tmp_path / "palace")
        mine_convos(str(tmp_path), palace_path, wing="empty")
        # No crash is the assertion

    def test_file_below_min_chunk_size_skipped(self, tmp_path):
        """Files with content shorter than MIN_CHUNK_SIZE should be skipped."""
        convo_file = tmp_path / "tiny.txt"
        convo_file.write_text("hi", encoding="utf-8")
        palace_path = str(tmp_path / "palace")
        mine_convos(str(tmp_path), palace_path, wing="test")

        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
        assert col.count() == 0

    def test_limit_parameter(self, tmp_path):
        """limit parameter restricts number of files processed."""
        for i in range(5):
            (tmp_path / f"chat_{i}.txt").write_text(
                f"> Question {i}?\nThis is a sufficiently long answer to question number {i} about memory.\n",
                encoding="utf-8",
            )
        palace_path = str(tmp_path / "palace")
        mine_convos(str(tmp_path), palace_path, wing="test", limit=2)

        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
        # Should have drawers from at most 2 files
        data = col.get(include=["metadatas"])
        source_files = {m["source_file"] for m in data["metadatas"]}
        assert len(source_files) <= 2

    def test_wing_auto_detected_from_dir_name(self, tmp_path):
        """When wing is None, it is derived from the directory name."""
        convo_dir = tmp_path / "my-chats"
        convo_dir.mkdir()
        (convo_dir / "chat.txt").write_text(
            "> What is testing?\nTesting is validating that code behaves as expected correctly.\n",
            encoding="utf-8",
        )
        palace_path = str(tmp_path / "palace")
        mine_convos(str(convo_dir), palace_path)

        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
        data = col.get(include=["metadatas"])
        if data["metadatas"]:
            assert data["metadatas"][0]["wing"] == "my_chats"


# ── scan_convos edge cases ─────────────────────────────────────────────


class TestScanConvosEdgeCases:
    def test_skips_oversized_files(self, tmp_path):
        """Files larger than MAX_FILE_SIZE should be skipped."""
        big_file = tmp_path / "huge.txt"
        big_file.write_text("x" * (MAX_FILE_SIZE + 1), encoding="utf-8")
        (tmp_path / "normal.txt").write_text("hello world", encoding="utf-8")
        files = scan_convos(str(tmp_path))
        names = [f.name for f in files]
        assert "huge.txt" not in names
        assert "normal.txt" in names

    def test_skips_symlinks(self, tmp_path):
        """Symlinks should be skipped."""
        real_file = tmp_path / "real.txt"
        real_file.write_text("content", encoding="utf-8")
        link = tmp_path / "link.txt"
        try:
            link.symlink_to(real_file)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported on this platform")
        files = scan_convos(str(tmp_path))
        names = [f.name for f in files]
        assert "link.txt" not in names

    def test_jsonl_extension_included(self, tmp_path):
        (tmp_path / "data.jsonl").write_text('{"msg": "hi"}', encoding="utf-8")
        files = scan_convos(str(tmp_path))
        assert any(f.suffix == ".jsonl" for f in files)
