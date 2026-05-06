"""Tests for detect_palace_holder + mine pre-flight refusal (issue #1264).

The bug: when an MCP server (or any other writer) holds the palace's
chroma.sqlite3 open, ``mempalace mine`` would print only the auto-defaults
warning and exit with no diagnostic — the chroma open would either block
silently or SIGSEGV under chromadb 1.5.x's concurrent-writer behavior.

The fix detects a live holder before opening chroma and refuses with a
clear stderr message + non-zero exit. POSIX uses ``lsof``; Windows and
hosts without ``lsof`` degrade silently to None.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys

import pytest

from mempalace import miner, palace
from mempalace.palace import detect_palace_holder


# ---------------------------------------------------------------------------
# detect_palace_holder — pure unit tests (subprocess mocked)
# ---------------------------------------------------------------------------


def test_returns_none_when_palace_dir_missing(tmp_path):
    """No chroma.sqlite3 → no holder, no subprocess call."""
    assert detect_palace_holder(str(tmp_path / "missing_palace")) is None


def test_returns_none_when_chroma_db_missing(tmp_path):
    """Palace dir exists but no chroma.sqlite3 yet → no detection attempted."""
    palace_dir = tmp_path / "palace"
    palace_dir.mkdir()
    assert detect_palace_holder(str(palace_dir)) is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only path")
def test_returns_none_on_lsof_missing(tmp_path, monkeypatch):
    """If `lsof` is not installed, degrade to None (don't crash)."""
    palace_dir = tmp_path / "palace"
    palace_dir.mkdir()
    (palace_dir / "chroma.sqlite3").write_bytes(b"")

    def _raise_fnf(*_args, **_kwargs):
        raise FileNotFoundError("lsof")

    monkeypatch.setattr(subprocess, "run", _raise_fnf)
    assert detect_palace_holder(str(palace_dir)) is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only path")
def test_returns_none_on_lsof_timeout(tmp_path, monkeypatch):
    """A hung lsof must not hang the mine — we degrade after the timeout."""
    palace_dir = tmp_path / "palace"
    palace_dir.mkdir()
    (palace_dir / "chroma.sqlite3").write_bytes(b"")

    def _raise_timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="lsof", timeout=2)

    monkeypatch.setattr(subprocess, "run", _raise_timeout)
    assert detect_palace_holder(str(palace_dir)) is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only path")
def test_returns_none_when_lsof_finds_no_holders(tmp_path, monkeypatch):
    """Empty lsof output (returncode 0 or 1) → no holder."""
    palace_dir = tmp_path / "palace"
    palace_dir.mkdir()
    (palace_dir / "chroma.sqlite3").write_bytes(b"")

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(args=a, returncode=1, stdout="", stderr=""),
    )
    assert detect_palace_holder(str(palace_dir)) is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only path")
def test_skips_self_pid(tmp_path, monkeypatch):
    """If the only holder is our own PID, we are not "another writer"."""
    palace_dir = tmp_path / "palace"
    palace_dir.mkdir()
    (palace_dir / "chroma.sqlite3").write_bytes(b"")

    own_pid = os.getpid()
    lsof_output = f"p{own_pid}\ncPython\nn{palace_dir / 'chroma.sqlite3'}\n"
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            args=a, returncode=0, stdout=lsof_output, stderr=""
        ),
    )
    assert detect_palace_holder(str(palace_dir)) is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only path")
def test_classifies_mcp_server_holder(tmp_path, monkeypatch):
    """An MCP server holding the db is reported with kind='mempalace.mcp_server'."""
    palace_dir = tmp_path / "palace"
    palace_dir.mkdir()
    (palace_dir / "chroma.sqlite3").write_bytes(b"")

    other_pid = os.getpid() + 1  # any PID that isn't us
    lsof_output = f"p{other_pid}\ncPython\nn{palace_dir / 'chroma.sqlite3'}\n"

    def _fake_run(cmd, *args, **kwargs):
        if cmd[0] == "lsof":
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=lsof_output, stderr=""
            )
        if cmd[0] == "ps":
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout="/usr/bin/python3 -m mempalace.mcp_server --palace ~/palace\n",
                stderr="",
            )
        raise AssertionError(f"unexpected cmd: {cmd}")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    holder = detect_palace_holder(str(palace_dir))
    assert holder == {"pid": other_pid, "command": "Python", "kind": "mempalace.mcp_server"}


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only path")
def test_classifies_concurrent_mine_holder(tmp_path, monkeypatch):
    """A sibling `mempalace mine` is reported with kind='mempalace mine'."""
    palace_dir = tmp_path / "palace"
    palace_dir.mkdir()
    (palace_dir / "chroma.sqlite3").write_bytes(b"")

    other_pid = os.getpid() + 1
    lsof_output = f"p{other_pid}\ncPython\nn{palace_dir / 'chroma.sqlite3'}\n"

    def _fake_run(cmd, *args, **kwargs):
        if cmd[0] == "lsof":
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=lsof_output, stderr=""
            )
        if cmd[0] == "ps":
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout="/usr/bin/python3 /usr/local/bin/mempalace mine /tmp/proj\n",
                stderr="",
            )
        raise AssertionError(f"unexpected cmd: {cmd}")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    holder = detect_palace_holder(str(palace_dir))
    assert holder is not None
    assert holder["kind"] == "mempalace mine"
    assert holder["pid"] == other_pid


