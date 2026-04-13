"""Regression tests for the Chroma migration utility."""

import sqlite3
from pathlib import Path
from unittest.mock import patch

from mempalace.migrate import detect_chromadb_version, extract_drawers_from_sqlite, migrate


def _create_sqlite_fixture(db_path: Path, *, schema_str: bool = False, queue_table: bool = False):
    """Build the minimal SQLite schema migrate.py expects to inspect."""
    conn = sqlite3.connect(db_path)
    if schema_str:
        conn.execute("CREATE TABLE collections (id TEXT PRIMARY KEY, name TEXT, schema_str TEXT)")
        conn.execute(
            "INSERT INTO collections (id, name, schema_str) VALUES ('raw-col', 'mempalace_drawers', '{}')"
        )
    else:
        conn.execute("CREATE TABLE collections (id TEXT PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO collections (id, name) VALUES ('raw-col', 'mempalace_drawers')")

    if queue_table:
        conn.execute("CREATE TABLE embeddings_queue (id INTEGER PRIMARY KEY)")

    conn.execute(
        "CREATE TABLE segments (id TEXT PRIMARY KEY, type TEXT, scope TEXT, collection TEXT)"
    )
    conn.execute(
        "INSERT INTO segments (id, type, scope, collection) VALUES (?, ?, ?, ?)",
        ("raw-seg", "urn:chroma:segment/metadata/sqlite", "METADATA", "raw-col"),
    )
    conn.execute(
        "CREATE TABLE embeddings (id INTEGER PRIMARY KEY, segment_id TEXT, embedding_id TEXT)"
    )
    conn.execute(
        """
        CREATE TABLE embedding_metadata (
            id INTEGER,
            key TEXT,
            string_value TEXT,
            int_value INTEGER,
            float_value REAL,
            bool_value INTEGER
        )
        """
    )
    conn.commit()
    conn.close()


def test_extract_drawers_from_sqlite_reads_documents_and_typed_metadata(tmp_path):
    db_path = tmp_path / "chroma.sqlite3"
    _create_sqlite_fixture(db_path)

    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT INTO embeddings (id, segment_id, embedding_id) VALUES (?, ?, ?)",
        [(1, "raw-seg", "drawer-1"), (2, "raw-seg", "drawer-2")],
    )
    conn.executemany(
        """
        INSERT INTO embedding_metadata (id, key, string_value, int_value, float_value, bool_value)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (1, "chroma:document", "Document body", None, None, None),
            (1, "wing", "alpha", None, None, None),
            (1, "chunk_index", None, 3, None, None),
            (1, "score", None, None, 1.5, None),
            (1, "current", None, None, None, 1),
            # drawer-2 is intentionally missing chroma:document and should be skipped.
            (2, "wing", "beta", None, None, None),
        ],
    )
    conn.commit()
    conn.close()

    drawers = extract_drawers_from_sqlite(str(db_path))

    assert drawers == [
        {
            "id": "drawer-1",
            "document": "Document body",
            "metadata": {"wing": "alpha", "chunk_index": 3, "score": 1.5, "current": True},
        }
    ]


def test_extract_drawers_from_sqlite_ignores_sibling_support_collection(tmp_path):
    db_path = tmp_path / "chroma.sqlite3"
    _create_sqlite_fixture(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO collections (id, name) VALUES (?, ?)", ("support-col", "mempalace_support"))
    conn.execute(
        "INSERT INTO segments (id, type, scope, collection) VALUES (?, ?, ?, ?)",
        ("support-seg", "urn:chroma:segment/metadata/sqlite", "METADATA", "support-col"),
    )
    conn.executemany(
        "INSERT INTO embeddings (id, segment_id, embedding_id) VALUES (?, ?, ?)",
        [(1, "raw-seg", "drawer-1"), (2, "support-seg", "support-1")],
    )
    conn.executemany(
        """
        INSERT INTO embedding_metadata (id, key, string_value, int_value, float_value, bool_value)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (1, "chroma:document", "Drawer body", None, None, None),
            (1, "wing", "alpha", None, None, None),
            (2, "chroma:document", "Support helper", None, None, None),
            (2, "support_kind", "preference", None, None, None),
        ],
    )
    conn.commit()
    conn.close()

    drawers = extract_drawers_from_sqlite(str(db_path))

    assert drawers == [
        {
            "id": "drawer-1",
            "document": "Drawer body",
            "metadata": {"wing": "alpha"},
        }
    ]


def test_detect_chromadb_version_distinguishes_known_layouts(tmp_path):
    one_x = tmp_path / "one_x.sqlite3"
    zero_six = tmp_path / "zero_six.sqlite3"
    unknown = tmp_path / "unknown.sqlite3"

    _create_sqlite_fixture(one_x, schema_str=True)
    _create_sqlite_fixture(zero_six, queue_table=True)
    _create_sqlite_fixture(unknown)

    assert detect_chromadb_version(str(one_x)) == "1.x"
    assert detect_chromadb_version(str(zero_six)) == "0.6.x"
    assert detect_chromadb_version(str(unknown)) == "unknown"


