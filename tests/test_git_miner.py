"""
tests/test_git_miner.py — Tests for mempalace.git_miner.

All tests mock subprocess.run so they require no git binary, no gh CLI,
and no network access.
"""

import hashlib
import shutil
import subprocess
import tempfile
from unittest.mock import MagicMock, call, patch

import chromadb
import pytest

from mempalace.git_miner import (
    DEFAULT_ROOM,
    DEFAULT_WING,
    GitEntry,
    _DECISION_RE,
    collect_commits,
    collect_entries,
    collect_prs,
    mine_git,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

LOG_SEP = ">>MP<<"


def _make_log_output(*records):
    """Build a fake ``git log`` stdout from (sha, author, date, subject, body) tuples."""
    parts = []
    for sha, author, date, subject, body in records:
        parts.append(f"{sha}|{author}|{date}|{subject}|{body}")
    return LOG_SEP + LOG_SEP.join(parts) + LOG_SEP


FAKE_LOG = _make_log_output(
    ("abc123def456", "Alice", "2026-01-01T00:00:00Z", "refactor: extract auth module", ""),
    (
        "111222333444",
        "Bob",
        "2026-01-02T00:00:00Z",
        "feat: add rate limiter",
        "Decided to use token bucket instead of leaky bucket because it handles burst traffic better.",
    ),
    ("deadbeefcafe", "Carol", "2026-01-03T00:00:00Z", "chore: bump deps", ""),
)

FAKE_PR_LIST = """[
  {
    "number": 42,
    "title": "feat: switch to gRPC instead of REST",
    "body": "We chose gRPC over REST because of better performance and streaming support.",
    "author": {"login": "alice"},
    "createdAt": "2026-01-10T00:00:00Z"
  },
  {
    "number": 43,
    "title": "chore: update dependencies",
    "body": "",
    "author": {"login": "bob"},
    "createdAt": "2026-01-11T00:00:00Z"
  }
]"""

FAKE_PR_REVIEWS = """{"reviews": [
  {
    "author": {"login": "carol"},
    "body": "Why not use REST here? The team decided on gRPC for performance reasons.",
    "createdAt": "2026-01-10T12:00:00Z"
  },
  {
    "author": {"login": "dan"},
    "body": "",
    "createdAt": "2026-01-10T13:00:00Z"
  }
]}"""


def _mock_run(stdout="", returncode=0):
    m = MagicMock()
    m.stdout = stdout
    m.returncode = returncode
    return m


# ── GitEntry ───────────────────────────────────────────────────────────────────


class TestGitEntry:
    def test_format_commit(self):
        e = GitEntry("commit", "abc123", "fix: auth bug", "Body text", "Alice", "2026-01-01")
        text = e.format()
        assert "COMMIT abc123" in text
        assert "Subject: fix: auth bug" in text
        assert "Body text" in text

    def test_format_pr(self):
        e = GitEntry("pr", "42", "feat: add feature", "PR body", "bob", "2026-01-01")
        text = e.format()
        assert "PR #42" in text
        assert "Title: feat: add feature" in text

    def test_format_review(self):
        e = GitEntry("review", "42.0", "Review on PR #42: feat", "Review body", "carol", "2026-01-01")
        text = e.format()
        assert "REVIEW 42.0" in text
        assert "Review body" in text

    def test_format_no_body(self):
        e = GitEntry("commit", "abc", "subject only", "", "Alice", "2026-01-01")
        text = e.format()
        assert "subject only" in text
        # No blank body section appended
        assert text.count("\n\n") == 0

    def test_has_decision_signal_title(self):
        e = GitEntry("commit", "abc", "refactor: migrate to new auth", "", "Alice", "2026-01-01")
        assert e.has_decision_signal()

    def test_has_decision_signal_body(self):
        e = GitEntry("commit", "abc", "feat: add thing", "We decided to use X because Y.", "A", "")
        assert e.has_decision_signal()

    def test_no_decision_signal(self):
        e = GitEntry("commit", "abc", "chore: bump deps", "", "Alice", "2026-01-01")
        assert not e.has_decision_signal()

    def test_drawer_id_deterministic(self):
        e = GitEntry("commit", "abc123", "fix: bug", "", "Alice", "2026-01-01")
        id1 = e.drawer_id("wing_code", "git-decisions")
        id2 = e.drawer_id("wing_code", "git-decisions")
        assert id1 == id2

    def test_drawer_id_includes_wing_room(self):
        e = GitEntry("commit", "abc", "fix", "", "A", "")
        id_a = e.drawer_id("wing_a", "room_a")
        id_b = e.drawer_id("wing_b", "room_b")
        assert id_a != id_b

    def test_drawer_id_format(self):
        e = GitEntry("pr", "99", "title", "", "A", "")
        drawer_id = e.drawer_id("wing_code", "git-decisions")
        assert drawer_id.startswith("drawer_wing_code_git-decisions_git_")


# ── collect_commits ────────────────────────────────────────────────────────────


class TestCollectCommits:
    @patch("subprocess.run")
    def test_parses_commits(self, mock_run):
        mock_run.return_value = _mock_run(FAKE_LOG)
        entries = collect_commits("/fake/repo", include_all=True)
        assert len(entries) == 3
        assert all(e.source == "commit" for e in entries)
        assert entries[0].ref == "abc123def456"[:12]
        assert entries[0].title == "refactor: extract auth module"
        assert entries[1].body.startswith("Decided")

    @patch("subprocess.run")
    def test_filters_trivial_commits_by_default(self, mock_run):
        mock_run.return_value = _mock_run(FAKE_LOG)
        entries = collect_commits("/fake/repo", include_all=False)
        # abc123 has no body and no decision signal → excluded
        # deadbeef has no body and no decision signal → excluded
        # 111222 has a body with decision signal → included
        # Also "refactor" in abc123 title matches → included
        titles = [e.title for e in entries]
        assert "chore: bump deps" not in titles  # no body, no signal
        assert "feat: add rate limiter" in titles

    @patch("subprocess.run")
    def test_max_commits_passed_to_git(self, mock_run):
        mock_run.return_value = _mock_run(FAKE_LOG)
        collect_commits("/fake/repo", max_commits=5)
        args = mock_run.call_args[0][0]
        assert "-n5" in args

    @patch("subprocess.run")
    def test_since_passed_to_git(self, mock_run):
        mock_run.return_value = _mock_run(FAKE_LOG)
        collect_commits("/fake/repo", since="2025-01-01")
        args = mock_run.call_args[0][0]
        assert "--since=2025-01-01" in args

    @patch("subprocess.run")
    def test_git_failure_raises(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(128, "git")
        with pytest.raises(RuntimeError, match="git log failed"):
            collect_commits("/fake/repo")

    @patch("subprocess.run")
    def test_empty_repo(self, mock_run):
        mock_run.return_value = _mock_run("")
        entries = collect_commits("/fake/repo")
        assert entries == []


# ── collect_prs ────────────────────────────────────────────────────────────────


class TestCollectPRs:
    @patch("shutil.which", return_value=None)
    def test_no_gh_returns_empty(self, mock_which):
        prs, reviews = collect_prs("/fake/repo")
        assert prs == []
        assert reviews == []

    @patch("shutil.which", return_value="/usr/bin/gh")
    @patch("subprocess.run")
    def test_parses_prs(self, mock_run, mock_which):
        # First call: pr list; subsequent: pr view per PR
        mock_run.side_effect = [
            _mock_run(FAKE_PR_LIST),
            _mock_run(FAKE_PR_REVIEWS),  # reviews for PR 42
            _mock_run('{"reviews": []}'),  # reviews for PR 43
        ]
        prs, reviews = collect_prs("/fake/repo")
        assert len(prs) == 2
        assert prs[0].ref == "42"
        assert prs[0].title == "feat: switch to gRPC instead of REST"
        assert prs[0].author == "alice"

    @patch("shutil.which", return_value="/usr/bin/gh")
    @patch("subprocess.run")
    def test_reviews_fetched_per_pr(self, mock_run, mock_which):
        mock_run.side_effect = [
            _mock_run(FAKE_PR_LIST),
            _mock_run(FAKE_PR_REVIEWS),
            _mock_run('{"reviews": []}'),
        ]
        prs, reviews = collect_prs("/fake/repo")
        # One non-empty review body from PR 42
        assert len(reviews) == 1
        assert reviews[0].source == "review"
        assert "gRPC" in reviews[0].body

    @patch("shutil.which", return_value="/usr/bin/gh")
    @patch("subprocess.run")
    def test_no_reviews_flag_skips_review_fetch(self, mock_run, mock_which):
        mock_run.return_value = _mock_run(FAKE_PR_LIST)
        prs, reviews = collect_prs("/fake/repo", no_reviews=True)
        assert reviews == []
        # Only one subprocess call (pr list), no pr view calls
        assert mock_run.call_count == 1

    @patch("shutil.which", return_value="/usr/bin/gh")
    @patch("subprocess.run")
    def test_gh_failure_returns_empty(self, mock_run, mock_which):
        mock_run.side_effect = subprocess.CalledProcessError(1, "gh", stderr=b"auth error")
        prs, reviews = collect_prs("/fake/repo")
        assert prs == []
        assert reviews == []

    @patch("shutil.which", return_value="/usr/bin/gh")
    @patch("subprocess.run")
    def test_max_prs_limit_passed_to_gh(self, mock_run, mock_which):
        mock_run.side_effect = [_mock_run("[]")]
        collect_prs("/fake/repo", max_prs=10)
        args = mock_run.call_args[0][0]
        assert "10" in args


# ── collect_entries ────────────────────────────────────────────────────────────


class TestCollectEntries:
    @patch("shutil.which", return_value=None)
    @patch("subprocess.run")
    def test_decision_only_filters(self, mock_run, mock_which):
        mock_run.return_value = _mock_run(FAKE_LOG)
        entries = collect_entries("/fake/repo", include_all=True, decision_only=True)
        for e in entries:
            assert e.has_decision_signal(), f"Entry without signal: {e.title!r}"

    @patch("shutil.which", return_value=None)
    @patch("subprocess.run")
    def test_all_sources_combined(self, mock_run, mock_which):
        mock_run.return_value = _mock_run(FAKE_LOG)
        entries = collect_entries("/fake/repo", include_all=True)
        sources = {e.source for e in entries}
        assert "commit" in sources  # no gh → only commits


# ── mine_git (integration via tempdir palace) ──────────────────────────────────


class TestMineGit:
    @patch("shutil.which", return_value=None)
    @patch("subprocess.run")
    def test_files_drawers_to_palace(self, mock_run, mock_which):
        mock_run.return_value = _mock_run(FAKE_LOG)
        tmpdir = tempfile.mkdtemp()
        try:
            result = mine_git(
                repo_dir="/fake/repo",
                palace_path=tmpdir,
                include_all=True,
            )
            assert result["filed"] == 3
            assert result["commits"] == 3
            # Verify drawers landed in ChromaDB
            client = chromadb.PersistentClient(path=tmpdir)
            col = client.get_collection("mempalace_drawers")
            assert col.count() == 3
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @patch("shutil.which", return_value=None)
    @patch("subprocess.run")
    def test_dry_run_does_not_write(self, mock_run, mock_which):
        mock_run.return_value = _mock_run(FAKE_LOG)
        tmpdir = tempfile.mkdtemp()
        try:
            result = mine_git(
                repo_dir="/fake/repo",
                palace_path=tmpdir,
                include_all=True,
                dry_run=True,
            )
            assert result["filed"] == 0
            # No palace directory created by ChromaDB
            import os

            assert not os.path.exists(os.path.join(tmpdir, "chroma.sqlite3"))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @patch("shutil.which", return_value=None)
    @patch("subprocess.run")
    def test_idempotent_upsert(self, mock_run, mock_which):
        """Filing the same repo twice should not duplicate drawers."""
        mock_run.return_value = _mock_run(FAKE_LOG)
        tmpdir = tempfile.mkdtemp()
        try:
            mine_git("/fake/repo", tmpdir, include_all=True)
            mine_git("/fake/repo", tmpdir, include_all=True)
            client = chromadb.PersistentClient(path=tmpdir)
            col = client.get_collection("mempalace_drawers")
            assert col.count() == 3  # not 6
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @patch("shutil.which", return_value=None)
    @patch("subprocess.run")
    def test_default_wing_room(self, mock_run, mock_which):
        mock_run.return_value = _mock_run(FAKE_LOG)
        tmpdir = tempfile.mkdtemp()
        try:
            result = mine_git("/fake/repo", tmpdir, include_all=True)
            client = chromadb.PersistentClient(path=tmpdir)
            col = client.get_collection("mempalace_drawers")
            metas = col.get(include=["metadatas"])["metadatas"]
            assert all(m["wing"] == DEFAULT_WING for m in metas)
            assert all(m["room"] == DEFAULT_ROOM for m in metas)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_invalid_wing_returns_error(self):
        result = mine_git("/fake/repo", "/fake/palace", wing="bad/wing")
        assert "error" in result

    @patch("shutil.which", return_value=None)
    @patch("subprocess.run")
    def test_decision_only_reduces_count(self, mock_run, mock_which):
        mock_run.return_value = _mock_run(FAKE_LOG)
        tmpdir = tempfile.mkdtemp()
        try:
            result_all = mine_git("/fake/repo", tmpdir, include_all=True)
            shutil.rmtree(tmpdir)

            tmpdir2 = tempfile.mkdtemp()
            result_dec = mine_git("/fake/repo", tmpdir2, include_all=True, decision_only=True)
            assert result_dec["filed"] <= result_all["filed"]
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
            shutil.rmtree(tmpdir2, ignore_errors=True)


# ── MCP tool ───────────────────────────────────────────────────────────────────


class TestToolGitMine:
    @patch("shutil.which", return_value=None)
    @patch("subprocess.run")
    def test_mcp_tool_returns_success(self, mock_run, mock_which):
        mock_run.return_value = _mock_run(FAKE_LOG)
        tmpdir = tempfile.mkdtemp()
        try:
            import os

            with patch.dict(os.environ, {"MEMPALACE_PALACE_PATH": tmpdir}):
                # Re-import to pick up patched env (config reads at call time)
                from mempalace.mcp_server import tool_git_mine

                result = tool_git_mine(repo_dir="/fake/repo", all_commits=True)
            assert result["success"] is True
            assert result["drawers_filed"] == 3
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @patch("shutil.which", return_value=None)
    @patch("subprocess.run")
    def test_mcp_tool_dry_run(self, mock_run, mock_which):
        mock_run.return_value = _mock_run(FAKE_LOG)
        from mempalace.mcp_server import tool_git_mine

        result = tool_git_mine(repo_dir="/fake/repo", all_commits=True, dry_run=True)
        assert result["dry_run"] is True
        assert result["total"] == 3
        assert all("title" in e for e in result["entries"])

    def test_mcp_tool_in_tools_registry(self):
        from mempalace.mcp_server import TOOLS

        assert "mempalace_git_mine" in TOOLS
        schema = TOOLS["mempalace_git_mine"]["input_schema"]
        assert "repo_dir" in schema["required"]
        assert "repo_dir" in schema["properties"]
        assert "dry_run" in schema["properties"]
