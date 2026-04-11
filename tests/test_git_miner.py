"""
tests/test_git_miner.py — Tests for mempalace.git_miner.

All tests mock subprocess.run so they require no git binary, no gh CLI,
and no network access.
"""

import shutil
import subprocess
import tempfile
from unittest.mock import MagicMock, patch

import chromadb
import pytest

from mempalace.git_miner import (
    DEFAULT_ROOM,
    DIFF_SUMMARY_ALWAYS,
    DIFF_SUMMARY_FALLBACK,
    DIFF_SUMMARY_NEVER,
    _FALLBACK_WING,
    _build_pr_body,
    _default_wing,
    _parse_diff_summary,
    GitEntry,
    _DECISION_RE,
    collect_commits,
    collect_entries,
    collect_prs,
    mine_git,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

LOG_SEP = "\x00"


def _make_log_output(*records):
    """Build a fake ``git log`` stdout from (sha, author, date, subject, body) tuples."""
    parts = []
    for sha, author, date, subject, body in records:
        parts.append(f"{sha}|{author}|{date}|{subject}|{body}")
    return LOG_SEP + LOG_SEP.join(parts) + LOG_SEP


FAKE_LOG = _make_log_output(
    ("abc123def456" + "a" * 28, "Alice", "2026-01-01T00:00:00Z", "refactor: extract auth module", ""),
    (
        "111222333444" + "b" * 28,
        "Bob",
        "2026-01-02T00:00:00Z",
        "feat: add rate limiter",
        "Decided to use token bucket instead of leaky bucket because it handles burst traffic better.",
    ),
    ("deadbeefcafe" + "c" * 28, "Carol", "2026-01-03T00:00:00Z", "chore: bump deps", ""),
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

# PR detail response: reviews + commits (commits are used to populate pr_shas)
FAKE_PR_DETAIL_42 = """{
  "reviews": [
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
  ],
  "commits": [
    {"oid": "abc123def456aaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
    {"oid": "deadbeefcafecccccccccccccccccccccccccccc"}
  ]
}"""

FAKE_PR_DETAIL_43 = '{"reviews": [], "commits": []}'

# Fake GitHub REST API /pulls/{n}/files response with patch text including
# hunk context so we can test diff summary extraction.
FAKE_PR_FILES_42 = """[
  {
    "filename": "mempalace/cli.py",
    "status": "modified",
    "additions": 62,
    "deletions": 0,
    "patch": "@@ -98,6 +98,26 @@ def cmd_mine(args):\\n+new line\\n @@ -552,6 +572,47 @@ def main():\\n+other"
  },
  {
    "filename": "mempalace/git_miner.py",
    "status": "added",
    "additions": 467,
    "deletions": 0,
    "patch": "@@ -0,0 +1,467 @@"
  }
]"""

FAKE_PR_FILES_43 = "[]"


def _mock_run(stdout="", returncode=0):
    m = MagicMock()
    m.stdout = stdout
    m.returncode = returncode
    return m


# ── _default_wing ─────────────────────────────────────────────────────────────


class TestDefaultWing:
    def test_derives_from_repo_name(self):
        assert _default_wing("/path/to/mempalace") == "mempalace"

    def test_lowercases_name(self):
        assert _default_wing("/path/to/MyProject") == "myproject"

    def test_replaces_hyphens(self):
        assert _default_wing("/path/to/my-repo") == "my_repo"

    def test_replaces_spaces(self):
        assert _default_wing("/path/to/my repo") == "my_repo"

    def test_fallback_on_invalid_name(self):
        # A repo directory starting with '_' fails sanitize_name → fallback
        assert _default_wing("/path/to/_hidden") == _FALLBACK_WING


# ── _parse_diff_summary ────────────────────────────────────────────────────────


class TestParseDiffSummary:
    def test_empty_returns_empty(self):
        assert _parse_diff_summary([]) == ""
        assert _parse_diff_summary(None) == ""

    def test_no_hunk_context(self):
        files = [{"filename": "go.sum", "status": "modified", "additions": 10, "deletions": 5, "patch": ""}]
        result = _parse_diff_summary(files)
        assert "go.sum" in result
        assert "modified" in result
        assert "+10" in result
        assert "-5" in result
        assert "→" not in result

    def test_extracts_hunk_context(self):
        patch = "@@ -98,6 +98,26 @@ def cmd_mine(args):\n+new\n@@ -200,3 +220,5 @@ def main():\n+other"
        files = [{"filename": "cli.py", "status": "modified", "additions": 28, "deletions": 0, "patch": patch}]
        result = _parse_diff_summary(files)
        assert "→" in result
        assert "def cmd_mine(args):" in result
        assert "def main():" in result

    def test_deduplicates_context(self):
        patch = "@@ -10,3 +10,5 @@ def foo():\n+x\n@@ -20,3 +22,5 @@ def foo():\n+y"
        files = [{"filename": "a.py", "status": "modified", "additions": 2, "deletions": 0, "patch": patch}]
        result = _parse_diff_summary(files)
        assert result.count("def foo():") == 1

    def test_new_file_no_context(self):
        files = [{"filename": "new.py", "status": "added", "additions": 120, "deletions": 0, "patch": "@@ -0,0 +1,120 @@"}]
        result = _parse_diff_summary(files)
        assert "new.py" in result
        assert "added" in result
        assert "+120" in result

    def test_multiple_files_one_line_each(self):
        files = [
            {"filename": "a.py", "status": "modified", "additions": 5, "deletions": 2, "patch": ""},
            {"filename": "b.py", "status": "added", "additions": 10, "deletions": 0, "patch": ""},
        ]
        lines = _parse_diff_summary(files).splitlines()
        assert len(lines) == 2


# ── _build_pr_body ─────────────────────────────────────────────────────────────


class TestBuildPRBody:
    def test_no_reviews_no_diff(self):
        assert _build_pr_body("description", [], "") == "description"

    def test_reviews_folded_in(self):
        reviews = [
            {"author": "alice", "body": "Looks good."},
            {"author": "bob", "body": "Why not gRPC?"},
        ]
        body = _build_pr_body("Switch to gRPC.", reviews, "")
        assert "Switch to gRPC." in body
        assert "--- Review threads ---" in body
        assert "[alice] Looks good." in body
        assert "[bob] Why not gRPC?" in body

    def test_diff_summary_appended(self):
        summary = "  cli.py  modified  +5"
        body = _build_pr_body("desc", [], summary)
        assert "--- Code changes ---" in body
        assert "cli.py" in body

    def test_all_three_sections_in_order(self):
        reviews = [{"author": "x", "body": "LGTM"}]
        summary = "  a.py  modified  +1"
        body = _build_pr_body("desc", reviews, summary)
        desc_idx = body.index("desc")
        review_idx = body.index("--- Review threads ---")
        code_idx = body.index("--- Code changes ---")
        assert desc_idx < review_idx < code_idx

    def test_empty_pr_body_with_reviews(self):
        reviews = [{"author": "carol", "body": "LGTM"}]
        body = _build_pr_body("", reviews, "")
        assert not body.startswith("\n"), "should not start with newline when PR body is empty"
        assert "[carol] LGTM" in body

    def test_diff_only_no_description(self):
        summary = "  main.py  modified  +5"
        body = _build_pr_body("", [], summary)
        assert not body.startswith("\n")
        assert "--- Code changes ---" in body


# ── GitEntry ───────────────────────────────────────────────────────────────────


class TestGitEntry:
    def test_format_commit(self):
        e = GitEntry("commit", "abc123", "fix: auth bug", "Body text", "Alice", "2026-01-01")
        text = e.format()
        assert "COMMIT abc123" in text
        assert "Subject: fix: auth bug" in text
        assert "Body text" in text

    def test_format_pr_with_reviews_folded(self):
        body = "Switch to gRPC.\n\n--- Review threads ---\n[alice] LGTM"
        e = GitEntry("pr", "42", "feat: add gRPC", body, "bob", "2026-01-01")
        text = e.format()
        assert "PR #42" in text
        assert "Title: feat: add gRPC" in text
        assert "--- Review threads ---" in text
        assert "[alice] LGTM" in text

    def test_format_no_body(self):
        e = GitEntry("commit", "abc", "subject only", "", "Alice", "2026-01-01")
        text = e.format()
        assert "subject only" in text
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
        assert entries[0].ref == "abc123def456"
        assert entries[0].title == "refactor: extract auth module"
        assert entries[1].body.startswith("Decided")

    @patch("subprocess.run")
    def test_git_sha_populated(self, mock_run):
        mock_run.return_value = _mock_run(FAKE_LOG)
        entries = collect_commits("/fake/repo", include_all=True)
        for e in entries:
            assert len(e.git_sha) == 40, f"expected 40-char SHA, got {e.git_sha!r}"

    @patch("subprocess.run")
    def test_filters_trivial_commits_by_default(self, mock_run):
        mock_run.return_value = _mock_run(FAKE_LOG)
        entries = collect_commits("/fake/repo", include_all=False)
        titles = [e.title for e in entries]
        assert "chore: bump deps" not in titles
        assert "feat: add rate limiter" in titles

    @patch("subprocess.run")
    def test_pr_shas_excluded(self, mock_run):
        mock_run.return_value = _mock_run(FAKE_LOG)
        # Exclude the first commit's SHA
        sha = "abc123def456" + "a" * 28
        entries = collect_commits("/fake/repo", include_all=True, pr_shas={sha})
        refs = [e.ref for e in entries]
        assert "abc123def456" not in refs

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
        prs, pr_shas = collect_prs("/fake/repo")
        assert prs == []
        assert pr_shas == set()

    @patch("shutil.which", return_value="/usr/bin/gh")
    @patch("subprocess.run")
    def test_parses_prs(self, mock_run, mock_which):
        mock_run.side_effect = [
            _mock_run(FAKE_PR_LIST),
            _mock_run(FAKE_PR_DETAIL_42),
            _mock_run(FAKE_PR_DETAIL_43),
        ]
        prs, _ = collect_prs("/fake/repo", diff_summary=DIFF_SUMMARY_NEVER)
        assert len(prs) == 2
        assert prs[0].ref == "42"
        assert prs[0].title == "feat: switch to gRPC instead of REST"
        assert prs[0].author == "alice"

    @patch("shutil.which", return_value="/usr/bin/gh")
    @patch("subprocess.run")
    def test_reviews_folded_into_pr_body(self, mock_run, mock_which):
        mock_run.side_effect = [
            _mock_run(FAKE_PR_LIST),
            _mock_run(FAKE_PR_DETAIL_42),
            _mock_run(FAKE_PR_DETAIL_43),
        ]
        prs, _ = collect_prs("/fake/repo", diff_summary=DIFF_SUMMARY_NEVER)
        assert "--- Review threads ---" in prs[0].body
        assert "[carol]" in prs[0].body
        assert "gRPC" in prs[0].body
        assert "[dan]" not in prs[0].body

    @patch("shutil.which", return_value="/usr/bin/gh")
    @patch("subprocess.run")
    def test_no_review_source_entries(self, mock_run, mock_which):
        """collect_prs must never return entries with source=='review'."""
        mock_run.side_effect = [
            _mock_run(FAKE_PR_LIST),
            _mock_run(FAKE_PR_DETAIL_42),
            _mock_run(FAKE_PR_DETAIL_43),
        ]
        prs, _ = collect_prs("/fake/repo", diff_summary=DIFF_SUMMARY_NEVER)
        assert all(e.source == "pr" for e in prs)

    @patch("shutil.which", return_value="/usr/bin/gh")
    @patch("subprocess.run")
    def test_pr_shas_populated(self, mock_run, mock_which):
        """pr_shas should contain commit OIDs from the fetched PR detail."""
        mock_run.side_effect = [
            _mock_run(FAKE_PR_LIST),
            _mock_run(FAKE_PR_DETAIL_42),
            _mock_run(FAKE_PR_DETAIL_43),
        ]
        _, pr_shas = collect_prs("/fake/repo", diff_summary=DIFF_SUMMARY_NEVER)
        assert "abc123def456" + "a" * 28 in pr_shas
        assert "deadbeefcafe" + "c" * 28 in pr_shas

    @patch("shutil.which", return_value="/usr/bin/gh")
    @patch("subprocess.run")
    def test_no_reviews_flag_skips_detail_fetch(self, mock_run, mock_which):
        # no_reviews=True AND diff_summary=never → only pr list call
        mock_run.return_value = _mock_run(FAKE_PR_LIST)
        prs, pr_shas = collect_prs("/fake/repo", no_reviews=True, diff_summary=DIFF_SUMMARY_NEVER)
        assert mock_run.call_count == 1
        assert pr_shas == set()

    @patch("shutil.which", return_value="/usr/bin/gh")
    @patch("subprocess.run")
    def test_gh_failure_returns_empty(self, mock_run, mock_which):
        mock_run.side_effect = subprocess.CalledProcessError(1, "gh", stderr=b"auth error")
        prs, pr_shas = collect_prs("/fake/repo")
        assert prs == []
        assert pr_shas == set()

    @patch("shutil.which", return_value="/usr/bin/gh")
    @patch("subprocess.run")
    def test_max_prs_limit_passed_to_gh(self, mock_run, mock_which):
        mock_run.side_effect = [_mock_run("[]")]
        collect_prs("/fake/repo", max_prs=10, diff_summary=DIFF_SUMMARY_NEVER)
        args = mock_run.call_args[0][0]
        assert "10" in args

    @patch("shutil.which", return_value="/usr/bin/gh")
    @patch("subprocess.run")
    def test_diff_summary_always_fetches_files(self, mock_run, mock_which):
        """diff_summary=always calls gh api /files for each PR."""
        mock_run.side_effect = [
            _mock_run(FAKE_PR_LIST),          # pr list
            _mock_run(FAKE_PR_DETAIL_42),     # pr view 42
            _mock_run(FAKE_PR_FILES_42),      # gh api files 42
            _mock_run(FAKE_PR_DETAIL_43),     # pr view 43
            _mock_run(FAKE_PR_FILES_43),      # gh api files 43
        ]
        prs, _ = collect_prs("/fake/repo", diff_summary=DIFF_SUMMARY_ALWAYS)
        assert "--- Code changes ---" in prs[0].body
        assert "mempalace/cli.py" in prs[0].body
        # PR 43 has empty body (short) — diff summary present but files empty
        assert "--- Code changes ---" not in prs[1].body

    @patch("shutil.which", return_value="/usr/bin/gh")
    @patch("subprocess.run")
    def test_diff_summary_fallback_only_when_no_body(self, mock_run, mock_which):
        """diff_summary=fallback: only fetch files for PR 43 (empty body)."""
        mock_run.side_effect = [
            _mock_run(FAKE_PR_LIST),          # pr list
            _mock_run(FAKE_PR_DETAIL_42),     # pr view 42 (has body — no files fetch)
            _mock_run(FAKE_PR_DETAIL_43),     # pr view 43 (no body — files fetch)
            _mock_run(FAKE_PR_FILES_43),      # gh api files 43
        ]
        prs, _ = collect_prs("/fake/repo", diff_summary=DIFF_SUMMARY_FALLBACK)
        # PR 42 has a description → no diff appended
        assert "--- Code changes ---" not in prs[0].body
        # PR 43 has no description → diff appended (but files fixture is empty)
        # (No code-changes block because FAKE_PR_FILES_43 = "[]")

    @patch("shutil.which", return_value="/usr/bin/gh")
    @patch("subprocess.run")
    def test_diff_summary_never_skips_files(self, mock_run, mock_which):
        """diff_summary=never: no gh api /files calls."""
        mock_run.side_effect = [
            _mock_run(FAKE_PR_LIST),
            _mock_run(FAKE_PR_DETAIL_42),
            _mock_run(FAKE_PR_DETAIL_43),
        ]
        prs, _ = collect_prs("/fake/repo", diff_summary=DIFF_SUMMARY_NEVER)
        assert "--- Code changes ---" not in prs[0].body
        assert "--- Code changes ---" not in prs[1].body
        assert mock_run.call_count == 3  # list + 2x pr view, no files calls


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
    def test_only_commit_and_pr_sources(self, mock_run, mock_which):
        mock_run.return_value = _mock_run(FAKE_LOG)
        entries = collect_entries("/fake/repo", include_all=True)
        for e in entries:
            assert e.source in ("commit", "pr"), f"Unexpected source: {e.source!r}"

    @patch("shutil.which", return_value="/usr/bin/gh")
    @patch("subprocess.run")
    def test_pr_commits_excluded_from_commit_entries(self, mock_run, mock_which):
        """Commits that belong to a fetched PR must not appear as separate drawers."""
        mock_run.side_effect = [
            _mock_run(FAKE_PR_LIST),
            _mock_run(FAKE_PR_DETAIL_42),
            _mock_run(FAKE_PR_DETAIL_43),
            _mock_run(FAKE_LOG),
        ]
        entries = collect_entries("/fake/repo", include_all=True, diff_summary=DIFF_SUMMARY_NEVER)
        commit_refs = [e.ref for e in entries if e.source == "commit"]
        assert "abc123def456" not in commit_refs
        assert "deadbeefcafe" not in commit_refs
        assert "111222333444" in commit_refs


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
            import os
            assert not os.path.exists(os.path.join(tmpdir, "chroma.sqlite3"))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @patch("shutil.which", return_value=None)
    @patch("subprocess.run")
    def test_idempotent_upsert(self, mock_run, mock_which):
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
            expected_wing = _default_wing("/fake/repo")
            assert all(m["wing"] == expected_wing for m in metas)
            assert all(m["room"] == DEFAULT_ROOM for m in metas)
            assert result["wing"] == expected_wing
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
        tmpdir2 = tempfile.mkdtemp()
        try:
            result_all = mine_git("/fake/repo", tmpdir, include_all=True)
            result_dec = mine_git("/fake/repo", tmpdir2, include_all=True, decision_only=True)
            assert result_dec["filed"] <= result_all["filed"]
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
            shutil.rmtree(tmpdir2, ignore_errors=True)

    @patch("shutil.which", return_value=None)
    @patch("subprocess.run")
    def test_no_reviews_key_in_result(self, mock_run, mock_which):
        """result dict must not contain 'reviews' — that field was removed."""
        mock_run.return_value = _mock_run(FAKE_LOG)
        tmpdir = tempfile.mkdtemp()
        try:
            result = mine_git("/fake/repo", tmpdir, include_all=True)
            assert "reviews" not in result
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


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
                from mempalace.mcp_server import tool_git_mine
                result = tool_git_mine(repo_dir="/fake/repo", all_commits=True)
            assert result["success"] is True
            assert result["drawers_filed"] == 3
            assert "reviews_scanned" not in result

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
