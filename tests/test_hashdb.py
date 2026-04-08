import os
import tempfile
import shutil
from pathlib import Path
import hashlib

from mempalace.miner import BloomFilter, ContentHashDB


class TestBloomFilter:
    def test_add_and_check(self):
        bf = BloomFilter(capacity=1000)
        bf.add("hello")
        assert "hello" in bf
        assert "world" not in bf

    def test_false_positive_rate(self):
        bf = BloomFilter(capacity=10000, false_positive_rate=0.1)
        items = [f"item_{i}" for i in range(1000)]
        for item in items:
            bf.add(item)

        false_positives = sum(1 for i in range(1000, 2000) if f"item_{i}" in bf)
        assert false_positives < 150

    def test_save_and_load(self):
        bf1 = BloomFilter(capacity=1000)
        bf1.add("test")
        bf1.add("data")

        tmpdir = tempfile.mkdtemp()
        try:
            bf1.save(os.path.join(tmpdir, "bloom.json"))
            bf2 = BloomFilter.load(os.path.join(tmpdir, "bloom.json"))
            assert "test" in bf2
            assert "data" in bf2
        finally:
            shutil.rmtree(tmpdir)


class TestContentHashDB:
    def test_compute_hash(self):
        tmpdir = tempfile.mkdtemp()
        try:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("hello world")

            db = ContentHashDB(os.path.join(tmpdir, "hashes.json"))
            content_hash = db.compute_hash(test_file)

            assert len(content_hash) == 64
            assert content_hash == hashlib.sha256(b"hello world").hexdigest()
        finally:
            shutil.rmtree(tmpdir)

    def test_check_and_add_new_file(self):
        tmpdir = tempfile.mkdtemp()
        try:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("new content")

            db = ContentHashDB(os.path.join(tmpdir, "hashes.json"))
            is_duplicate = db.check_and_add(test_file)

            assert is_duplicate is False
            assert str(test_file) in db.hashes
        finally:
            shutil.rmtree(tmpdir)

    def test_check_and_add_duplicate_file(self):
        tmpdir = tempfile.mkdtemp()
        try:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("same content")

            db = ContentHashDB(os.path.join(tmpdir, "hashes.json"))
            db.check_and_add(test_file)

            is_duplicate = db.check_and_add(test_file)

            assert is_duplicate is True
        finally:
            shutil.rmtree(tmpdir)

    def test_different_files_same_content(self):
        tmpdir = tempfile.mkdtemp()
        try:
            file1 = Path(tmpdir) / "file1.txt"
            file2 = Path(tmpdir) / "file2.txt"
            file1.write_text("identical content")
            file2.write_text("identical content")

            db = ContentHashDB(os.path.join(tmpdir, "hashes.json"))
            db.check_and_add(file1)
            is_dup = db.check_and_add(file2)

            assert is_dup is True
        finally:
            shutil.rmtree(tmpdir)

    def test_different_content_not_duplicate(self):
        tmpdir = tempfile.mkdtemp()
        try:
            file1 = Path(tmpdir) / "file1.txt"
            file2 = Path(tmpdir) / "file2.txt"
            file1.write_text("content A")
            file2.write_text("content B")

            db = ContentHashDB(os.path.join(tmpdir, "hashes.json"))
            db.check_and_add(file1)
            is_dup = db.check_and_add(file2)

            assert is_dup is False
        finally:
            shutil.rmtree(tmpdir)

    def test_persistence(self):
        tmpdir = tempfile.mkdtemp()
        try:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("persistent content")

            db1 = ContentHashDB(os.path.join(tmpdir, "hashes.json"))
            db1.check_and_add(test_file)

            db2 = ContentHashDB(os.path.join(tmpdir, "hashes.json"))
            is_dup = db2.check_and_add(test_file)

            assert is_dup is True
            assert str(test_file) in db2.hashes
        finally:
            shutil.rmtree(tmpdir)

    def test_clear(self):
        tmpdir = tempfile.mkdtemp()
        try:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("content")

            db = ContentHashDB(os.path.join(tmpdir, "hashes.json"))
            db.check_and_add(test_file)
            assert str(test_file) in db.hashes

            db.clear()
            assert len(db.hashes) == 0
            assert "content" not in db.bloom

            is_dup = db.check_and_add(test_file)
            assert is_dup is False
        finally:
            shutil.rmtree(tmpdir)
