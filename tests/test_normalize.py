import os
import json
import tempfile
from mempalace.normalize import normalize, _try_cursor_jsonl


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


# --- Cursor agent transcript JSONL ---


def _write_jsonl(lines, suffix=".jsonl"):
    """Helper: write a list of dicts as JSONL to a temp file."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False)
    for entry in lines:
        f.write(json.dumps(entry) + "\n")
    f.close()
    return f.name


def test_cursor_jsonl_basic():
    """Minimal two-turn Cursor agent transcript round-trips correctly."""
    path = _write_jsonl([
        {"role": "user", "message": {"content": [{"type": "text", "text": "How do I reverse a list?"}]}},
        {"role": "assistant", "message": {"content": [{"type": "text", "text": "Use list.reverse() or slicing [::-1]."}]}},
    ])
    result = normalize(path)
    assert "> How do I reverse a list?" in result
    assert "Use list.reverse() or slicing [::-1]." in result
    os.unlink(path)


def test_cursor_jsonl_multi_turn():
    """Multi-turn conversation preserves all turns in order."""
    path = _write_jsonl([
        {"role": "user", "message": {"content": [{"type": "text", "text": "What is Python?"}]}},
        {"role": "assistant", "message": {"content": [{"type": "text", "text": "A programming language."}]}},
        {"role": "user", "message": {"content": [{"type": "text", "text": "Is it compiled?"}]}},
        {"role": "assistant", "message": {"content": [{"type": "text", "text": "It is interpreted."}]}},
    ])
    result = normalize(path)
    lines = result.split("\n")
    user_lines = [line for line in lines if line.startswith(">")]
    assert len(user_lines) == 2
    assert "> What is Python?" in result
    assert "> Is it compiled?" in result
    assert "A programming language." in result
    assert "It is interpreted." in result
    os.unlink(path)


def test_cursor_jsonl_skips_empty_content():
    """Entries with empty text are silently skipped."""
    path = _write_jsonl([
        {"role": "user", "message": {"content": [{"type": "text", "text": "Hi"}]}},
        {"role": "assistant", "message": {"content": [{"type": "text", "text": ""}]}},
        {"role": "assistant", "message": {"content": [{"type": "text", "text": "Hello!"}]}},
    ])
    result = normalize(path)
    assert "> Hi" in result
    assert "Hello!" in result
    os.unlink(path)


def test_cursor_jsonl_rejects_single_message():
    """A file with fewer than 2 messages is not recognized as Cursor JSONL."""
    path = _write_jsonl([
        {"role": "user", "message": {"content": [{"type": "text", "text": "lonely message"}]}},
    ])
    result = normalize(path)
    assert not result.strip().startswith(">")
    os.unlink(path)


def test_cursor_jsonl_skips_entries_without_message_key():
    """Entries with role but no message dict are skipped."""
    path = _write_jsonl([
        {"role": "user"},
        {"role": "user", "message": {"content": [{"type": "text", "text": "Q"}]}},
        {"role": "assistant", "message": {"content": [{"type": "text", "text": "A"}]}},
    ])
    result = normalize(path)
    assert "> Q" in result
    assert "A" in result
    os.unlink(path)


def test_cursor_jsonl_rejects_claude_code_jsonl():
    """Claude Code JSONL (top-level 'type' key) must not match the Cursor parser."""
    content = "\n".join([
        json.dumps({"type": "human", "message": {"content": "Hi from Claude Code"}}),
        json.dumps({"type": "assistant", "message": {"content": "Hello back"}}),
    ])
    assert _try_cursor_jsonl(content) is None


def test_cursor_jsonl_ignores_non_cursor_jsonl():
    """Claude Code JSONL is handled by its own parser (integration check)."""
    path = _write_jsonl([
        {"type": "human", "message": {"content": "Hi from Claude Code"}},
        {"type": "assistant", "message": {"content": "Hello back"}},
    ])
    result = normalize(path)
    assert result.strip()  # some parser picks it up
    os.unlink(path)


def test_cursor_jsonl_multiple_content_blocks():
    """Content arrays with several text blocks are joined."""
    path = _write_jsonl([
        {"role": "user", "message": {"content": [
            {"type": "text", "text": "First part."},
            {"type": "text", "text": "Second part."},
        ]}},
        {"role": "assistant", "message": {"content": [{"type": "text", "text": "Got it."}]}},
    ])
    result = normalize(path)
    assert "First part." in result
    assert "Second part." in result
    assert "Got it." in result
    os.unlink(path)


def test_cursor_jsonl_tolerates_malformed_lines():
    """Malformed JSON lines and unexpected entry shapes are skipped gracefully."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    f.write("NOT VALID JSON\n")
    f.write(json.dumps({"role": "user", "message": {"content": [{"type": "text", "text": "Q1"}]}}) + "\n")
    f.write(json.dumps({"unexpected": "shape"}) + "\n")
    f.write(json.dumps({"role": "assistant", "message": {"content": [{"type": "text", "text": "A1"}]}}) + "\n")
    f.close()
    result = normalize(f.name)
    assert "> Q1" in result
    assert "A1" in result
    os.unlink(f.name)


def test_cursor_jsonl_requires_list_content():
    """Entries where message.content is a plain string (not list) don't set the Cursor flag."""
    path = _write_jsonl([
        {"role": "user", "message": {"content": "plain string"}},
        {"role": "assistant", "message": {"content": "also plain"}},
    ])
    result = normalize(path)
    assert not result.strip().startswith(">")
    os.unlink(path)
