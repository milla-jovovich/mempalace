import os
import json
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


def test_claude_code_jsonl_user_type():
    """Claude Code JSONL uses type \"user\", not \"human\" (#111)."""
    lines = [
        '{"type":"user","message":{"content":"fix the bug in auth.py"}}',
        '{"type":"assistant","message":{"content":[{"type":"text","text":"I will look."}]}}',
    ]
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8")
    f.write("\n".join(lines))
    f.close()
    try:
        result = normalize(f.name)
        assert "fix the bug" in result
    finally:
        os.unlink(f.name)