def test_migrate_returns_false_when_database_is_missing(tmp_path, capsys):
    result = migrate(str(tmp_path / "missing-palace"))

    assert result is False
    assert "No palace database found" in capsys.readouterr().out


def test_migrate_short_circuits_when_palace_is_already_readable(tmp_path, capsys):
    palace = tmp_path / "palace"
    palace.mkdir()
    db_path = palace / "chroma.sqlite3"
    _create_sqlite_fixture(db_path, queue_table=True)

    class _ReadableCollection:
        def count(self):
            return 3

    class _ReadableClient:
        def __init__(self, path):
            self.path = path

        def get_collection(self, name):
            assert name == "mempalace_drawers"
            return _ReadableCollection()

    with patch("chromadb.PersistentClient", _ReadableClient):
        result = migrate(str(palace))

    output = capsys.readouterr().out
    assert result is True
    assert "No migration needed." in output


def test_migrate_dry_run_extracts_from_sqlite_when_client_cannot_read(tmp_path, capsys):
    palace = tmp_path / "palace"
    palace.mkdir()
    db_path = palace / "chroma.sqlite3"
    _create_sqlite_fixture(db_path, schema_str=True)

    drawers = [
        {
            "id": "drawer-1",
            "document": "Rollback plan",
            "metadata": {"wing": "ops", "room": "plans"},
        },
        {
            "id": "drawer-2",
            "document": "Checkpoint list",
            "metadata": {"wing": "ops", "room": "plans"},
        },
    ]

    class _UnreadableClient:
        def __init__(self, path):
            raise RuntimeError("schema mismatch")

    with patch("chromadb.PersistentClient", _UnreadableClient), patch(
        "mempalace.migrate.extract_drawers_from_sqlite",
        return_value=drawers,
    ):
        result = migrate(str(palace), dry_run=True)

    output = capsys.readouterr().out
    assert result is True
    assert "Palace is NOT readable" in output
    assert "DRY RUN" in output
    assert "Would migrate 2 drawers." in output


def test_migrate_reports_nothing_when_sqlite_extract_is_empty(tmp_path, capsys):
    palace = tmp_path / "palace"
    palace.mkdir()
    db_path = palace / "chroma.sqlite3"
    _create_sqlite_fixture(db_path, schema_str=True)

    class _UnreadableClient:
        def __init__(self, path):
            raise RuntimeError("schema mismatch")

    with patch("chromadb.PersistentClient", _UnreadableClient), patch(
        "mempalace.migrate.extract_drawers_from_sqlite",
        return_value=[],
    ):
        result = migrate(str(palace))

    assert result is True
    assert "Nothing to migrate." in capsys.readouterr().out


def test_migrate_rebuilds_and_warns_on_count_mismatch(tmp_path, capsys):
    palace = tmp_path / "palace"
    palace.mkdir()
    db_path = palace / "chroma.sqlite3"
    _create_sqlite_fixture(db_path, queue_table=True)

    drawers = [
        {
            "id": "drawer-1",
            "document": "Rollback plan",
            "metadata": {"wing": "ops", "room": "plans"},
        },
        {
            "id": "drawer-2",
            "document": "Checkpoint list",
            "metadata": {"wing": "ops", "room": "plans"},
        },
    ]

    temp_palace = tmp_path / "rebuilt-palace"
    temp_palace.mkdir()

    class _Collection:
        def __init__(self):
            self.add_calls = []

        def add(self, ids, documents, metadatas):
            self.add_calls.append((ids, documents, metadatas))

        def count(self):
            return 1

    class _ReadableClient:
        def __init__(self, path):
            self.path = path
            self.collection = _Collection()

        def get_or_create_collection(self, name, metadata=None):
            assert name == "mempalace_drawers"
            assert metadata == {"hnsw:space": "cosine"}
            return self.collection

    def _fake_client(path):
        if path == str(palace):
            raise RuntimeError("schema mismatch")
        return _ReadableClient(path)

    with patch("chromadb.PersistentClient", side_effect=_fake_client), patch(
        "mempalace.migrate.extract_drawers_from_sqlite",
        return_value=drawers,
    ), patch("tempfile.mkdtemp", return_value=str(temp_palace)), patch(
        "mempalace.repair.backfill_retrieval_signals"
    ) as mock_backfill:
        result = migrate(str(palace))

    output = capsys.readouterr().out
    assert result is True
    assert "Migration complete." in output
    assert "WARNING: Expected 2, got 1" in output
    mock_backfill.assert_called_once_with(palace_path=str(palace), dry_run=False)
    backups = list(tmp_path.glob("palace.pre-migrate.*"))
    assert backups
    assert palace.is_dir()
