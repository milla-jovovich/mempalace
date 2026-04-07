"""Tests for mempalace.normalize — format detection and conversion."""

import json

import pytest

from mempalace.normalize import (
    _extract_content,
    _messages_to_transcript,
    _try_chatgpt_json,
    _try_claude_ai_json,
    _try_claude_code_jsonl,
    _try_slack_json,
    normalize,
)


class TestNormalizePlainText:
    def test_plain_text_passthrough(self, tmp_path):
        f = tmp_path / "plain.txt"
        f.write_text("Hello world\nSecond line\n")
        assert "Hello world" in normalize(str(f))

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        assert normalize(str(f)).strip() == ""

    def test_whitespace_only(self, tmp_path):
        f = tmp_path / "ws.txt"
        f.write_text("   \n  \n  ")
        assert normalize(str(f)).strip() == ""

    def test_already_has_markers_passthrough(self, tmp_path):
        content = "> Question one\nAnswer one\n\n> Question two\nAnswer two\n\n> Question three\nAnswer three\n"
        f = tmp_path / "marked.txt"
        f.write_text(content)
        assert normalize(str(f)) == content


class TestClaudeAiJson:
    def test_simple_messages(self):
        data = [
            {"role": "user", "content": "Hi there"},
            {"role": "assistant", "content": "Hello!"},
        ]
        result = _try_claude_ai_json(data)
        assert "> Hi there" in result
        assert "Hello!" in result

    def test_nested_under_messages_key(self):
        data = {
            "messages": [
                {"role": "user", "content": "What is AI?"},
                {"role": "assistant", "content": "Artificial Intelligence."},
            ]
        }
        result = _try_claude_ai_json(data)
        assert "> What is AI?" in result

    def test_human_and_ai_roles(self):
        data = [
            {"role": "human", "content": "Hello"},
            {"role": "ai", "content": "Hi"},
        ]
        result = _try_claude_ai_json(data)
        assert "> Hello" in result

    def test_too_few_messages(self):
        data = [{"role": "user", "content": "Solo"}]
        assert _try_claude_ai_json(data) is None

    def test_not_a_list(self):
        assert _try_claude_ai_json("string") is None


class TestClaudeCodeJsonl:
    def test_jsonl_sessions(self):
        lines = [
            json.dumps({"type": "human", "message": {"content": "Fix the bug"}}),
            json.dumps({"type": "assistant", "message": {"content": "I'll fix it now"}}),
        ]
        result = _try_claude_code_jsonl("\n".join(lines))
        assert "> Fix the bug" in result
        assert "I'll fix it now" in result

    def test_content_as_list_blocks(self):
        lines = [
            json.dumps({"type": "human", "message": {"content": [{"type": "text", "text": "Do X"}]}}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Done"}]}}),
        ]
        result = _try_claude_code_jsonl("\n".join(lines))
        assert "> Do X" in result

    def test_invalid_jsonl(self):
        assert _try_claude_code_jsonl("not json\nalso not") is None


class TestChatGptJson:
    def test_mapping_tree(self):
        data = {
            "mapping": {
                "root": {
                    "parent": None,
                    "message": None,
                    "children": ["n1"],
                },
                "n1": {
                    "parent": "root",
                    "message": {"author": {"role": "user"}, "content": {"parts": ["Hello ChatGPT"]}},
                    "children": ["n2"],
                },
                "n2": {
                    "parent": "n1",
                    "message": {"author": {"role": "assistant"}, "content": {"parts": ["Hi there!"]}},
                    "children": [],
                },
            }
        }
        result = _try_chatgpt_json(data)
        assert "> Hello ChatGPT" in result
        assert "Hi there!" in result

    def test_no_mapping_key(self):
        assert _try_chatgpt_json({"title": "Chat"}) is None

    def test_non_dict_input(self):
        assert _try_chatgpt_json([1, 2, 3]) is None


class TestSlackJson:
    def test_two_person_dm(self):
        data = [
            {"type": "message", "user": "U001", "text": "Hey, how's the deploy?"},
            {"type": "message", "user": "U002", "text": "All green, shipped 5 min ago."},
            {"type": "message", "user": "U001", "text": "Nice work!"},
        ]
        result = _try_slack_json(data)
        assert result is not None
        assert "deploy" in result

    def test_non_message_items_skipped(self):
        data = [
            {"type": "channel_join", "user": "U001"},
            {"type": "message", "user": "U001", "text": "Hello"},
            {"type": "message", "user": "U002", "text": "Hi"},
        ]
        result = _try_slack_json(data)
        assert result is not None

    def test_not_a_list(self):
        assert _try_slack_json({"key": "val"}) is None


class TestExtractContent:
    def test_string(self):
        assert _extract_content("hello") == "hello"

    def test_list_of_strings(self):
        assert _extract_content(["hello", "world"]) == "hello world"

    def test_list_of_blocks(self):
        blocks = [{"type": "text", "text": "foo"}, {"type": "text", "text": "bar"}]
        assert _extract_content(blocks) == "foo bar"

    def test_dict_with_text(self):
        assert _extract_content({"text": "content"}) == "content"

    def test_none(self):
        assert _extract_content(None) == ""


class TestMessagesToTranscript:
    def test_user_assistant_pairs(self):
        msgs = [("user", "Q1"), ("assistant", "A1"), ("user", "Q2"), ("assistant", "A2")]
        result = _messages_to_transcript(msgs)
        assert "> Q1" in result
        assert "A1" in result
        assert "> Q2" in result

    def test_consecutive_user_messages(self):
        msgs = [("user", "First"), ("user", "Second"), ("assistant", "Reply")]
        result = _messages_to_transcript(msgs)
        assert "> First" in result
        assert "> Second" in result


class TestNormalizeIntegration:
    def test_json_file_auto_detected(self, tmp_path):
        data = [
            {"role": "user", "content": "What is Python?"},
            {"role": "assistant", "content": "A programming language."},
        ]
        f = tmp_path / "chat.json"
        f.write_text(json.dumps(data))
        result = normalize(str(f))
        assert "> What is Python?" in result

    def test_unreadable_file_raises(self, tmp_path):
        with pytest.raises(IOError):
            normalize(str(tmp_path / "nonexistent.txt"))
