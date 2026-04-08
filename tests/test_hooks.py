import json
import stat
import subprocess
import sys

import pytest

from mempalace.hooks import hook_path, hooks_dir


def test_hooks_dir_exists():
    assert hooks_dir().is_dir()


def test_hooks_dir_contains_scripts():
    scripts = {f.name for f in hooks_dir().iterdir() if f.suffix == ".sh"}
    assert "mempal_save_hook.sh" in scripts
    assert "mempal_precompact_hook.sh" in scripts


def test_hook_path_returns_existing_file():
    p = hook_path("mempal_save_hook.sh")
    assert p.is_file()
    assert p.name == "mempal_save_hook.sh"


def test_hook_path_raises_for_missing():
    with pytest.raises(FileNotFoundError):
        hook_path("nonexistent_hook.sh")


def test_hook_scripts_are_executable():
    for name in ("mempal_save_hook.sh", "mempal_precompact_hook.sh"):
        p = hook_path(name)
        mode = p.stat().st_mode
        assert mode & stat.S_IXUSR, f"{name} should be executable"


def test_cli_hooks_path():
    result = subprocess.run(
        [sys.executable, "-m", "mempalace", "hooks", "path"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip().endswith("hooks")


def test_cli_hooks_install_claude():
    result = subprocess.run(
        [sys.executable, "-m", "mempalace", "hooks", "install"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    lines = result.stdout.strip().split("\n")
    json_str = "\n".join(lines[2:])  # skip header + blank line
    config = json.loads(json_str)
    assert "hooks" in config
    assert "Stop" in config["hooks"]
    assert "PreCompact" in config["hooks"]


def test_cli_hooks_install_codex():
    result = subprocess.run(
        [sys.executable, "-m", "mempalace", "hooks", "install", "--format", "codex"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    lines = result.stdout.strip().split("\n")
    json_str = "\n".join(lines[2:])  # skip header + blank line
    config = json.loads(json_str)
    assert "Stop" in config
    assert "PreCompact" in config
