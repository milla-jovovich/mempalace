import json
import tempfile
from mempalace.normalize import normalize, _try_copilot_cli_jsonl, _try_factory_jsonl
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
    os.unlink(f.name)


def _make_copilot_jsonl(events: list) -> str:
    """Helper: build a Copilot CLI events.jsonl string."""
    return "\n".join(json.dumps(e) for e in events)


def test_copilot_cli_basic():
    """Happy path: session.start + user.message + assistant.message."""
    raw = _make_copilot_jsonl([
        {"type": "session.start", "data": {"sessionId": "abc", "version": 1, "producer": "copilot-agent"}},
        {"type": "user.message", "data": {"content": "Implement AIM-P009", "transformedContent": "<injected>"}},
        {"type": "assistant.message", "data": {"content": "Phase 0 complete. All artifacts validated.", "messageId": "x"}},
    ])
    result = _try_copilot_cli_jsonl(raw)
    assert result is not None
    assert "Implement AIM-P009" in result
    assert "Phase 0 complete" in result
    # transformedContent must not leak into the transcript
    assert "<injected>" not in result


def test_copilot_cli_filters_short_assistant_messages():
    """Assistant messages under 30 chars are noise — skip them."""
    raw = _make_copilot_jsonl([
        {"type": "session.start", "data": {"sessionId": "abc", "version": 1, "producer": "copilot-agent"}},
        {"type": "user.message", "data": {"content": "Run the pipeline"}},
        {"type": "assistant.message", "data": {"content": "ok"}},
        {"type": "assistant.message", "data": {"content": "Phase 1 reviewers running in parallel. Waiting for results."}},
    ])
    result = _try_copilot_cli_jsonl(raw)
    assert result is not None
    assert "ok" not in result
    assert "Phase 1 reviewers running" in result


def test_copilot_cli_filters_pure_system_notifications():
    """Short system_notification wrappers should be dropped."""
    raw = _make_copilot_jsonl([
        {"type": "session.start", "data": {"sessionId": "abc", "version": 1, "producer": "copilot-agent"}},
        {"type": "user.message", "data": {"content": "Check status"}},
        {"type": "assistant.message", "data": {"content": "<system_notification>Agent done.</system_notification>"}},
        {"type": "assistant.message", "data": {"content": "Both reviewers approved. Phase 1 passed — moving to architecture."}},
    ])
    result = _try_copilot_cli_jsonl(raw)
    assert result is not None
    assert "<system_notification>" not in result
    assert "Phase 1 passed" in result


def test_copilot_cli_requires_session_start():
    """Without session.start fingerprint, should not match."""
    raw = _make_copilot_jsonl([
        {"type": "user.message", "data": {"content": "Hello"}},
        {"type": "assistant.message", "data": {"content": "Hi there, ready to help with anything you need."}},
    ])
    result = _try_copilot_cli_jsonl(raw)
    assert result is None


def test_copilot_cli_requires_two_messages():
    """Single message is not enough to form a transcript."""
    raw = _make_copilot_jsonl([
        {"type": "session.start", "data": {"sessionId": "abc", "version": 1, "producer": "copilot-agent"}},
        {"type": "user.message", "data": {"content": "Just one message"}},
    ])
    result = _try_copilot_cli_jsonl(raw)
    assert result is None


def test_copilot_cli_via_normalize_file():
    """End-to-end: normalize() dispatches to Copilot normalizer for .jsonl files."""
    events = [
        {"type": "session.start", "data": {"sessionId": "test-session", "version": 1, "producer": "copilot-agent"}},
        {"type": "user.message", "data": {"content": "Implement petition P-001"}},
        {"type": "tool.execution_start", "data": {"toolName": "read_file"}},
        {"type": "tool.execution_complete", "data": {"toolName": "read_file"}},
        {"type": "assistant.message", "data": {"content": "Read P-001.md successfully. Starting phase review now."}},
        {"type": "subagent.started", "data": {"agentName": "petition-translator-reviewer"}},
        {"type": "assistant.message", "data": {"content": "Petition translator reviewer approved with 0 blocking issues."}},
        {"type": "session.shutdown", "data": {"shutdownType": "routine"}},
    ]
    raw = "\n".join(json.dumps(e) for e in events)
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    f.write(raw)
    f.close()
    result = normalize(f.name)
    os.unlink(f.name)
    assert "Implement petition P-001" in result
    assert "Starting phase review now" in result
    assert "approved with 0 blocking issues" in result
    # Non-message events must not appear
    assert "tool.execution_start" not in result
    assert "subagent.started" not in result


# ---------------------------------------------------------------------------
# Factory.ai / Droid normalizer tests
# ---------------------------------------------------------------------------

def _make_factory_jsonl(events: list) -> str:
    """Helper: build a Factory.ai session JSONL string."""
    return "\n".join(json.dumps(e) for e in events)


def _factory_msg(role: str, texts: list, msg_id: str = "id1", parent: str = None) -> dict:
    """Build a Factory.ai message event with content blocks."""
    content = [{"type": "text", "text": t} for t in texts]
    event = {
        "type": "message",
        "id": msg_id,
        "timestamp": "2025-11-18T12:00:00.000Z",
        "message": {"role": role, "content": content},
    }
    if parent:
        event["parentId"] = parent
    return event


