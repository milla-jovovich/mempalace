"""
test_normalize.py — Tests for normalize.py streaming functionality

Tests cover:
- Unit tests: individual function behavior
- Integration tests: full normalization workflows  
- Error tests: malformed input, edge cases
- Regression tests: ensure existing formats still work
"""

import json
from pathlib import Path

from mempalace import normalize as norm


# ── Unit tests: format detection ─────────────────────────────────────────


def test_normalize_already_has_markers():
    """Files with > markers pass through unchanged."""
    content = "> Hello\nResponse\n> Another prompt"
    # Create temp file
    path = Path("/tmp/test_markers.txt")
    path.write_text(content)
    
    result = norm.normalize(str(path))
    assert result == content
    
    path.unlink()


def test_normalize_empty_file(tmp_path):
    """Empty files return empty string."""
    path = tmp_path / "empty.txt"
    path.write_text("")
    
    result = norm.normalize(str(path))
    assert result == ""


def test_normalize_file_too_large(tmp_path):
    """Files over 500MB raise IOError."""
    import pytest
    import os
    
    path = tmp_path / "huge.txt"
    # Write a small file but mock its size
    path.write_text("small content")
    
    # Mock the size check by temporarily modifying the file stat
    original_getsize = os.path.getsize
    
    def mock_getsize(p):
        if str(p) == str(path):
            return 600 * 1024 * 1024  # 600MB
        return original_getsize(p)
    
    import mempalace.normalize
    mempalace.normalize.os.path.getsize = mock_getsize
    
    try:
        with pytest.raises(IOError) as exc_info:
            norm.normalize(str(path))
        assert "too large" in str(exc_info.value)
    finally:
        mempalace.normalize.os.path.getsize = original_getsize


# ── Unit tests: Claude Code JSONL streaming ─────────────────────────────


def test_claude_code_jsonl_streaming_basic(tmp_path):
    """Test streaming Claude Code JSONL normalization."""
    path = tmp_path / "claude.jsonl"
    
    lines = [
        json.dumps({"type": "human", "message": {"content": "Hello"}}),
        json.dumps({"type": "assistant", "message": {"content": "Hi there"}}),
        json.dumps({"type": "human", "message": {"content": "How are you?"}}),
        json.dumps({"type": "assistant", "message": {"content": "I'm fine"}}),
    ]
    path.write_text("\n".join(lines))
    
    result = norm.normalize(str(path))
    
    assert "> Hello" in result
    assert "> How are you?" in result
    assert "Hi there" in result
    assert "I'm fine" in result


def test_claude_code_jsonl_streaming_empty_messages(tmp_path):
    """Test JSONL with empty messages is handled."""
    path = tmp_path / "claude_empty.jsonl"
    
    lines = [
        json.dumps({"type": "human", "message": {"content": ""}}),
        json.dumps({"type": "assistant", "message": {"content": "Response"}}),
        json.dumps({"type": "human", "message": {"content": "Real message"}}),
    ]
    path.write_text("\n".join(lines))
    
    result = norm.normalize(str(path))
    
    # Empty message should be skipped
    assert result.count(">") == 1
    assert "> Real message" in result


def test_claude_code_jsonl_streaming_malformed_lines(tmp_path):
    """Test JSONL with malformed lines is handled gracefully."""
    path = tmp_path / "claude_bad.jsonl"
    
    lines = [
        json.dumps({"type": "human", "message": {"content": "First"}}),
        "not valid json {{[",
        json.dumps({"type": "assistant", "message": {"content": "Second"}}),
        "",
        json.dumps({"type": "human", "message": {"content": "Third"}}),
    ]
    path.write_text("\n".join(lines))
    
    result = norm.normalize(str(path))
    
    assert "> First" in result
    assert "> Third" in result
    assert "Second" in result


# ── Unit tests: Codex JSONL streaming ───────────────────────────────────


