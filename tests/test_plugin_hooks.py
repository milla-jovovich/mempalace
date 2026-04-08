"""
test_plugin_hooks.py — Tests for the Claude Code plugin hooks.

Tests the Python save and precompact hooks for correct behavior:
trigger/allow logic, session ID sanitization, and output format.
"""

import json
import subprocess
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent / "plugins" / "mempalace" / "hooks"
SAVE_HOOK = HOOKS_DIR / "mempal_save.py"
PRECOMPACT_HOOK = HOOKS_DIR / "mempal_precompact.py"


def run_hook(hook_path, input_data):
    """Run a hook script with JSON input, return (stdout, stderr, exit_code)."""
    proc = subprocess.run(
        [sys.executable, str(hook_path)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        timeout=10,
    )
    return proc.stdout.strip(), proc.stderr.strip(), proc.returncode


def parse_output(stdout):
    """Parse hook JSON output, return None if empty."""
    if not stdout:
        return None
    return json.loads(stdout)


class TestSaveHook:
    def test_allows_when_stop_hook_active(self):
        stdout, _, code = run_hook(
            SAVE_HOOK,
            {
                "session_id": "test-active",
                "stop_hook_active": True,
                "transcript_path": "",
            },
        )
        assert code == 0
        assert stdout == ""

    def test_allows_when_no_transcript(self):
        stdout, _, code = run_hook(
            SAVE_HOOK,
            {
                "session_id": "test-no-transcript",
                "stop_hook_active": False,
                "transcript_path": "",
            },
        )
        assert code == 0
        assert stdout == ""

    def test_allows_when_under_threshold(self, tmp_path):
        # Create transcript with 5 user messages (under 15 threshold)
        transcript = tmp_path / "short.jsonl"
        lines = []
        for i in range(5):
            lines.append(json.dumps({"message": {"role": "user", "content": f"msg {i}"}}))
            lines.append(json.dumps({"message": {"role": "assistant", "content": f"resp {i}"}}))
        transcript.write_text("\n".join(lines))

        stdout, _, code = run_hook(
            SAVE_HOOK,
            {
                "session_id": "test-under-threshold",
                "stop_hook_active": False,
                "transcript_path": str(transcript),
            },
        )
        assert code == 0
        assert stdout == ""

    def test_triggers_save_at_threshold(self, tmp_path):
        # Create transcript with 16 user messages (over 15 threshold)
        transcript = tmp_path / "long.jsonl"
        lines = []
        for i in range(16):
            lines.append(json.dumps({"message": {"role": "user", "content": f"msg {i}"}}))
            lines.append(json.dumps({"message": {"role": "assistant", "content": f"resp {i}"}}))
        transcript.write_text("\n".join(lines))

        stdout, _, code = run_hook(
            SAVE_HOOK,
            {
                "session_id": "test-at-threshold",
                "stop_hook_active": False,
                "transcript_path": str(transcript),
            },
        )
        assert code == 0
        result = parse_output(stdout)
        assert result is not None
        assert result["decision"] == "block"
        assert "AUTO-SAVE" in result["reason"]

    def test_skips_command_messages(self, tmp_path):
        # 16 messages but all are command messages — should not trigger
        transcript = tmp_path / "commands.jsonl"
        lines = []
        for i in range(16):
            lines.append(
                json.dumps(
                    {
                        "message": {
                            "role": "user",
                            "content": f"<command-message>cmd {i}</command-message>",
                        }
                    }
                )
            )
            lines.append(json.dumps({"message": {"role": "assistant", "content": f"resp {i}"}}))
        transcript.write_text("\n".join(lines))

        stdout, _, code = run_hook(
            SAVE_HOOK,
            {
                "session_id": "test-commands-only",
                "stop_hook_active": False,
                "transcript_path": str(transcript),
            },
        )
        assert code == 0
        assert stdout == ""

    def test_handles_malformed_json_input(self):
        proc = subprocess.run(
            [sys.executable, str(SAVE_HOOK)],
            input="not valid json",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""

    def test_handles_empty_input(self):
        proc = subprocess.run(
            [sys.executable, str(SAVE_HOOK)],
            input="",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""

    def test_sanitizes_session_id(self, tmp_path):
        # Path traversal attempt in session_id
        transcript = tmp_path / "traverse.jsonl"
        lines = []
        for i in range(16):
            lines.append(json.dumps({"message": {"role": "user", "content": f"msg {i}"}}))
            lines.append(json.dumps({"message": {"role": "assistant", "content": f"resp {i}"}}))
        transcript.write_text("\n".join(lines))

        stdout, _, code = run_hook(
            SAVE_HOOK,
            {
                "session_id": "../../tmp/evil",
                "stop_hook_active": False,
                "transcript_path": str(transcript),
            },
        )
        assert code == 0
        # Should trigger save (16 messages) but session ID should be sanitized
        result = parse_output(stdout)
        assert result is not None
        assert result["decision"] == "block"

        # Verify no file written outside state dir
        state_dir = Path.home() / ".mempalace" / "hook_state"
        if state_dir.exists():
            for f in state_dir.iterdir():
                assert ".." not in f.name

    def test_always_exits_zero(self, tmp_path):
        """Hooks must always exit 0 — non-zero is treated as a warning by Claude Code."""
        test_cases = [
            {"session_id": "x", "stop_hook_active": True},
            {"session_id": "x", "stop_hook_active": False, "transcript_path": "/nonexistent"},
            {"session_id": "x"},
            {},
        ]
        for case in test_cases:
            _, _, code = run_hook(SAVE_HOOK, case)
            assert code == 0, f"Non-zero exit for input: {case}"


class TestPrecompactHook:
    def test_always_blocks(self):
        stdout, _, code = run_hook(
            PRECOMPACT_HOOK,
            {
                "session_id": "test-compact",
            },
        )
        assert code == 0
        result = parse_output(stdout)
        assert result is not None
        assert result["decision"] == "block"
        assert "COMPACTION" in result["reason"]

    def test_blocks_with_empty_input(self):
        stdout, _, code = run_hook(PRECOMPACT_HOOK, {})
        assert code == 0
        result = parse_output(stdout)
        assert result is not None
        assert result["decision"] == "block"

    def test_handles_malformed_json(self):
        proc = subprocess.run(
            [sys.executable, str(PRECOMPACT_HOOK)],
            input="garbage",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0
        result = parse_output(proc.stdout.strip())
        assert result is not None
        assert result["decision"] == "block"

    def test_always_exits_zero(self):
        test_cases = [
            {"session_id": "x"},
            {},
            {"session_id": "../../evil"},
        ]
        for case in test_cases:
            _, _, code = run_hook(PRECOMPACT_HOOK, case)
            assert code == 0, f"Non-zero exit for input: {case}"