def test_factory_basic():
    """Happy path: session_start + user message + assistant message."""
    raw = _make_factory_jsonl([
        {"type": "session_start", "id": "abc", "title": "test session", "owner": "user", "version": 2},
        _factory_msg("user", ["How do I implement the debt service?"]),
        _factory_msg("assistant", ["To implement the debt service, start by creating the Spring Boot application."]),
    ])
    result = _try_factory_jsonl(raw)
    assert result is not None
    assert "How do I implement the debt service?" in result
    assert "start by creating the Spring Boot application" in result


def test_factory_filters_system_reminder():
    """<system-reminder> injections in user content must be excluded."""
    raw = _make_factory_jsonl([
        {"type": "session_start", "id": "abc", "title": "t", "owner": "u", "version": 2},
        _factory_msg("user", [
            "<system-reminder>\nImportant: Never call a file editing tool in parallel.\n</system-reminder>",
            "Add a new endpoint to the creditor service.",
        ]),
        _factory_msg("assistant", ["I will add the endpoint to the creditor service controller now."]),
    ])
    result = _try_factory_jsonl(raw)
    assert result is not None
    assert "<system-reminder>" not in result
    assert "Add a new endpoint" in result


def test_factory_filters_tool_use_blocks():
    """Assistant tool_use blocks must not appear in the transcript."""
    raw = _make_factory_jsonl([
        {"type": "session_start", "id": "abc", "title": "t", "owner": "u", "version": 2},
        _factory_msg("user", ["Search for usages of DebtService."]),
        {
            "type": "message",
            "id": "asst1",
            "timestamp": "2025-11-18T12:00:01.000Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "tu1", "name": "Grep", "input": {"pattern": "DebtService"}},
                    {"type": "text", "text": "Found 12 usages of DebtService across 5 files."},
                ],
            },
        },
    ])
    result = _try_factory_jsonl(raw)
    assert result is not None
    assert "Found 12 usages" in result
    assert "tool_use" not in result
    assert "Grep" not in result


def test_factory_filters_thinking_blocks():
    """Extended thinking blocks must not appear in the transcript."""
    raw = _make_factory_jsonl([
        {"type": "session_start", "id": "abc", "title": "t", "owner": "u", "version": 2},
        _factory_msg("user", ["Does Droid support agents?"]),
        {
            "type": "message",
            "id": "asst2",
            "timestamp": "2025-11-18T12:00:02.000Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "signature": "sig==", "thinking": "The user asks about agent support."},
                    {"type": "text", "text": "Yes, Factory.ai supports droids which act as autonomous agents."},
                ],
            },
        },
    ])
    result = _try_factory_jsonl(raw)
    assert result is not None
    assert "Yes, Factory.ai supports droids" in result
    assert "thinking" not in result
    assert "The user asks about agent support" not in result


def test_factory_requires_session_start():
    """Without session_start fingerprint, must not match."""
    raw = _make_factory_jsonl([
        _factory_msg("user", ["Hello"]),
        _factory_msg("assistant", ["Hello! I am ready to help you with your coding tasks today."]),
    ])
    result = _try_factory_jsonl(raw)
    assert result is None


def test_factory_requires_two_messages():
    """Single message is not enough to form a transcript."""
    raw = _make_factory_jsonl([
        {"type": "session_start", "id": "abc", "title": "t", "owner": "u", "version": 2},
        _factory_msg("user", ["Just one message here"]),
    ])
    result = _try_factory_jsonl(raw)
    assert result is None


def test_factory_via_normalize_file():
    """End-to-end: normalize() dispatches to Factory normalizer for .jsonl files."""
    events = [
        {"type": "session_start", "id": "s1", "title": "opendebt session", "owner": "u", "version": 2},
        _factory_msg("user", [
            "<system-reminder>Do not call editing tools in parallel.</system-reminder>",
            "Implement the payment reconciliation endpoint.",
        ], msg_id="u1"),
        {
            "type": "message", "id": "a1",
            "timestamp": "2025-11-18T12:00:01.000Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "tu1", "name": "ReadFile", "input": {}},
                    {"type": "text", "text": "I have read the service file. Adding the reconciliation endpoint now."},
                ],
            },
            "parentId": "u1",
        },
    ]
    raw = "\n".join(json.dumps(e) for e in events)
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    f.write(raw)
    f.close()
    result = normalize(f.name)
    os.unlink(f.name)
    assert "Implement the payment reconciliation endpoint" in result
    assert "I have read the service file" in result
    assert "<system-reminder>" not in result
    assert "ReadFile" not in result


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


def test_normalize_rejects_large_file():
    """Files over 500 MB should raise IOError before reading."""
    with patch("mempalace.normalize.os.path.getsize", return_value=600 * 1024 * 1024):
        try:
            normalize("/fake/huge_file.txt")
            assert False, "Should have raised IOError"
        except IOError as e:
            assert "too large" in str(e).lower()