def test_codex_jsonl_streaming_basic(tmp_path):
    """Test streaming Codex JSONL normalization."""
    path = tmp_path / "codex.jsonl"
    
    lines = [
        json.dumps({"type": "session_meta", "id": "test"}),
        json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "Hello"}}),
        json.dumps({"type": "event_msg", "payload": {"type": "agent_message", "message": "Hi"}}),
        json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "Question"}}),
        json.dumps({"type": "event_msg", "payload": {"type": "agent_message", "message": "Answer"}}),
    ]
    path.write_text("\n".join(lines))
    
    result = norm.normalize(str(path))
    
    assert "> Hello" in result
    assert "> Question" in result
    assert "Hi" in result
    assert "Answer" in result


def test_codex_jsonl_streaming_skips_response_items(tmp_path):
    """Test that response_item entries are correctly skipped."""
    path = tmp_path / "codex_skip.jsonl"
    
    lines = [
        json.dumps({"type": "session_meta", "id": "test"}),
        json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "User text"}}),
        json.dumps({"type": "response_item", "payload": {"type": "agent_message", "message": "Duplicate"}}),
        json.dumps({"type": "event_msg", "payload": {"type": "agent_message", "message": "Real response"}}),
    ]
    path.write_text("\n".join(lines))
    
    result = norm.normalize(str(path))
    
    # Should only have one agent message (the real one)
    lines_result = result.strip().split("\n")
    agent_responses = [l for l in lines_result if not l.startswith(">") and l.strip()]
    assert len(agent_responses) == 1
    assert "Real response" in result
    assert "Duplicate" not in result


def test_codex_jsonl_streaming_no_session_meta(tmp_path):
    """Test Codex JSONL without session_meta is rejected."""
    path = tmp_path / "codex_nosession.jsonl"
    
    lines = [
        json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "Hello"}}),
        json.dumps({"type": "event_msg", "payload": {"type": "agent_message", "message": "Hi"}}),
    ]
    path.write_text("\n".join(lines))
    
    result = norm.normalize(str(path))
    
    # Without session_meta, should pass through as plain text
    assert "> Hello" not in result


# ── Integration tests: full workflows ────────────────────────────────────


def test_normalize_jsonl_passes_through_plain_text(tmp_path):
    """Plain text files pass through."""
    path = tmp_path / "plain.txt"
    content = "This is just plain text\nWith multiple lines\nNo markers here"
    path.write_text(content)
    
    result = norm.normalize(str(path))
    assert result == content


def test_normalize_jsonl_handles_large_streaming(tmp_path):
    """Test that large JSONL files are processed via streaming without OOM."""
    path = tmp_path / "large.jsonl"
    
    # Create a larger JSONL file (but not actually huge for test speed)
    lines = []
    for i in range(100):
        lines.append(json.dumps({"type": "human", "message": {"content": f"Message {i}"}}))
        lines.append(json.dumps({"type": "assistant", "message": {"content": f"Response {i}"}}))
    
    path.write_text("\n".join(lines))
    
    result = norm.normalize(str(path))
    
    # Verify all messages present
    for i in range(100):
        assert f"> Message {i}" in result
        assert f"Response {i}" in result


# ── Regression tests: ensure existing JSON still works ────────────────────


def test_claude_ai_json_still_works(tmp_path):
    """Ensure Claude.ai JSON export format still works."""
    path = tmp_path / "claude_ai.json"
    
    data = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi"},
        {"role": "user", "content": "How are you?"},
    ]
    path.write_text(json.dumps(data))
    
    result = norm.normalize(str(path))
    
    assert "> Hello" in result
    assert "> How are you?" in result


