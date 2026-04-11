#!/usr/bin/env python3
"""
git_miner.py — Mine git commit history and GitHub PR data into the palace.

Structure produced:

    wing: <repo-name>  (derived from repo directory base name)
      room: git-decisions
        drawer: one per merged PR — title + body + review threads + diff summary
        drawer: one per commit not associated with any fetched PR

Callers can override wing and room via CLI flags or the MCP tool parameters.
Commit mining requires only ``git``; PR and review mining requires ``gh``
(https://cli.github.com) to be installed and authenticated.
"""

import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .palace import get_collection
from .config import sanitize_name, sanitize_content


# ── Constants ──────────────────────────────────────────────────────────────────

_FALLBACK_WING = "wing_code"
DEFAULT_ROOM = "git-decisions"

# NUL byte as record separator — cannot appear in git commit messages.
_LOG_SEP = "\x00"

# Keywords that signal a decision, rationale, or architectural choice.
_DECISION_RE = re.compile(
    r"\b(decided|because|instead of|rather than|trade-?off|"
    r"approach|strategy|architecture|chose|went with|"
    r"over\b.{0,40}\bbecause|"
    r"migrate|refactor|deprecat|introduced|removed|replaced|switched)\b",
    re.IGNORECASE,
)

# Diff summary modes.
DIFF_SUMMARY_ALWAYS = "always"
DIFF_SUMMARY_FALLBACK = "fallback"
DIFF_SUMMARY_NEVER = "never"

# Hunk header context regex — extracts the function/method name from a unified
# diff @@ header line, e.g.: @@ -98,6 +98,26 @@ def cmd_mine(args):
_HUNK_CONTEXT_RE = re.compile(r"^@@[^@]*@@\s*(.+)$")

# Minimum PR body length (non-whitespace chars) to be considered "has a description"
# for the "fallback" mode.
_BODY_MIN_LEN = 30

MAX_FILE_SIZE = 10 * 1024 * 1024  # not used for git, kept for parity


# ── Wing derivation ────────────────────────────────────────────────────────────


def _default_wing(repo_dir: str) -> str:
    """Derive a wing name from the repository directory name.

    Lower-cases the directory name and replaces spaces and hyphens with
    underscores, mirroring convo_miner.py.  Falls back to ``wing_code`` if the
    result fails ``sanitize_name`` validation.
    """
    name = Path(repo_dir).resolve().name.lower().replace(" ", "_").replace("-", "_")
    try:
        return sanitize_name(name, "wing")
    except ValueError:
        return _FALLBACK_WING


# ── Diff summary ───────────────────────────────────────────────────────────────


def _parse_diff_summary(files: list) -> str:
    """Convert a list of PR file dicts (from the GitHub REST API) into a
    compact, human-readable summary of what changed.

    Example output::

        mempalace/cli.py        modified  +62    → cmd_mine, main
        mempalace/git_miner.py  added     +467
        tests/test_git_miner.py added     +426

    Function context is extracted from unified diff hunk headers when present.
    No raw diff content is stored.

    Args:
        files: List of dicts with keys ``filename``, ``status``,
               ``additions``, ``deletions``, and optionally ``patch``.
    """
    if not files:
        return ""

    lines = []
    for f in files:
        filename = f.get("filename", "")
        status = f.get("status", "")
        additions = f.get("additions", 0)
        deletions = f.get("deletions", 0)
        patch = f.get("patch", "") or ""

        # Collect unique function/method names from hunk headers, preserving order.
        seen_ctx: set = set()
        ctx_list: list = []
        for line in patch.splitlines():
            m = _HUNK_CONTEXT_RE.match(line.strip())
            if m:
                ctx = m.group(1).strip()
                if ctx and ctx not in seen_ctx:
                    seen_ctx.add(ctx)
                    ctx_list.append(ctx)

        stat = f"+{additions}"
        if deletions:
            stat += f" -{deletions}"

        line = f"  {filename:<45}  {status:<8}  {stat}"
        if ctx_list:
            line += "   → " + ", ".join(ctx_list)
        lines.append(line)

    return "\n".join(lines)


