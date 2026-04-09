"""Tests for cursor_miner: message extraction and exchange-pair chunking."""

from mempalace.cursor_miner import (
    _extract_user_text,
    _extract_assistant_text,
    chunk_cursor_session,
    scan_cursor_dbs,
)


# ---------------------------------------------------------------------------
# _extract_user_text
# ---------------------------------------------------------------------------


def test_extract_user_text_from_user_query_tag():
    content = [{"type": "text", "text": "<user_query>\nDo the thing\n</user_query>"}]
    assert _extract_user_text(content) == "Do the thing"


def test_extract_user_text_plain():
    content = [{"type": "text", "text": "Plain question without tags"}]
    assert _extract_user_text(content) == "Plain question without tags"


def test_extract_user_text_skips_pure_system_context():
    content = [{"type": "text", "text": "<system_reminder>Do not edit</system_reminder>"}]
    assert _extract_user_text(content) == ""


def test_extract_user_text_string_content():
    assert _extract_user_text("<user_query>Hello</user_query>") == "Hello"


# ---------------------------------------------------------------------------
# _extract_assistant_text
# ---------------------------------------------------------------------------


def test_extract_assistant_text_joins_parts():
    content = [
        {"type": "text", "text": "Part one."},
        {"type": "tool-call", "toolName": "Glob"},
        {"type": "text", "text": "Part two."},
    ]
    result = _extract_assistant_text(content)
    assert "Part one." in result
    assert "Part two." in result
    assert "Glob" not in result  # tool-call not included


def test_extract_assistant_text_string_content():
    assert _extract_assistant_text("Just a string") == "Just a string"


# ---------------------------------------------------------------------------
# chunk_cursor_session
# ---------------------------------------------------------------------------


def _msg(role, text):
    return {"role": role, "content": [{"type": "text", "text": text}]}


def test_chunk_pairs_user_and_assistant():
    messages = [
        _msg("user", "<user_query>What is X?</user_query>"),
        _msg("assistant", "X is a thing. " * 5),
    ]
    chunks = chunk_cursor_session(messages)
    assert len(chunks) == 1
    assert "[User]" in chunks[0]["content"]
    assert "[Cursor]" in chunks[0]["content"]
    assert "What is X?" in chunks[0]["content"]


def test_chunk_skips_system_user_messages():
    messages = [
        _msg("user", "<system_reminder>No edits</system_reminder>"),
        _msg("assistant", "OK"),
        _msg("user", "<user_query>Real question</user_query>"),
        _msg("assistant", "Real answer. " * 5),
    ]
    chunks = chunk_cursor_session(messages)
    assert len(chunks) == 1
    assert "Real question" in chunks[0]["content"]


def test_chunk_index_sequential():
    messages = [
        _msg("user", "<user_query>First question here?</user_query>"),
        _msg("assistant", "A1 " * 20),
        _msg("user", "<user_query>Second question here?</user_query>"),
        _msg("assistant", "A2 " * 20),
    ]
    chunks = chunk_cursor_session(messages)
    assert len(chunks) == 2
    assert [c["chunk_index"] for c in chunks] == [0, 1]


def test_chunk_without_assistant_still_produces_chunk():
    messages = [_msg("user", "<user_query>An orphan question without a reply?</user_query>")]
    chunks = chunk_cursor_session(messages)
    assert len(chunks) == 1
    assert "[Cursor]" not in chunks[0]["content"]


def test_assistant_text_capped():
    long_answer = "word " * 1000
    messages = [
        _msg("user", "<user_query>Tell me everything</user_query>"),
        _msg("assistant", long_answer),
    ]
    chunks = chunk_cursor_session(messages)
    assert len(chunks) == 1
    # Content should be capped (ASSISTANT_TEXT_LIMIT = 1500 chars)
    assert len(chunks[0]["content"]) < 5000


# ---------------------------------------------------------------------------
# scan_cursor_dbs
# ---------------------------------------------------------------------------


def test_scan_cursor_dbs_empty_dir(tmp_path):
    assert scan_cursor_dbs(str(tmp_path)) == []


def test_scan_cursor_dbs_finds_store_db(tmp_path):
    import sqlite3

    workspace = tmp_path / "abc123"
    session = workspace / "sess456"
    session.mkdir(parents=True)
    db_path = session / "store.db"
    # Minimal valid SQLite DB
    con = sqlite3.connect(str(db_path))
    con.execute("CREATE TABLE blobs (id TEXT PRIMARY KEY, data BLOB)")
    con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    con.commit()
    con.close()

    results = scan_cursor_dbs(str(tmp_path))
    assert len(results) == 1
    sid, path = results[0]
    assert sid == "abc123/sess456"
    assert path.endswith("store.db")


def test_scan_cursor_dbs_ignores_nonexistent(tmp_path):
    results = scan_cursor_dbs(str(tmp_path / "does_not_exist"))
    assert results == []
