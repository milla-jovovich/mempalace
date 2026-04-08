import os
import json
import sqlite3
import tempfile
from mempalace.normalize import normalize


def test_plain_text():
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    f.write("Hello world\nSecond line\n")
    f.close()
    result = normalize(f.name)
    assert "Hello world" in result
    os.unlink(f.name)


def test_claude_json():
    data = [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}]
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    result = normalize(f.name)
    assert "Hi" in result
    os.unlink(f.name)


def test_empty():
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    f.close()
    result = normalize(f.name)
    assert result.strip() == ""
    os.unlink(f.name)


def test_opencode_sqlite():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    conn = sqlite3.connect(f.name)
    conn.executescript("""
        CREATE TABLE project (id TEXT PRIMARY KEY, worktree TEXT, name TEXT,
            time_created INT, time_updated INT, sandboxes TEXT DEFAULT '[]');
        CREATE TABLE session (id TEXT PRIMARY KEY, project_id TEXT, slug TEXT DEFAULT '',
            directory TEXT DEFAULT '/', title TEXT DEFAULT '', version TEXT DEFAULT '1',
            time_created INT, time_updated INT);
        CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT,
            time_created INT, time_updated INT, data TEXT);
        CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT,
            time_created INT, time_updated INT, data TEXT);
        INSERT INTO project VALUES ('p1','/home/user/app','app',0,0,'[]');
        INSERT INTO session VALUES ('s1','p1','','/','test','1',0,0);
        INSERT INTO message VALUES ('m1','s1',1,1,'{"role":"user"}');
        INSERT INTO part VALUES ('t1','m1','s1',1,1,'{"type":"text","text":"Why Clerk over Auth0?"}');
        INSERT INTO message VALUES ('m2','s1',2,2,'{"role":"assistant"}');
        INSERT INTO part VALUES ('t2','m2','s1',2,2,'{"type":"text","text":"Better DX and lower pricing."}');
    """)
    conn.commit()
    conn.close()
    result = normalize(f.name)
    assert "> Why Clerk" in result
    assert "Better DX" in result
    os.unlink(f.name)
