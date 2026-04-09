import json
from unittest.mock import patch

from mempalace.normalize import (
    _extract_content,
    _messages_to_transcript,
    _try_chatgpt_json,
    _try_claude_ai_json,
    _try_claude_code_jsonl,
    _try_codex_jsonl,
    _try_normalize_json,
    _try_slack_json,
    normalize,
)


# ── normalize() top-level ──────────────────────────────────────────────


def test_plain_text(tmp_path):
    f = tmp_path / "plain.txt"
    f.write_text("Hello world\nSecond line\n")
    result = normalize(str(f))
    assert "Hello world" in result


def test_claude_json(tmp_path):
    data = [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}]
    f = tmp_path / "claude.json"
    f.write_text(json.dumps(data))
    result = normalize(str(f))
    assert "Hi" in result


def test_empty(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("")
    result = normalize(str(f))
    assert result.strip() == ""


def test_normalize_io_error():
    """normalize raises IOError for unreadable file."""
    try:
        normalize("/nonexistent/path/file.txt")
        assert False, "Should have raised"
    except IOError as e:
        assert "Could not read" in str(e)


def test_normalize_already_has_markers(tmp_path):
    """Files with >= 3 '>' lines pass through unchanged."""
    content = "> question 1\nanswer 1\n> question 2\nanswer 2\n> question 3\nanswer 3\n"
    f = tmp_path / "markers.txt"
    f.write_text(content)
    result = normalize(str(f))
    assert result == content


def test_normalize_json_content_detected_by_brace(tmp_path):
    """A .txt file starting with [ triggers JSON parsing."""
    data = [{"role": "user", "content": "Hey"}, {"role": "assistant", "content": "Hi there"}]
    f = tmp_path / "chat.txt"
    f.write_text(json.dumps(data))
    result = normalize(str(f))
    assert "Hey" in result


def test_normalize_whitespace_only(tmp_path):
    f = tmp_path / "ws.txt"
    f.write_text("   \n  \n  ")
    result = normalize(str(f))
    assert result.strip() == ""


# ── _extract_content ───────────────────────────────────────────────────


def test_extract_content_string():
    assert _extract_content("hello") == "hello"


def test_extract_content_list_of_strings():
    assert _extract_content(["hello", "world"]) == "hello world"


def test_extract_content_list_of_blocks():
    blocks = [{"type": "text", "text": "hello"}, {"type": "image", "url": "x"}]
    assert _extract_content(blocks) == "hello"


def test_extract_content_dict():
    assert _extract_content({"text": "hello"}) == "hello"


def test_extract_content_none():
    assert _extract_content(None) == ""


def test_extract_content_mixed_list():
    blocks = ["plain", {"type": "text", "text": "block"}]
    assert _extract_content(blocks) == "plain block"


# ── _try_claude_code_jsonl ─────────────────────────────────────────────


def test_claude_code_jsonl_valid():
    lines = [
        json.dumps({"type": "human", "message": {"content": "What is X?"}}),
        json.dumps({"type": "assistant", "message": {"content": "X is Y."}}),
    ]
    result = _try_claude_code_jsonl("\n".join(lines))
    assert result is not None
    assert "> What is X?" in result
    assert "X is Y." in result


def test_claude_code_jsonl_user_type():
    lines = [
        json.dumps({"type": "user", "message": {"content": "Q"}}),
        json.dumps({"type": "assistant", "message": {"content": "A"}}),
    ]
    result = _try_claude_code_jsonl("\n".join(lines))
    assert result is not None
    assert "> Q" in result


def test_claude_code_jsonl_too_few_messages():
    lines = [json.dumps({"type": "human", "message": {"content": "only one"}})]
    result = _try_claude_code_jsonl("\n".join(lines))
    assert result is None


def test_claude_code_jsonl_invalid_json_lines():
    lines = [
        "not json",
        json.dumps({"type": "human", "message": {"content": "Q"}}),
        json.dumps({"type": "assistant", "message": {"content": "A"}}),
    ]
    result = _try_claude_code_jsonl("\n".join(lines))
    assert result is not None


def test_claude_code_jsonl_non_dict_entries():
    lines = [
        json.dumps([1, 2, 3]),
        json.dumps({"type": "human", "message": {"content": "Q"}}),
        json.dumps({"type": "assistant", "message": {"content": "A"}}),
    ]
    result = _try_claude_code_jsonl("\n".join(lines))
    assert result is not None


# ── _try_codex_jsonl ───────────────────────────────────────────────────


def test_codex_jsonl_valid():
    lines = [
        json.dumps({"type": "session_meta", "payload": {}}),
        json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "Q"}}),
        json.dumps({"type": "event_msg", "payload": {"type": "agent_message", "message": "A"}}),
    ]
    result = _try_codex_jsonl("\n".join(lines))
    assert result is not None
    assert "> Q" in result


