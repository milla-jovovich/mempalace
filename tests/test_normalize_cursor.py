import json
import sqlite3
from pathlib import Path

from mempalace.normalize import normalize


def _make_cursor_db(path: Path, payload: dict):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "INSERT INTO ItemTable(key, value) VALUES (?, ?)",
        ("composer.composerData", json.dumps(payload)),
    )
    conn.commit()
    conn.close()


def test_normalize_cursor_sqlite_workspace_db(tmp_path):
    db_path = tmp_path / "state.vscdb"
    payload = {
        "allComposers": [
            {
                "messages": [
                    {"role": "user", "content": "How do I fix auth timeout?"},
                    {"role": "assistant", "content": "Start with token expiry checks."},
                    {"role": "user", "text": "Give me exact steps."},
                    {
                        "role": "assistant",
                        "markdown": "1) reproduce\n2) inspect refresh flow\n3) patch",
                    },
                ]
            }
        ]
    }
    _make_cursor_db(db_path, payload)

    normalized = normalize(str(db_path))

    assert "> How do I fix auth timeout?" in normalized
    assert "Start with token expiry checks." in normalized
    assert "> Give me exact steps." in normalized
    assert "inspect refresh flow" in normalized


def test_normalize_non_cursor_sqlite_returns_empty(tmp_path):
    db_path = tmp_path / "random.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE foo (id INTEGER PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO foo(value) VALUES ('hello')")
    conn.commit()
    conn.close()

    assert normalize(str(db_path)) == ""
