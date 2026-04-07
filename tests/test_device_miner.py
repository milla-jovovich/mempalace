"""Tests for device_miner.py — no network, no API keys required."""

import os
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, PropertyMock

import pytest

from mempalace.device_miner import (
    _chunk_text,
    _infer_wing,
    _shell_profile,
    _cloud_providers,
    _agent_sessions,
    _obsidian_vaults,
    mine_device,
)


class TestChunking:
    def test_short_text_single_chunk(self):
        text = "Hello world, this is a test that is long enough to pass the minimum chunk size threshold easily."
        chunks = _chunk_text(text)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_empty_text(self):
        assert _chunk_text("") == []
        assert _chunk_text("   ") == []

    def test_text_below_min_size(self):
        assert _chunk_text("tiny") == []

    def test_long_text_multiple_chunks(self):
        text = "x" * 2000
        chunks = _chunk_text(text, size=800, overlap=100)
        assert len(chunks) >= 2
        # Verify overlap
        assert chunks[0][-100:] == chunks[1][:100]


class TestInferWing:
    def test_github_org_extraction(self):
        assert _infer_wing({"remote": "https://github.com/firstbatchxyz/kai.git", "path": "/x"}) == "firstbatchxyz"
        assert _infer_wing({"remote": "git@github.com:myorg/repo.git", "path": "/x"}) == "myorg"

    def test_skip_dotfile_repos(self):
        assert _infer_wing({"remote": "", "path": "/home/user/.claude/plugins/foo"}) == ""
        assert _infer_wing({"remote": "", "path": "/home/user/.zsh/autosuggestions"}) == ""
        assert _infer_wing({"remote": "", "path": "/home/user/.nvm"}) == ""

    def test_local_fallback(self):
        assert _infer_wing({"remote": "", "path": "/home/user/projects/foo"}) == "local"


class TestAgentSessions:
    def test_detects_claude_code_projects(self):
        """Should find Claude Code projects and read CLAUDE.md files.

        Uses the real ~/.claude directory if it exists — this tests actual
        Claude Code integration on developer machines. Skips on CI/machines
        without Claude Code installed.
        """
        home = Path.home()
        claude_dir = home / ".claude" / "projects"
        if not claude_dir.is_dir() or not list(claude_dir.iterdir()):
            pytest.skip("No Claude Code projects found — install Claude Code to test")

        sessions = _agent_sessions()
        claude = [s for s in sessions if s["agent"] == "claude-code"]
        assert len(claude) == 1
        assert len(claude[0]["projects"]) > 0
        # At least one project should have a name and path
        first = claude[0]["projects"][0]
        assert "name" in first
        assert "path" in first

    def test_no_sessions_in_empty_home(self, tmp_path):
        """Should return empty when home has no agent directories."""
        # Create a completely bare home directory
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        # Directly test the function's logic with a patched home
        import mempalace.device_miner as dm
        original_home = Path.home
        Path.home = staticmethod(lambda: fake_home)
        try:
            sessions = _agent_sessions()
            assert sessions == []
        finally:
            Path.home = original_home


class TestMineDeviceDryRun:
    def test_dry_run_produces_no_drawers(self, tmp_path):
        """Dry run should not add anything to the palace."""
        palace = str(tmp_path / "palace")

        mine_device(
            palace_path=palace,
            home_dir=str(tmp_path),  # empty dir, fast
            dry_run=True,
        )

        import chromadb
        client = chromadb.PersistentClient(path=palace)
        col = client.get_collection("mempalace_drawers")
        assert col.count() == 0


class TestMineDeviceIntegration:
    def test_mines_git_repo(self, tmp_path):
        """Should discover and file a git repo."""
        # Create a minimal git repo
        repo = tmp_path / "myproject"
        repo.mkdir()
        os.system(f'cd "{repo}" && git init && git commit --allow-empty -m "init" 2>/dev/null')
        (repo / "README.md").write_text("# My Project\nA cool thing.")
        os.system(f'cd "{repo}" && git add . && git commit -m "add readme" 2>/dev/null')

        palace = str(tmp_path / "palace")
        mine_device(
            palace_path=palace,
            home_dir=str(tmp_path),
            max_depth=3,
        )

        import chromadb
        client = chromadb.PersistentClient(path=palace)
        col = client.get_collection("mempalace_drawers")
        assert col.count() > 0

        # Verify the repo was filed
        results = col.get(where={"room": "myproject"})
        assert len(results["ids"]) > 0