def test_chatgpt_json_still_works(tmp_path):
    """Ensure ChatGPT conversations.json still works."""
    path = tmp_path / "chatgpt.json"
    
    data = {
        "mapping": {
            "root": {"parent": None, "message": None, "children": ["child1"]},
            "child1": {
                "parent": "root",
                "message": {"author": {"role": "user"}, "content": {"parts": ["Hello"]}},
                "children": ["child2"]
            },
            "child2": {
                "parent": "child1",
                "message": {"author": {"role": "assistant"}, "content": {"parts": ["Hi there"]}},
                "children": []
            }
        }
    }
    path.write_text(json.dumps(data))
    
    result = norm.normalize(str(path))
    
    assert "> Hello" in result
    assert "Hi there" in result


def test_slack_json_still_works(tmp_path):
    """Ensure Slack export still works."""
    path = tmp_path / "slack.json"
    
    data = [
        {"type": "message", "user": "U123", "text": "Hello"},
        {"type": "message", "user": "U456", "text": "Hi"},
        {"type": "message", "user": "U123", "text": "How are you?"},
    ]
    path.write_text(json.dumps(data))
    
    result = norm.normalize(str(path))
    
    # Should have user and assistant alternating
    assert "Hello" in result
    assert "Hi" in result


# ── Error handling tests ────────────────────────────────────────────────


def test_normalize_missing_file(tmp_path):
    """Test handling of non-existent file."""
    path = tmp_path / "nonexistent.jsonl"
    
    try:
        norm.normalize(str(path))
        assert False, "Should have raised IOError"
    except IOError as e:
        assert "Could not read" in str(e)


def test_normalize_malformed_json(tmp_path):
    """Test handling of malformed JSON."""
    path = tmp_path / "bad.json"
    path.write_text("not json {{{")
    
    # Should pass through as plain text
    result = norm.normalize(str(path))
    assert result == "not json {{{"


def test_normalize_truncated_jsonl(tmp_path):
    """Test handling of truncated/incomplete JSONL - passes through as plain text."""
    path = tmp_path / "truncated.jsonl"
    
    lines = [
        json.dumps({"type": "human", "message": {"content": "Complete"}}),
        '{"type": "assistant", "message": {"content": "Incomple',  # Truncated
    ]
    path.write_text("\n".join(lines))
    
    result = norm.normalize(str(path))
    
    # With only 1 valid message (truncated second line), can't normalize
    # Falls through as plain text since not enough valid messages
    assert "Complete" in result  # Raw content preserved


# ── Helper extraction tests ─────────────────────────────────────────────


def test_extract_content_string():
    """Test _extract_content with string input."""
    assert norm._extract_content("Hello") == "Hello"


def test_extract_content_list():
    """Test _extract_content with list input."""
    content = ["Hello ", {"type": "text", "text": "world"}]
    # Note: function joins with space, so "Hello " + " " + "world" = "Hello  world"
    assert norm._extract_content(content) == "Hello  world"


def test_extract_content_dict():
    """Test _extract_content with dict input."""
    content = {"text": "Hello world"}
    assert norm._extract_content(content) == "Hello world"


def test_extract_content_unknown():
    """Test _extract_content with unknown type."""
    assert norm._extract_content(12345) == ""


# ── Messages to transcript tests ────────────────────────────────────────


def test_messages_to_transcript_basic():
    """Test basic message conversion."""
    messages = [
        ("user", "Hello"),
        ("assistant", "Hi there"),
        ("user", "How are you?"),
    ]
    
    result = norm._messages_to_transcript(messages, spellcheck=False)
    
    assert "> Hello" in result
    assert "> How are you?" in result
    assert "Hi there" in result


def test_messages_to_transcript_unpaired_assistant():
    """Test handling of assistant message without preceding user."""
    messages = [
        ("assistant", "Hi"),
        ("user", "Hello"),
        ("assistant", "Response"),
    ]
    
    result = norm._messages_to_transcript(messages, spellcheck=False)
    
    assert "Hi" in result  # Unpaired assistant message included
    assert "> Hello" in result


def test_messages_to_transcript_empty():
    """Test handling of empty messages list."""
    result = norm._messages_to_transcript([], spellcheck=False)
    assert result == ""
