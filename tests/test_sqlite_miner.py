"""Unit tests for sqlite_miner pure functions (no chromadb needed)."""

import sqlite3
import os
from pathlib import Path

from mempalace.sqlite_miner import (
    read_sqlite_file,
    chunk_sqlite_content,
    detect_sqlite_room,
    scan_sqlite_files,
)


class TestReadSqliteFile:
    def test_read_schema(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("CREATE INDEX idx_users_name ON users(name)")
        conn.commit()
        conn.close()
        content = read_sqlite_file(db_path)
        assert "SQLite3 Database" in content
        assert "CREATE TABLE users" in content
        assert "CREATE INDEX idx_users_name" in content

    def test_read_table_data(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE items (id INTEGER, value TEXT)")
        conn.execute("INSERT INTO items VALUES (1, 'hello'), (2, 'world')")
        conn.commit()
        conn.close()
        content = read_sqlite_file(db_path)
        assert "TABLE DATA: items" in content
        assert "INSERT INTO 'items'" in content
        assert "'hello'" in content

    def test_read_table_counts(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE t1 (id INTEGER)")
        conn.execute("CREATE TABLE t2 (id INTEGER)")
        conn.execute("INSERT INTO t1 VALUES (1), (2), (3)")
        conn.commit()
        conn.close()
        content = read_sqlite_file(db_path)
        assert "TABLE COUNTS" in content
        assert "t1: 3 rows" in content
        assert "t2: 0 rows" in content

    def test_read_nonexistent_file(self):
        content = read_sqlite_file(Path("/nonexistent/file.db"))
        assert "Error" in content


class TestChunkSqliteContent:
    def test_chunk_schema(self):
        content = "-- SQLite3 Database: test.db\n" + "=" * 60 + "\nSCHEMA\n" + "=" * 60
        chunks = chunk_sqlite_content(content)
        assert len(chunks) >= 1
        assert all("content" in c and "chunk_index" in c for c in chunks)

    def test_chunk_large_content(self):
        content = "Line\n" * 500
        chunks = chunk_sqlite_content(content)
        assert len(chunks) >= 2

    def test_chunk_empty(self):
        chunks = chunk_sqlite_content("")
        assert chunks == []

    def test_chunk_small_content(self):
        content = "small"
        chunks = chunk_sqlite_content(content)
        assert chunks == []


class TestDetectSqliteRoom:
    def test_schema_room(self, tmp_path):
        content = "CREATE TABLE users (id INT);\nCREATE INDEX idx ON users(id);"
        filepath = tmp_path / "schema.db"
        filepath.touch()
        assert detect_sqlite_room(filepath, content) == "schema"

    def test_auth_room_by_filename(self, tmp_path):
        content = "some data"
        filepath = tmp_path / "user_auth.db"
        filepath.touch()
        assert detect_sqlite_room(filepath, content) == "auth"

    def test_auth_room_by_content(self, tmp_path):
        content = "user table and account data"
        filepath = tmp_path / "mydb.db"
        filepath.touch()
        assert detect_sqlite_room(filepath, content) == "auth"

    def test_logs_room(self, tmp_path):
        content = "event log and audit history"
        filepath = tmp_path / "app_logs.db"
        filepath.touch()
        assert detect_sqlite_room(filepath, content) == "logs"

    def test_data_fallback(self, tmp_path):
        content = "some random database"
        filepath = tmp_path / "random.db"
        filepath.touch()
        assert detect_sqlite_room(filepath, content) == "data"


class TestScanSqliteFiles:
    def test_scan_finds_sqlite_files(self, tmp_path):
        (tmp_path / "data.db").write_bytes(b"SQLite format 3\x00")
        (tmp_path / "app.sqlite").write_bytes(b"SQLite format 3\x00")
        (tmp_path / "test.sqlite3").write_bytes(b"SQLite format 3\x00")
        (tmp_path / "notdb.txt").write_text("hello")
        files = scan_sqlite_files(str(tmp_path))
        extensions = {f.suffix for f in files}
        assert ".db" in extensions
        assert ".sqlite" in extensions
        assert ".sqlite3" in extensions
        assert ".txt" not in extensions

    def test_scan_skips_symlinks(self, tmp_path):
        db_path = tmp_path / "real.db"
        db_path.write_bytes(b"SQLite format 3\x00")
        link_path = tmp_path / "link.db"
        os.symlink(str(db_path), str(link_path))
        files = scan_sqlite_files(str(tmp_path))
        assert len(files) == 1
        assert files[0].name == "real.db"

    def test_scan_skips_git_dir(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "objects.db").write_bytes(b"SQLite format 3\x00")
        (tmp_path / "app.db").write_bytes(b"SQLite format 3\x00")
        files = scan_sqlite_files(str(tmp_path))
        names = [f.name for f in files]
        assert "objects.db" not in names
        assert "app.db" in names

    def test_scan_empty_dir(self, tmp_path):
        files = scan_sqlite_files(str(tmp_path))
        assert files == []
