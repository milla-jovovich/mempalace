"""Tests for stop-hook env-var tuning knobs.

Covers ``MEMPAL_SAVE_INTERVAL`` and ``MEMPAL_STOP_HOOK_DISABLE`` added on
top of the existing stop-hook behavior.
"""

import contextlib
import io
import json
from unittest.mock import patch

import pytest

from mempalace import hooks_cli


@pytest.fixture
def clean_env(monkeypatch):
    for key in ("MEMPAL_SAVE_INTERVAL", "MEMPAL_STOP_HOOK_DISABLE"):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


# ---------------------------------------------------------------------------
# _get_save_interval
# ---------------------------------------------------------------------------


def test_default_when_unset(clean_env):
    assert hooks_cli._get_save_interval() == hooks_cli.DEFAULT_SAVE_INTERVAL


@pytest.mark.parametrize("raw,expected", [
    ("50", 50),
    ("  100  ", 100),
    ("1", 1),
])
def test_overrides_from_env(clean_env, raw, expected):
    clean_env.setenv("MEMPAL_SAVE_INTERVAL", raw)
    assert hooks_cli._get_save_interval() == expected


@pytest.mark.parametrize("raw", ["", "   "])
def test_empty_falls_back_to_default(clean_env, raw):
    clean_env.setenv("MEMPAL_SAVE_INTERVAL", raw)
    assert hooks_cli._get_save_interval() == hooks_cli.DEFAULT_SAVE_INTERVAL


@pytest.mark.parametrize("raw", ["abc", "3.5", "not-a-number", "--"])
def test_invalid_falls_back_to_default(clean_env, raw):
    """A typo must never reduce the interval to 0 and block every turn."""
    clean_env.setenv("MEMPAL_SAVE_INTERVAL", raw)
    assert hooks_cli._get_save_interval() == hooks_cli.DEFAULT_SAVE_INTERVAL


@pytest.mark.parametrize("raw", ["0", "-1", "-99"])
def test_nonpositive_clamped_to_one(clean_env, raw):
    clean_env.setenv("MEMPAL_SAVE_INTERVAL", raw)
    assert hooks_cli._get_save_interval() == 1


# ---------------------------------------------------------------------------
# _stop_hook_disabled
# ---------------------------------------------------------------------------


def test_disabled_default_is_false(clean_env):
    assert hooks_cli._stop_hook_disabled() is False


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "Yes", "on", "  true  "])
def test_disabled_truthy_variants(clean_env, raw):
    clean_env.setenv("MEMPAL_STOP_HOOK_DISABLE", raw)
    assert hooks_cli._stop_hook_disabled() is True


@pytest.mark.parametrize("raw", ["0", "false", "no", "off", "", "  ", "maybe"])
def test_disabled_falsy_variants(clean_env, raw):
    clean_env.setenv("MEMPAL_STOP_HOOK_DISABLE", raw)
    assert hooks_cli._stop_hook_disabled() is False


# ---------------------------------------------------------------------------
# Backwards compatibility
# ---------------------------------------------------------------------------


def test_module_still_exports_save_interval_constant():
    """Existing code / tests that read ``hooks_cli.SAVE_INTERVAL`` keep working."""
    assert hooks_cli.SAVE_INTERVAL == hooks_cli.DEFAULT_SAVE_INTERVAL == 15


# ---------------------------------------------------------------------------
# Integration: hook_stop honors env vars at runtime
# ---------------------------------------------------------------------------


def _run_hook_stop(data, state_dir):
    """Execute ``hook_stop`` and capture its JSON stdout."""
    buf = io.StringIO()
    patches = [
        patch(
            "mempalace.hooks_cli._output",
            side_effect=lambda d: buf.write(json.dumps(d)),
        ),
        patch("mempalace.hooks_cli.STATE_DIR", state_dir),
    ]
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        hooks_cli.hook_stop(data, "claude-code")
    return json.loads(buf.getvalue())


