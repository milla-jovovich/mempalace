"""
test_palace.py -- Direct unit tests for palace.py.

Covers get_collection, file_already_mined (including mtime tolerance),
and SKIP_DIRS constants.
"""

import os

from mempalace.palace import SKIP_DIRS, file_already_mined, get_collection


class TestGetCollection:
    def test_creates_collection_if_missing(self, palace_path):
        col = get_collection(palace_path, "test_col")
        assert col is not None
        assert col.name == "test_col"

    def test_returns_existing_collection(self, palace_path):
        col1 = get_collection(palace_path, "test_col")
        col1.add(ids=["d1"], documents=["hello"], metadatas=[{"wing": "w"}])
        col2 = get_collection(palace_path, "test_col")
        assert col2.count() == 1

    def test_creates_palace_directory(self, tmp_dir):
        new_path = os.path.join(tmp_dir, "new_palace")
        col = get_collection(new_path)
        assert col is not None
        assert os.path.isdir(new_path)


class TestFileAlreadyMined:
    def test_false_for_new_file(self, collection):
        assert file_already_mined(collection, "never_seen.py") is False

    def test_true_for_known_file(self, collection):
        collection.add(
            ids=["d1"],
            documents=["content"],
            metadatas=[{"source_file": "known.py", "wing": "w", "room": "r"}],
        )
        assert file_already_mined(collection, "known.py") is True

    def test_mtime_exact_match(self, collection, tmp_dir):
        src = os.path.join(tmp_dir, "file.txt")
        with open(src, "w") as f:
            f.write("data")
        mtime = os.path.getmtime(src)
        collection.add(
            ids=["d1"],
            documents=["content"],
            metadatas=[{"source_file": src, "source_mtime": mtime, "wing": "w", "room": "r"}],
        )
        assert file_already_mined(collection, src, check_mtime=True) is True

    def test_mtime_tolerance(self, collection, tmp_dir):
        """A tiny float rounding difference should still count as mined."""
        src = os.path.join(tmp_dir, "file.txt")
        with open(src, "w") as f:
            f.write("data")
        mtime = os.path.getmtime(src)
        # Simulate a tiny rounding error from serialization
        stored = mtime + 1e-7
        collection.add(
            ids=["d1"],
            documents=["content"],
            metadatas=[{"source_file": src, "source_mtime": stored, "wing": "w", "room": "r"}],
        )
        assert file_already_mined(collection, src, check_mtime=True) is True

    def test_mtime_detects_modification(self, collection, tmp_dir):
        """If the file was modified after mining, it should return False."""
        src = os.path.join(tmp_dir, "file.txt")
        with open(src, "w") as f:
            f.write("original")
        old_mtime = os.path.getmtime(src)
        collection.add(
            ids=["d1"],
            documents=["content"],
            metadatas=[{"source_file": src, "source_mtime": old_mtime, "wing": "w", "room": "r"}],
        )
        # Modify the file so mtime changes
        os.utime(src, (old_mtime + 10, old_mtime + 10))
        assert file_already_mined(collection, src, check_mtime=True) is False

    def test_mtime_missing_metadata(self, collection, tmp_dir):
        """If source_mtime was never stored, treat as not mined."""
        src = os.path.join(tmp_dir, "file.txt")
        with open(src, "w") as f:
            f.write("data")
        collection.add(
            ids=["d1"],
            documents=["content"],
            metadatas=[{"source_file": src, "wing": "w", "room": "r"}],
        )
        assert file_already_mined(collection, src, check_mtime=True) is False


class TestSkipDirs:
    def test_contains_expected_entries(self):
        for d in (".git", "node_modules", "__pycache__", ".venv", ".mempalace"):
            assert d in SKIP_DIRS

    def test_is_a_set(self):
        assert isinstance(SKIP_DIRS, set)