def test_codex_jsonl_no_session_meta():
    """Without session_meta, codex parser returns None."""
    lines = [
        json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "Q"}}),
        json.dumps({"type": "event_msg", "payload": {"type": "agent_message", "message": "A"}}),
    ]
    result = _try_codex_jsonl("\n".join(lines))
    assert result is None


def test_codex_jsonl_skips_non_event_msg():
    lines = [
        json.dumps({"type": "session_meta"}),
        json.dumps({"type": "response_item", "payload": {"type": "user_message", "message": "X"}}),
        json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "Q"}}),
        json.dumps({"type": "event_msg", "payload": {"type": "agent_message", "message": "A"}}),
    ]
    result = _try_codex_jsonl("\n".join(lines))
    assert result is not None
    assert "X" not in result.split("> Q")[0]


def test_codex_jsonl_non_string_message():
    lines = [
        json.dumps({"type": "session_meta"}),
        json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": 123}}),
        json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "Q"}}),
        json.dumps({"type": "event_msg", "payload": {"type": "agent_message", "message": "A"}}),
    ]
    result = _try_codex_jsonl("\n".join(lines))
    assert result is not None


def test_codex_jsonl_empty_text_skipped():
    lines = [
        json.dumps({"type": "session_meta"}),
        json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "  "}}),
        json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "Q"}}),
        json.dumps({"type": "event_msg", "payload": {"type": "agent_message", "message": "A"}}),
    ]
    result = _try_codex_jsonl("\n".join(lines))
    assert result is not None


def test_codex_jsonl_payload_not_dict():
    lines = [
        json.dumps({"type": "session_meta"}),
        json.dumps({"type": "event_msg", "payload": "not a dict"}),
        json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "Q"}}),
        json.dumps({"type": "event_msg", "payload": {"type": "agent_message", "message": "A"}}),
    ]
    result = _try_codex_jsonl("\n".join(lines))
    assert result is not None


# ── _try_claude_ai_json ───────────────────────────────────────────────


def test_claude_ai_flat_messages():
    data = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
    ]
    result = _try_claude_ai_json(data)
    assert result is not None
    assert "> Hello" in result


def test_claude_ai_dict_with_messages_key():
    data = {
        "messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
    }
    result = _try_claude_ai_json(data)
    assert result is not None


def test_claude_ai_privacy_export():
    data = [
        {
            "chat_messages": [
                {"role": "human", "content": "Q1"},
                {"role": "ai", "content": "A1"},
            ]
        }
    ]
    result = _try_claude_ai_json(data)
    assert result is not None
    assert "> Q1" in result


def test_claude_ai_not_a_list():
    result = _try_claude_ai_json("not a list")
    assert result is None


def test_claude_ai_too_few_messages():
    data = [{"role": "user", "content": "Hello"}]
    result = _try_claude_ai_json(data)
    assert result is None


def test_claude_ai_dict_with_chat_messages_key():
    data = {
        "chat_messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "World"},
        ]
    }
    result = _try_claude_ai_json(data)
    assert result is not None


def test_claude_ai_privacy_export_non_dict_items():
    """Non-dict items in privacy export are skipped."""
    data = [
        {
            "chat_messages": [
                "not a dict",
                {"role": "user", "content": "Q"},
                {"role": "assistant", "content": "A"},
            ]
        },
        "not a convo",
    ]
    result = _try_claude_ai_json(data)
    assert result is not None


# ── _try_chatgpt_json ─────────────────────────────────────────────────


def test_chatgpt_json_valid():
    data = {
        "mapping": {
            "root": {
                "parent": None,
                "message": None,
                "children": ["msg1"],
            },
            "msg1": {
                "parent": "root",
                "message": {
                    "author": {"role": "user"},
                    "content": {"parts": ["Hello ChatGPT"]},
                },
                "children": ["msg2"],
            },
            "msg2": {
                "parent": "msg1",
                "message": {
                    "author": {"role": "assistant"},
                    "content": {"parts": ["Hello! How can I help?"]},
                },
                "children": [],
            },
        }
    }
    result = _try_chatgpt_json(data)
    assert result is not None
    assert "> Hello ChatGPT" in result