def _write_transcript(path, n):
    with open(path, "w", encoding="utf-8") as f:
        for i in range(n):
            f.write(json.dumps({"message": {"role": "user", "content": f"msg {i}"}}) + "\n")


def test_hook_stop_honors_custom_save_interval(clean_env, tmp_path):
    """MEMPAL_SAVE_INTERVAL=3 must trigger block at 3 messages, not the 15 default."""
    clean_env.setenv("MEMPAL_SAVE_INTERVAL", "3")
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, 3)  # exactly at the override

    result = _run_hook_stop(
        {
            "session_id": "integration-interval",
            "stop_hook_active": False,
            "transcript_path": str(transcript),
        },
        state_dir=tmp_path,
    )

    assert result["decision"] == "block"
    assert result["reason"] == hooks_cli.STOP_BLOCK_REASON


def test_hook_stop_custom_interval_passthrough_below_threshold(clean_env, tmp_path):
    """MEMPAL_SAVE_INTERVAL=10 must pass through when below the overridden cap."""
    clean_env.setenv("MEMPAL_SAVE_INTERVAL", "10")
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, 9)  # one short of the override

    result = _run_hook_stop(
        {
            "session_id": "integration-passthrough",
            "stop_hook_active": False,
            "transcript_path": str(transcript),
        },
        state_dir=tmp_path,
    )

    assert result == {}


def test_hook_stop_disable_passes_through(clean_env, tmp_path):
    """MEMPAL_STOP_HOOK_DISABLE=1 must never block, even above the interval."""
    clean_env.setenv("MEMPAL_STOP_HOOK_DISABLE", "1")
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, hooks_cli.DEFAULT_SAVE_INTERVAL * 3)  # well above

    result = _run_hook_stop(
        {
            "session_id": "integration-disabled",
            "stop_hook_active": False,
            "transcript_path": str(transcript),
        },
        state_dir=tmp_path,
    )

    assert result == {}


def test_hook_stop_disable_still_tracks_state(clean_env, tmp_path):
    """Disabled hook must advance the last-save watermark.

    Otherwise, toggling ``MEMPAL_STOP_HOOK_DISABLE`` off mid-session would
    make ``since_last`` include every message accumulated while disabled,
    causing an immediate retroactive block.
    """
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, 100)

    # Disabled phase — accumulate 100 messages but must not block
    clean_env.setenv("MEMPAL_STOP_HOOK_DISABLE", "1")
    result = _run_hook_stop(
        {
            "session_id": "integration-state",
            "stop_hook_active": False,
            "transcript_path": str(transcript),
        },
        state_dir=tmp_path,
    )
    assert result == {}

    last_save_file = tmp_path / "integration-state_last_save"
    assert last_save_file.is_file()
    assert int(last_save_file.read_text().strip()) == 100

    # Re-enable: since the watermark advanced, a single new message must NOT
    # trigger a block (since_last == 0 on the next tick, not 100).
    clean_env.delenv("MEMPAL_STOP_HOOK_DISABLE")
    # One more human message after re-enabling
    with open(transcript, "a", encoding="utf-8") as f:
        f.write(json.dumps({"message": {"role": "user", "content": "resumed"}}) + "\n")

    result = _run_hook_stop(
        {
            "session_id": "integration-state",
            "stop_hook_active": False,
            "transcript_path": str(transcript),
        },
        state_dir=tmp_path,
    )
    # 101 total, last_save=100, since_last=1, interval=15 → passthrough
    assert result == {}


def test_hook_stop_passthrough_when_active_skips_state_update(clean_env, tmp_path):
    """stop_hook_active short-circuit must not touch state (infinite-loop guard)."""
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, 20)

    result = _run_hook_stop(
        {
            "session_id": "integration-active",
            "stop_hook_active": True,
            "transcript_path": str(transcript),
        },
        state_dir=tmp_path,
    )

    assert result == {}
    # state file must not have been created by a short-circuited call
    assert not (tmp_path / "integration-active_last_save").exists()
