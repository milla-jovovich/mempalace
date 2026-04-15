"""Tests for the mempalace walker subcommand group (Task 4b)."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from mempalace import cli
from mempalace.walker.gpu_detect import HardwareTier, WalkerHardware


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Redirect HOME so walker_ready flag goes to tmp_path."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_walker_init_full_tier_writes_flag(isolated_home):
    """walker init on FULL-tier hardware writes walker_ready and exits 0."""
    fake_hw = WalkerHardware(HardwareTier.FULL, "NVIDIA RTX A5000", 24.0)
    with patch("mempalace.walker.gpu_detect.detect_hardware", return_value=fake_hw):
        rc = cli.main(["walker", "init"])
    assert rc == 0
    flag = isolated_home / ".mempalace" / "walker_ready"
    assert flag.exists()
    data = json.loads(flag.read_text())
    assert data["tier"] == "full"
    assert data["device"] == "NVIDIA RTX A5000"


def test_walker_init_cpu_only_fails(isolated_home):
    """walker init on CPU_ONLY hardware exits 1 and does not write flag."""
    fake_hw = WalkerHardware(HardwareTier.CPU_ONLY, None, None)
    with patch("mempalace.walker.gpu_detect.detect_hardware", return_value=fake_hw):
        rc = cli.main(["walker", "init"])
    assert rc == 1
    flag = isolated_home / ".mempalace" / "walker_ready"
    assert not flag.exists()


def test_walker_status_initialized(isolated_home, capsys):
    """walker status reads the flag file and prints hardware info."""
    flag_dir = isolated_home / ".mempalace"
    flag_dir.mkdir(parents=True, exist_ok=True)
    (flag_dir / "walker_ready").write_text(
        json.dumps({"tier": "full", "device": "NVIDIA RTX A5000", "vram_gb": 24.0})
    )
    rc = cli.main(["walker", "status"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "initialized" in out.lower() or "full" in out.lower()


def test_walker_status_not_initialized(isolated_home, capsys):
    """walker status with no flag prints not-initialized message."""
    rc = cli.main(["walker", "status"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "not initialized" in out.lower()


def test_status_walker_flag_reports_subsystem(isolated_home, capsys):
    """mempalace status --walker appends walker subsystem info to normal status output."""
    fake_hw = WalkerHardware(HardwareTier.FULL, "NVIDIA RTX A5000", 24.0)
    with patch(
        "mempalace.walker.gpu_detect.detect_hardware", return_value=fake_hw
    ):
        rc = cli.main(["status", "--walker"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Walker" in out
    assert "NVIDIA RTX A5000" in out or "not initialized" in out
