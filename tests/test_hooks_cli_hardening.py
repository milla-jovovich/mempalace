"""Hardening tests for hook transcript parsing with harness-native fixtures."""

import contextlib
import io
import json
from pathlib import Path
from unittest.mock import patch

from mempalace.hooks_cli import (
    SAVE_INTERVAL,
    _count_human_messages,
    _extract_text_content,
    _is_real_human_turn,
    _output,
    hook_stop,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "transcripts"


def _capture_hook_output(hook_fn, data, harness="claude-code", state_dir=None):
    """Capture hook JSON output without forking a subprocess in each test."""
    buf = io.StringIO()
    patches = [patch("mempalace.hooks_cli._output", side_effect=lambda d: buf.write(json.dumps(d)))]
    if state_dir is not None:
        patches.append(patch("mempalace.hooks_cli.STATE_DIR", state_dir))
    with contextlib.ExitStack() as stack:
        for patcher in patches:
            stack.enter_context(patcher)
        hook_fn(data, harness)
    return json.loads(buf.getvalue())


def test_count_human_messages_from_claude_code_fixture_ignores_tool_loop_noise():
    fixture = FIXTURE_DIR / "claude_code_hook_transcript.jsonl"

    # The fixture includes one tool_result-only synthetic turn and one
    # command-message. Only the two real human requests should count.
    assert _count_human_messages(str(fixture)) == 2


def test_count_human_messages_from_codex_fixture_uses_canonical_event_messages():
    fixture = FIXTURE_DIR / "codex_rollout.jsonl"

    # response_item payloads duplicate or synthesize context. The stop hook
    # should advance only on the canonical event_msg conversation turns.
    assert _count_human_messages(str(fixture)) == 2


def test_stop_hook_blocks_at_interval_for_raw_claude_code_transcript(tmp_path):
    transcript = tmp_path / "claude-session.jsonl"
    entries = []
    for idx in range(SAVE_INTERVAL):
        # Each loop contributes one real human turn plus one synthetic
        # tool-result turn that must not push the counter forward.
        entries.extend(
            [
                {
                    "type": "human",
                    "message": {
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f"Checkpoint the release review after request {idx} and keep the rollback "
                                    "notes attached to the final summary."
                                ),
                            }
                        ]
                    },
                },
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "Reviewing the release notes now."},
                            {
                                "type": "tool_use",
                                "id": f"toolu_{idx}",
                                "name": "Read",
                                "input": {"file_path": f"/tmp/release-{idx}.md"},
                            },
                        ]
                    },
                },
                {
                    "type": "human",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": f"toolu_{idx}",
                                "content": "release notes body",
                            }
                        ]
                    },
                },
            ]
        )

    with open(transcript, "w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")

    result = _capture_hook_output(
        hook_stop,
        {"session_id": "claude-fixture", "stop_hook_active": False, "transcript_path": str(transcript)},
        state_dir=tmp_path,
    )

    assert result["decision"] == "block"


def test_extract_text_content_ignores_non_text_blocks_but_keeps_string_items():
    content = [{"type": "tool_result", "content": "ignore me"}, "free text", {"type": "text", "text": "kept"}]

    assert _extract_text_content(content) == "free text\nkept"


def test_extract_text_content_returns_empty_for_non_list_payload():
    assert _extract_text_content({"type": "text", "text": "not a list here"}) == ""


def test_is_real_human_turn_handles_non_dict_and_bad_message_payloads():
    assert _is_real_human_turn("not a dict") is False
    assert _is_real_human_turn({"type": "human", "message": []}) is False


def test_count_human_messages_returns_zero_when_open_fails(monkeypatch, tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("{}", encoding="utf-8")

    def _boom(*args, **kwargs):
        raise OSError("cannot read")

    monkeypatch.setattr("builtins.open", _boom)

    assert _count_human_messages(str(transcript)) == 0


def test_output_prints_pretty_json(capsys):
    _output({"decision": "block"})

    stdout = capsys.readouterr().out
    assert '"decision": "block"' in stdout