def _fetch_pr_files(repo_dir: str, pr_number: int) -> list:
    """Fetch changed file metadata for a PR via ``gh api``.

    Uses the GitHub REST endpoint which includes the ``patch`` field (unified
    diff text) needed to extract hunk context. Returns an empty list on any
    error so callers can degrade gracefully.

    Args:
        repo_dir: Path to the git repository root.
        pr_number: PR number to fetch files for.
    """
    try:
        raw = subprocess.run(
            [
                "gh", "api",
                f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/files",
                "--paginate",
            ],
            cwd=repo_dir,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            check=True,
        )
        return json.loads(raw.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return []


# ── Public data class ──────────────────────────────────────────────────────────


class GitEntry:
    """One mined piece of content — a merged PR (with reviews folded in) or a
    standalone commit not covered by any fetched PR."""

    __slots__ = ("source", "ref", "title", "body", "author", "date", "git_sha")

    def __init__(
        self,
        source: str,
        ref: str,
        title: str,
        body: str,
        author: str,
        date: str,
        git_sha: str = "",
    ):
        self.source = source   # "commit" | "pr"
        self.ref = ref         # short SHA or PR number string
        self.title = title
        self.body = body
        self.author = author
        self.date = date
        self.git_sha = git_sha  # full 40-char SHA for commits; "" for PRs

    def has_decision_signal(self) -> bool:
        return bool(_DECISION_RE.search(self.title) or _DECISION_RE.search(self.body))

    def format(self) -> str:
        """Produce the verbatim text stored in a drawer."""
        lines = []
        if self.source == "commit":
            lines.append(f"COMMIT {self.ref} | {self.author} | {self.date}")
            lines.append(f"Subject: {self.title}")
        else:  # pr
            lines.append(f"PR #{self.ref} | {self.author} | {self.date}")
            lines.append(f"Title: {self.title}")
        text = "\n".join(lines) + "\n"
        if self.body:
            text += f"\n{self.body}\n"
        return text

    def drawer_id(self, wing: str, room: str) -> str:
        """Content-addressed, deterministic drawer ID — idempotent upserts."""
        key = wing + room + self.source + self.ref + self.title
        return f"drawer_{wing}_{room}_git_{hashlib.sha256(key.encode()).hexdigest()[:24]}"


# ── git log ────────────────────────────────────────────────────────────────────


def collect_commits(
    repo_dir: str,
    max_commits: int = 0,
    since: str = "",
    include_all: bool = False,
    pr_shas: set = None,
) -> list:
    """Return GitEntry objects parsed from ``git log``, skipping any commit
    whose full SHA appears in *pr_shas* (already covered by a PR drawer).

    Args:
        repo_dir: Path to the git repository root.
        max_commits: Cap on commits returned (0 = all).
        since: Only include commits after this date string.
        include_all: If ``False``, skip commits with no body and no signal.
        pr_shas: Set of full commit SHAs that belong to fetched PRs.
    """
    if pr_shas is None:
        pr_shas = set()

    fmt = "--pretty=format:%x00%H|%an|%aI|%s|%b%x00"
    args = ["git", "log", fmt, "--no-merges"]
    if since:
        args.append(f"--since={since}")
    if max_commits > 0:
        args.append(f"-n{max_commits}")

    try:
        result = subprocess.run(
            args,
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise RuntimeError(f"git log failed in {repo_dir}: {exc}") from exc

    entries = []
    for block in result.stdout.split(_LOG_SEP):
        block = block.strip()
        if not block:
            continue
        parts = block.split("|", 4)
        if len(parts) < 4:
            continue
        sha = parts[0].strip()
        author = parts[1].strip()
        date = parts[2].strip()
        subject = parts[3].strip()
        body = parts[4].strip() if len(parts) == 5 else ""
        if not sha or not subject:
            continue

        # Skip commits already covered by a fetched PR.
        if sha in pr_shas:
            continue

        entry = GitEntry(
            source="commit",
            ref=sha[:12] if len(sha) >= 12 else sha,
            title=subject,
            body=body,
            author=author,
            date=date,
            git_sha=sha,
        )
        if not include_all and not body and not entry.has_decision_signal():
            continue
        entries.append(entry)

    return entries


# ── gh PRs ─────────────────────────────────────────────────────────────────────


def _gh_available() -> bool:
    return shutil.which("gh") is not None


def collect_prs(
    repo_dir: str,
    max_prs: int = 25,
    no_reviews: bool = False,
    diff_summary: str = DIFF_SUMMARY_ALWAYS,
) -> tuple:
    """Return ``(pr_entries, pr_shas)`` fetched via ``gh``.

    Each PR entry has its review threads and diff summary folded into ``body``
    according to *diff_summary* mode.
    *pr_shas* is a set of full commit SHAs belonging to the fetched PRs so
    that ``collect_commits`` can skip them.

    Returns empty list and empty set (with a warning) when ``gh`` is
    unavailable or not authenticated.

    Args:
        repo_dir: Path to the git repository root.
        max_prs: Maximum number of merged PRs to fetch (default 25).
        no_reviews: Skip folding review threads into PR bodies.
        diff_summary: When to append the structured diff summary:
            ``"always"`` (default), ``"fallback"`` (only when PR body is
            absent/short), or ``"never"``.
    """
    pr_shas: set = set()

    if not _gh_available():
        print(
            "  [git-mine] gh CLI not found — skipping PR mining. "
            "Install from https://cli.github.com to enable PR indexing.",
            file=sys.stderr,
        )
        return [], pr_shas

    limit = max_prs if max_prs > 0 else 25

    try:
        raw = subprocess.run(
            [
                "gh", "pr", "list",
                "--state", "merged",
                "--limit", str(limit),
                "--json", "number,title,body,author,createdAt",
            ],
            cwd=repo_dir,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        print(
            f"  [git-mine] gh pr list failed — skipping PR mining: {exc.stderr.strip()!r}",
            file=sys.stderr,
        )
        return [], pr_shas

    try:
        prs = json.loads(raw.stdout)
    except json.JSONDecodeError:
        return [], pr_shas

    pr_entries = []

    for pr in prs:
        pr_body = (pr.get("body") or "").strip()
        reviews = []

        if not no_reviews:
            reviews, commit_shas = _fetch_pr_detail(repo_dir, pr["number"])
            pr_shas.update(commit_shas)

        # Fetch diff summary according to mode.
        summary = ""
        if diff_summary != DIFF_SUMMARY_NEVER:
            body_is_short = len(pr_body.strip()) < _BODY_MIN_LEN
            if diff_summary == DIFF_SUMMARY_ALWAYS or (diff_summary == DIFF_SUMMARY_FALLBACK and body_is_short):
                files = _fetch_pr_files(repo_dir, pr["number"])
                summary = _parse_diff_summary(files)

        pr_entries.append(
            GitEntry(
                source="pr",
                ref=str(pr["number"]),
                title=pr.get("title", ""),
                body=_build_pr_body(pr_body, reviews, summary),
                author=(pr.get("author") or {}).get("login", ""),
                date=pr.get("createdAt", ""),
            )
        )

    return pr_entries, pr_shas


def _fetch_pr_detail(repo_dir: str, pr_number: int) -> tuple:
    """Fetch review threads and commit SHAs for one PR.

    Returns ``(reviews, commit_shas)`` where *reviews* is a list of
    ``{"author": str, "body": str}`` dicts and *commit_shas* is a set of
    full SHA strings.
    """
    try:
        raw = subprocess.run(
            [
                "gh", "pr", "view", str(pr_number),
                "--json", "reviews,commits",
            ],
            cwd=repo_dir,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            check=True,
        )
        detail = json.loads(raw.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return [], set()

    reviews = []
    for rev in detail.get("reviews", []):
        body = (rev.get("body") or "").strip()
        if body:
            reviews.append({
                "author": (rev.get("author") or {}).get("login", ""),
                "body": body,
            })

    commit_shas = {
        c["oid"] for c in detail.get("commits", []) if c.get("oid")
    }

    return reviews, commit_shas


def _build_pr_body(pr_body: str, reviews: list, diff_summary: str = "") -> str:
    """Assemble the final drawer body for a PR.

    Sections (each omitted when empty):

    1. PR description
    2. ``--- Review threads ---`` block
    3. ``--- Code changes ---`` block
    """
    parts = []
    if pr_body:
        parts.append(pr_body)

    if reviews:
        review_lines = ["\n--- Review threads ---"]
        for rev in reviews:
            review_lines.append(f"[{rev['author']}] {rev['body']}")
        parts.append("\n".join(review_lines))

    if diff_summary:
        parts.append(f"\n--- Code changes ---\n{diff_summary}")

    return "\n".join(parts).strip()


# ── Core pipeline ──────────────────────────────────────────────────────────────


def collect_entries(
    repo_dir: str,
    max_commits: int = 0,
    max_prs: int = 25,
    since: str = "",
    include_all: bool = False,
    no_reviews: bool = False,
    decision_only: bool = False,
    diff_summary: str = DIFF_SUMMARY_ALWAYS,
) -> list:
    """Collect all git entries without writing to the palace.

    PRs (with reviews and diff summary folded in) are collected first; commits
    that belong to those PRs are then excluded from the commit scan.

    Useful for dry-run previews and testing.
    """
    pr_entries, pr_shas = collect_prs(
        repo_dir, max_prs=max_prs, no_reviews=no_reviews, diff_summary=diff_summary
    )
    commit_entries = collect_commits(
        repo_dir,
        max_commits=max_commits,
        since=since,
        include_all=include_all,
        pr_shas=pr_shas,
    )
    entries = pr_entries + commit_entries

    if decision_only:
        entries = [e for e in entries if e.has_decision_signal()]

    return entries


def mine_git(
    repo_dir: str,
    palace_path: str,
    wing: str = None,
    room: str = DEFAULT_ROOM,
    agent: str = "git-mine",
    max_commits: int = 0,
    max_prs: int = 25,
    since: str = "",
    include_all: bool = False,
    no_reviews: bool = False,
    decision_only: bool = False,
    dry_run: bool = False,
    diff_summary: str = DIFF_SUMMARY_ALWAYS,
) -> dict:
    """Mine a git repository and file entries into the palace.

    Args:
        repo_dir: Path to the git repository root.
        palace_path: Path to the ChromaDB palace directory.
        wing: Wing to file into. Defaults to the repository directory name
            (e.g. ``mempalace`` for ``/path/to/mempalace``), falling back to
            ``wing_code`` if the name cannot be sanitized.
        room: Room to file into (default: ``git-decisions``).
        agent: Agent name recorded in drawer metadata.
        max_commits: Cap on commits (0 = all).
        max_prs: Cap on PRs fetched via gh (default 25).
        since: Only include commits after this date (e.g. ``"2025-01-01"``).
        include_all: Include commits with no body and no decision signal.
        no_reviews: Skip folding review threads into PR drawers.
        decision_only: Only file entries matching decision-signal keywords.
        dry_run: Print entries without writing to the palace.
        diff_summary: When to append structured diff summary to PR drawers:
            ``"always"`` (default), ``"fallback"`` (only when no description),
            or ``"never"``.
        dry_run: Print entries without writing to the palace.

    Returns:
        A dict with keys ``commits``, ``prs``, ``filed``, ``errors``, ``wing``.
    """
    repo_path = str(Path(repo_dir).expanduser().resolve())
    resolved_wing = wing if wing is not None else _default_wing(repo_path)
    try:
        resolved_wing = sanitize_name(resolved_wing, "wing")
        room = sanitize_name(room, "room")
    except ValueError as exc:
        return {"error": str(exc)}

    entries = collect_entries(
        repo_path,
        max_commits=max_commits,
        max_prs=max_prs,
        since=since,
        include_all=include_all,
        no_reviews=no_reviews,
        decision_only=decision_only,
        diff_summary=diff_summary,
    )

    prs = sum(1 for e in entries if e.source == "pr")
    commits = sum(1 for e in entries if e.source == "commit")

    _print_header(repo_path, resolved_wing, room, len(entries), dry_run)

    if dry_run:
        for i, entry in enumerate(entries, 1):
            print(f"  [{i:4}] {entry.source.upper():6} {entry.ref:12} {entry.author:20} {entry.title[:55]}")
        print(f"\n  Total: {len(entries)} entries (not written)")
        _print_footer(resolved_wing)
        return {"commits": commits, "prs": prs, "filed": 0, "errors": [], "wing": resolved_wing}

    collection = get_collection(palace_path)
    filed = 0
    errors = []

    for entry in entries:
        content = entry.format()
        try:
            content = sanitize_content(content)
        except ValueError as exc:
            print(
                f"  [git-mine] skipping {entry.source} {entry.ref} — content rejected by sanitize_content: {exc}",
                file=sys.stderr,
            )
            continue

        drawer_id = entry.drawer_id(resolved_wing, room)
        metadata: dict = {
            "wing": resolved_wing,
            "room": room,
            "source_file": f"{entry.source}:{entry.ref}",
            "chunk_index": 0,
            "added_by": agent,
            "filed_at": datetime.now(timezone.utc).isoformat(),
            "ingest_mode": "git-mine",
        }
        if entry.git_sha:
            metadata["git_sha"] = entry.git_sha
        try:
            collection.upsert(
                ids=[drawer_id],
                documents=[content],
                metadatas=[metadata],
            )
            filed += 1
        except Exception as exc:
            errors.append(f"{entry.source} {entry.ref}: {exc}")

    _print_results(commits, prs, filed, resolved_wing, room, errors)
    return {"commits": commits, "prs": prs, "filed": filed, "errors": errors, "wing": resolved_wing}


# ── Output helpers ─────────────────────────────────────────────────────────────


def _print_header(repo_path: str, wing: str, room: str, total: int, dry_run: bool) -> None:
    print(f"\n{'=' * 55}")
    print("  MemPalace Git-Mine" + (" — Dry Run" if dry_run else ""))
    print(f"{'=' * 55}")
    print(f"  Repo:    {repo_path}")
    print(f"  Wing:    {wing}")
    print(f"  Room:    {room}")
    print(f"  Entries: {total}")
    if dry_run:
        print("  DRY RUN — nothing will be filed")
    print(f"{'-' * 55}\n")


def _print_results(
    commits: int, prs: int, filed: int, wing: str, room: str, errors: list
) -> None:
    print(f"\n{'=' * 55}")
    print(f"  Commits scanned:  {commits}")
    print(f"  PRs scanned:      {prs}")
    print(f"  Drawers filed:    {filed}")
    print(f"  Destination:      {wing} / {room}")
    if errors:
        print("\n  Warnings:")
        for err in errors:
            print(f"    - {err}")
    print(f'\n  Next: mempalace search "architecture decision" --wing {wing}')
    print(f"{'=' * 55}\n")


def _print_footer(wing: str) -> None:
    print(f"\n  Next: mempalace search \"architecture decision\" --wing {wing}")
    print(f"{'=' * 55}\n")


# ── CLI entry point ────────────────────────────────────────────────────────────


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Mine git history into the palace.")
    parser.add_argument("repo_dir", help="Path to the git repository root")
    parser.add_argument("--palace", default=None, help="Palace directory path")
    parser.add_argument("--wing", default=None, help="Wing to file into (default: repo directory name)")
    parser.add_argument("--room", default=DEFAULT_ROOM)
    parser.add_argument("--since", default="", help="Only commits after this date")
    parser.add_argument("--max-commits", type=int, default=0)
    parser.add_argument("--max-prs", type=int, default=25)
    parser.add_argument("--no-reviews", action="store_true", help="Skip folding review threads into PR drawers")
    parser.add_argument("--all-commits", action="store_true")
    parser.add_argument("--decision-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from .config import MempalaceConfig

    palace = args.palace or MempalaceConfig().palace_path
    mine_git(
        args.repo_dir,
        palace,
        wing=args.wing,
        room=args.room,
        max_commits=args.max_commits,
        max_prs=args.max_prs,
        since=args.since,
        include_all=args.all_commits,
        no_reviews=args.no_reviews,
        decision_only=args.decision_only,
        dry_run=args.dry_run,
    )
