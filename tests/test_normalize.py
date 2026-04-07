import json
from mempalace.normalize import (
    normalize,
    _try_chatgpt_json,
    _try_slack_json,
    _extract_content,
)


def test_plain_text(tmp_dir):
    f = tmp_dir / "plain.txt"
    f.write_text("Hello world\nSecond line\n")
    result = normalize(str(f))
    assert "Hello world" in result


def test_empty_file(tmp_dir):
    f = tmp_dir / "empty.txt"
    f.write_text("")
    result = normalize(str(f))
    assert result.strip() == ""


def test_passthrough_with_markers(tmp_dir):
    content = "> Question 1\nAnswer 1\n\n> Question 2\nAnswer 2\n\n> Question 3\nAnswer 3\n"
    f = tmp_dir / "marked.txt"
    f.write_text(content)
    result = normalize(str(f))
    assert result == content


def test_claude_ai_json(tmp_dir):
    data = [
        {"role": "user", "content": "Hi there"},
        {"role": "assistant", "content": "Hello back"},
    ]
    f = tmp_dir / "claude.json"
    f.write_text(json.dumps(data))
    result = normalize(str(f))
    assert "> Hi there" in result
    assert "Hello back" in result


def test_claude_code_jsonl(tmp_dir):
    lines = [
        json.dumps({"type": "human", "message": {"content": "What is X?"}}),
        json.dumps({"type": "assistant", "message": {"content": "X is a thing."}}),
        json.dumps({"type": "user", "message": {"content": "Tell me more."}}),
        json.dumps({"type": "assistant", "message": {"content": "More details here."}}),
    ]
    f = tmp_dir / "session.jsonl"
    f.write_text("\n".join(lines))
    result = normalize(str(f))
    assert "> What is X?" in result
    assert "X is a thing." in result
    assert "> Tell me more." in result


def test_chatgpt_json():
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
    assert "Hello! How can I help?" in result


def test_slack_json_two_person():
    data = [
        {"type": "message", "user": "U001", "text": "Hey, got a minute?"},
        {"type": "message", "user": "U002", "text": "Sure, what's up?"},
        {"type": "message", "user": "U001", "text": "Need to discuss the deploy."},
    ]
    result = _try_slack_json(data)
    assert result is not None
    assert "> Hey, got a minute?" in result
    assert "Sure, what's up?" in result


def test_slack_json_skips_non_messages():
    data = [
        {"type": "message", "user": "U001", "text": "First"},
        {"type": "channel_join", "user": "U002"},
        {"type": "message", "user": "U002", "text": "Second"},
    ]
    result = _try_slack_json(data)
    assert result is not None
    assert "First" in result
    assert "Second" in result


def test_extract_content_string():
    assert _extract_content("hello") == "hello"


def test_extract_content_list_of_blocks():
    blocks = [{"type": "text", "text": "part one"}, {"type": "text", "text": "part two"}]
    assert "part one" in _extract_content(blocks)
    assert "part two" in _extract_content(blocks)


def test_extract_content_dict():
    assert _extract_content({"text": "from dict"}) == "from dict"
