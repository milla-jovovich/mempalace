"""Tests for stop-hook env-var tuning knobs.

Covers ``MEMPAL_SAVE_INTERVAL`` and ``MEMPAL_STOP_HOOK_DISABLE`` added on
top of the existing stop-hook behavior.
"""

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
