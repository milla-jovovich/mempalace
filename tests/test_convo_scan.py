from mempalace.convo_miner import scan_convos


def test_scan_convos_includes_cursor_state_vscdb(tmp_path):
    workspace = tmp_path / "Cursor" / "User" / "workspaceStorage" / "abc123"
    workspace.mkdir(parents=True)
    db_path = workspace / "state.vscdb"
    db_path.write_bytes(b"SQLite format 3\x00dummy")

    files = scan_convos(str(tmp_path))
    assert db_path in files


def test_scan_convos_skips_unrelated_db_files(tmp_path):
    keep = tmp_path / "chat.json"
    keep.write_text('[{"role":"user","content":"hello"}]', encoding="utf-8")

    skip_db = tmp_path / "analytics.db"
    skip_db.write_bytes(b"SQLite format 3\x00dummy")

    files = scan_convos(str(tmp_path))

    assert keep in files
    assert skip_db not in files