def test_chatgpt_json_no_mapping():
    result = _try_chatgpt_json({"data": []})
    assert result is None


def test_chatgpt_json_not_dict():
    result = _try_chatgpt_json([1, 2, 3])
    assert result is None


def test_chatgpt_json_fallback_root():
    """Root node has a message (no synthetic root), uses fallback."""
    data = {
        "mapping": {
            "root": {
                "parent": None,
                "message": {
                    "author": {"role": "system"},
                    "content": {"parts": ["system prompt"]},
                },
                "children": ["msg1"],
            },
            "msg1": {
                "parent": "root",
                "message": {
                    "author": {"role": "user"},
                    "content": {"parts": ["Hello"]},
                },
                "children": ["msg2"],
            },
            "msg2": {
                "parent": "msg1",
                "message": {
                    "author": {"role": "assistant"},
                    "content": {"parts": ["Hi there"]},
                },
                "children": [],
            },
        }
    }
    result = _try_chatgpt_json(data)
    assert result is not None


def test_chatgpt_json_too_few_messages():
    data = {
        "mapping": {
            "root": {
                "parent": None,
                "message": None,
                "children": ["msg1"],
            },
            "msg1": {
                "parent": "root",
                "message": {
                    "author": {"role": "user"},
                    "content": {"parts": ["Only one"]},
                },
                "children": [],
            },
        }
    }
    result = _try_chatgpt_json(data)
    assert result is None


# ── _try_slack_json ────────────────────────────────────────────────────


def test_slack_json_valid():
    data = [
        {"type": "message", "user": "U1", "text": "Hello"},
        {"type": "message", "user": "U2", "text": "Hi there"},
    ]
    result = _try_slack_json(data)
    assert result is not None
    assert "Hello" in result


def test_slack_json_not_a_list():
    result = _try_slack_json({"type": "message"})
    assert result is None


def test_slack_json_too_few_messages():
    data = [{"type": "message", "user": "U1", "text": "Hello"}]
    result = _try_slack_json(data)
    assert result is None


def test_slack_json_skips_non_message_types():
    data = [
        {"type": "channel_join", "user": "U1", "text": "joined"},
        {"type": "message", "user": "U1", "text": "Hello"},
        {"type": "message", "user": "U2", "text": "Hi"},
    ]
    result = _try_slack_json(data)
    assert result is not None


def test_slack_json_three_users():
    """Three speakers get alternating roles."""
    data = [
        {"type": "message", "user": "U1", "text": "Hello"},
        {"type": "message", "user": "U2", "text": "Hi"},
        {"type": "message", "user": "U3", "text": "Hey"},
    ]
    result = _try_slack_json(data)
    assert result is not None


def test_slack_json_empty_text_skipped():
    data = [
        {"type": "message", "user": "U1", "text": ""},
        {"type": "message", "user": "U1", "text": "Hello"},
        {"type": "message", "user": "U2", "text": "Hi"},
    ]
    result = _try_slack_json(data)
    assert result is not None


def test_slack_json_username_fallback():
    data = [
        {"type": "message", "username": "bot1", "text": "Hello"},
        {"type": "message", "username": "bot2", "text": "Hi"},
    ]
    result = _try_slack_json(data)
    assert result is not None


# ── _try_normalize_json ────────────────────────────────────────────────


def test_try_normalize_json_invalid_json():
    result = _try_normalize_json("not json at all {{{")
    assert result is None


def test_try_normalize_json_valid_but_unknown_schema():
    result = _try_normalize_json(json.dumps({"random": "data"}))
    assert result is None


# ── _messages_to_transcript ────────────────────────────────────────────


def test_messages_to_transcript_basic():
    msgs = [("user", "Q"), ("assistant", "A")]
    with patch("mempalace.normalize.spellcheck_user_text", side_effect=lambda x: x, create=True):
        result = _messages_to_transcript(msgs, spellcheck=False)
    assert "> Q" in result
    assert "A" in result


def test_messages_to_transcript_consecutive_users():
    """Two user messages in a row (no assistant between)."""
    msgs = [("user", "Q1"), ("user", "Q2"), ("assistant", "A")]
    result = _messages_to_transcript(msgs, spellcheck=False)
    assert "> Q1" in result
    assert "> Q2" in result


def test_messages_to_transcript_assistant_first():
    """Leading assistant message (no user before it)."""
    msgs = [("assistant", "preamble"), ("user", "Q"), ("assistant", "A")]
    result = _messages_to_transcript(msgs, spellcheck=False)
    assert "preamble" in result
    assert "> Q" in result
