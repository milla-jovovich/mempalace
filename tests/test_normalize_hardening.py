"""Additional hardening tests for transcript normalization."""

import builtins
import json

import pytest

from mempalace.normalize import (
    _chatgpt_mapping_to_messages,
    _format_tool_result,
    _format_tool_use,
    _messages_to_transcript,
    _try_claude_ai_json,
    _try_claude_code_jsonl,
    _try_codex_jsonl,
    normalize,
)


def test_codex_jsonl_ignores_response_items_and_noncanonical_payloads():
    lines = [
        json.dumps({"type": "session_meta", "payload": {"id": "s1"}}),
        json.dumps(
            {
                "type": "response_item",
                "payload": {"type": "assistant_message", "message": "synthetic context"},
            }
        ),
        json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "Q1"}}),
        json.dumps(
            {"type": "event_msg", "payload": {"type": "status_update", "message": "ignore me"}}
        ),
        json.dumps({"type": "event_msg", "payload": {"type": "agent_message", "message": "A1"}}),
        json.dumps(
            {
                "type": "response_item",
                "payload": {"type": "user_message", "message": "duplicate tool context"},
            }
        ),
        json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "Q2"}}),
        json.dumps({"type": "event_msg", "payload": {"type": "agent_message", "message": "A2"}}),
    ]

    result = _try_codex_jsonl("\n".join(lines))

    assert result is not None
    assert "synthetic context" not in result
    assert "duplicate tool context" not in result
    assert "> Q1" in result
    assert "> Q2" in result
    assert "A1" in result
    assert "A2" in result


def test_codex_jsonl_skips_whitespace_and_malformed_noise_without_losing_turns():
    lines = [
        "",
        "not json",
        json.dumps({"type": "session_meta"}),
        json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "  "}}),
        json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "first"}}),
        json.dumps({"type": "event_msg", "payload": []}),
        json.dumps({"type": "event_msg", "payload": {"type": "agent_message", "message": "reply"}}),
        json.dumps({"type": "event_msg", "payload": {"type": "agent_message", "message": ""}}),
    ]

    result = _try_codex_jsonl("\n".join(lines))

    assert result is not None
    assert "> first" in result
    assert "reply" in result
    assert result.count(">") == 1


@pytest.mark.parametrize(
    ("messages", "expected_user_turns"),
    [
        ([("user", "Q"), ("assistant", "A")], 1),
        ([("assistant", "preface"), ("user", "Q1"), ("user", "Q2"), ("assistant", "A")], 2),
        ([("user", "Q1"), ("assistant", "A1"), ("assistant", "A1b"), ("user", "Q2")], 2),
    ],
)
def test_messages_to_transcript_preserves_expected_user_turn_count(messages, expected_user_turns):
    transcript = _messages_to_transcript(messages, spellcheck=False)

    user_turns = [line for line in transcript.splitlines() if line.startswith("> ")]
    assert len(user_turns) == expected_user_turns


def test_messages_to_transcript_preserves_message_order_without_spellcheck():
    messages = [
        ("assistant", "preamble"),
        ("user", "first question"),
        ("assistant", "first answer"),
        ("user", "second question"),
        ("assistant", "second answer"),
    ]

    transcript = _messages_to_transcript(messages, spellcheck=False)

    assert transcript.index("preamble") < transcript.index("> first question")
    assert transcript.index("> first question") < transcript.index("first answer")
    assert transcript.index("first answer") < transcript.index("> second question")
    assert transcript.index("> second question") < transcript.index("second answer")


def test_normalize_surfaces_read_errors_after_size_check(monkeypatch, tmp_path):
    transcript = tmp_path / "chat.json"
    transcript.write_text("{}", encoding="utf-8")

    monkeypatch.setattr("mempalace.normalize.os.path.getsize", lambda _: 10)

    def _boom(*args, **kwargs):
        raise OSError("read failed")

    monkeypatch.setattr("builtins.open", _boom)

    with pytest.raises(IOError, match="Could not read"):
        normalize(str(transcript))


def test_claude_code_jsonl_skips_entries_with_non_dict_message():
    lines = [
        json.dumps({"type": "human", "message": []}),
        json.dumps({"type": "human", "message": {"content": "Question"}}),
        json.dumps({"type": "assistant", "message": {"content": "Answer"}}),
    ]

    result = _try_claude_code_jsonl("\n".join(lines))

    assert result is not None
    assert "> Question" in result


def test_claude_ai_flat_list_skips_non_dict_noise():
    data = [
        "noise",
        {"role": "user", "content": "Explain the rollback hazard."},
        {"role": "assistant", "content": "The migration needs checkpoints."},
    ]

    result = _try_claude_ai_json(data)

    assert result is not None
    assert "> Explain the rollback hazard." in result


def test_chatgpt_mapping_to_messages_rejects_non_dict_mapping():
    assert _chatgpt_mapping_to_messages(["not", "a", "mapping"]) == []


def test_format_tool_use_read_with_non_numeric_range_falls_back():
    block = {
        "type": "tool_use",
        "name": "Read",
        "input": {"file_path": "/tmp/demo.py", "offset": "start", "limit": "rest"},
    }

    assert _format_tool_use(block) == "[Read /tmp/demo.py:start+rest]"


def test_format_tool_result_accepts_string_items_inside_content_list():
    result = _format_tool_result(
        [{"type": "text", "text": "line 1"}, "line 2"],
        "Bash",
    )

    assert "→ line 1" in result
    assert "→ line 2" in result


def test_messages_to_transcript_handles_missing_spellcheck_module(monkeypatch):
    real_import = builtins.__import__

    def _guarded_import(name, *args, **kwargs):
        if name == "mempalace.spellcheck":
            raise ImportError("spellcheck extras not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)

    transcript = _messages_to_transcript([("user", "Question"), ("assistant", "Answer")])

    assert "> Question" in transcript
    assert "Answer" in transcript
