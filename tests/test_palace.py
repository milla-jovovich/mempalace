"""Tests for mempalace.palace — shared ChromaDB access and file-tracking."""

import os
import stat
import sys
from unittest.mock import MagicMock, patch

import chromadb
import pytest

from mempalace.palace import SKIP_DIRS, file_already_mined, get_collection


class TestGetCollection:
    def test_creates_directory(self, tmp_path):
        palace_path = str(tmp_path / "new_palace")
        assert not os.path.exists(palace_path)
        col = get_collection(palace_path)
        assert os.path.isdir(palace_path)
        assert col is not None

    def test_creates_nested_directory(self, tmp_path):
        palace_path = str(tmp_path / "a" / "b" / "c" / "palace")
        col = get_collection(palace_path)
        assert os.path.isdir(palace_path)
        assert col is not None

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix permissions only")
    def test_sets_directory_permissions_0o700(self, tmp_path):
        palace_path = str(tmp_path / "secure_palace")
        get_collection(palace_path)
        mode = stat.S_IMODE(os.stat(palace_path).st_mode)
        assert mode == 0o700

    def test_returns_existing_collection(self, tmp_path):
        palace_path = str(tmp_path / "palace")
        client = chromadb.PersistentClient(path=palace_path)
        client.get_or_create_collection("mempalace_drawers")
        del client

        col = get_collection(palace_path)
        assert col.name == "mempalace_drawers"

    def test_creates_collection_if_missing(self, tmp_path):
        palace_path = str(tmp_path / "palace")
        col = get_collection(palace_path)
        assert col.name == "mempalace_drawers"

    def test_custom_collection_name(self, tmp_path):
        palace_path = str(tmp_path / "palace")
        col = get_collection(palace_path, collection_name="custom_col")
        assert col.name == "custom_col"

    def test_collection_is_usable(self, tmp_path):
        palace_path = str(tmp_path / "palace")
        col = get_collection(palace_path)
        col.add(
            ids=["test1"],
            documents=["hello world"],
            metadatas=[{"wing": "test"}],
        )
        assert col.count() == 1

    def test_chmod_failure_does_not_raise(self, tmp_path):
        palace_path = str(tmp_path / "palace")
        with patch("mempalace.palace.os.chmod", side_effect=OSError("perm denied")):
            col = get_collection(palace_path)
        assert col is not None


class TestFileAlreadyMined:
    @pytest.fixture
    def collection(self, tmp_path):
        palace_path = str(tmp_path / "palace")
        return get_collection(palace_path)

    def test_file_not_found(self, collection):
        assert file_already_mined(collection, "/nonexistent/file.py") is False

    def test_file_found_no_mtime_check(self, collection):
        collection.add(
            ids=["d1"],
            documents=["content"],
            metadatas=[{"source_file": "/test/file.py", "wing": "test"}],
        )
        assert file_already_mined(collection, "/test/file.py") is True

    def test_file_mtime_matches(self, collection, tmp_path):
        test_file = tmp_path / "src.py"
        test_file.write_text("code", encoding="utf-8")
        mtime = os.path.getmtime(str(test_file))

        collection.add(
            ids=["d1"],
            documents=["content"],
            metadatas=[{
                "source_file": str(test_file),
                "source_mtime": str(mtime),
                "wing": "test",
            }],
        )
        assert file_already_mined(collection, str(test_file), check_mtime=True) is True

    def test_file_mtime_outdated(self, collection, tmp_path):
        test_file = tmp_path / "src.py"
        test_file.write_text("old code", encoding="utf-8")
        old_mtime = os.path.getmtime(str(test_file))

        collection.add(
            ids=["d1"],
            documents=["content"],
            metadatas=[{
                "source_file": str(test_file),
                "source_mtime": str(old_mtime - 100),
                "wing": "test",
            }],
        )
        assert file_already_mined(collection, str(test_file), check_mtime=True) is False

    def test_file_mtime_missing_in_metadata(self, collection, tmp_path):
        test_file = tmp_path / "src.py"
        test_file.write_text("code", encoding="utf-8")

        collection.add(
            ids=["d1"],
            documents=["content"],
            metadatas=[{"source_file": str(test_file), "wing": "test"}],
        )
        assert file_already_mined(collection, str(test_file), check_mtime=True) is False

    def test_collection_exception_returns_false(self):
        mock_col = MagicMock()
        mock_col.get.side_effect = RuntimeError("db locked")
        assert file_already_mined(mock_col, "/any/file.py") is False

    def test_empty_ids_returns_false(self, collection):
        assert file_already_mined(collection, "no_such_file.txt") is False


class TestSkipDirs:
    def test_common_dirs_present(self):
        expected = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
        assert expected.issubset(SKIP_DIRS)

    def test_is_a_set(self):
        assert isinstance(SKIP_DIRS, set)