def test_returns_none_on_windows(tmp_path, monkeypatch):
    """Windows has no `lsof` — we degrade silently rather than crash."""
    palace_dir = tmp_path / "palace"
    palace_dir.mkdir()
    (palace_dir / "chroma.sqlite3").write_bytes(b"")
    monkeypatch.setattr(sys, "platform", "win32")
    assert detect_palace_holder(str(palace_dir)) is None


# ---------------------------------------------------------------------------
# mine() pre-flight integration — refuses with non-zero exit and clear stderr
# ---------------------------------------------------------------------------


def test_mine_exits_nonzero_when_holder_detected(tmp_path, monkeypatch, capsys):
    """When detect_palace_holder reports a holder, mine() must exit 1
    with a clear stderr message — *before* the auto-defaults warning."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "main.py").write_text("print('hello world')\n" * 20)

    palace_path = str(tmp_path / "palace")

    fake_holder = {"pid": 12345, "command": "Python", "kind": "mempalace.mcp_server"}
    monkeypatch.setattr(miner, "detect_palace_holder", lambda _p: fake_holder)

    with pytest.raises(SystemExit) as exc_info:
        miner.mine(project_dir=str(project_dir), palace_path=palace_path)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "cannot start" in captured.err
    assert "mempalace.mcp_server" in captured.err
    assert "PID 12345" in captured.err
    assert palace_path in captured.err
    # The auto-defaults warning lives in load_config, which must NOT have
    # run yet — pre-flight refusal happens before any config inspection.
    assert "auto-detected defaults" not in captured.err


def test_mine_proceeds_when_no_holder(tmp_path, monkeypatch):
    """When detect_palace_holder returns None, mine() proceeds normally."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "main.py").write_text("print('hello world')\n" * 20)

    palace_path = str(tmp_path / "palace")

    monkeypatch.setattr(miner, "detect_palace_holder", lambda _p: None)
    monkeypatch.setenv("HOME", str(tmp_path))  # isolate the lock dir

    # Should not raise SystemExit — mine should complete normally.
    miner.mine(
        project_dir=str(project_dir),
        palace_path=palace_path,
        wing_override="testwing",
    )


def test_mine_exits_nonzero_on_mine_already_running(tmp_path, monkeypatch, capsys):
    """When mine_palace_lock raises MineAlreadyRunning, mine() exits 1 with
    a clear message (was: silently exit 0 with 'exiting cleanly' wording)."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "main.py").write_text("print('hello world')\n" * 20)

    palace_path = str(tmp_path / "palace")

    monkeypatch.setattr(miner, "detect_palace_holder", lambda _p: None)

    @contextlib.contextmanager
    def _raise_lock(_path):
        raise palace.MineAlreadyRunning("simulated contention")
        yield  # pragma: no cover — unreachable, kept for generator validity

    monkeypatch.setattr(miner, "mine_palace_lock", _raise_lock)

    with pytest.raises(SystemExit) as exc_info:
        miner.mine(project_dir=str(project_dir), palace_path=palace_path)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "cannot start" in captured.err
    assert palace_path in captured.err
    assert "another `mempalace mine`" in captured.err


def test_dry_run_skips_pre_flight(tmp_path, monkeypatch, capsys):
    """Dry-run mode does not open chroma, so it must not be blocked by a
    detected holder — preserves the existing 'dry-run is always safe' contract."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "main.py").write_text("print('hello world')\n" * 20)

    palace_path = str(tmp_path / "palace")

    fake_holder = {"pid": 12345, "command": "Python", "kind": "mempalace.mcp_server"}
    monkeypatch.setattr(miner, "detect_palace_holder", lambda _p: fake_holder)

    # Dry run should NOT raise SystemExit — pre-flight is dry-run-bypassed.
    miner.mine(
        project_dir=str(project_dir),
        palace_path=palace_path,
        wing_override="testwing",
        dry_run=True,
    )
