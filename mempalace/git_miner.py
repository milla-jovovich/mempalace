#!/usr/bin/env python3
"""
git_miner.py — Mine git commit history and GitHub PR data into the palace.

Parses commit messages from ``git log`` (no auth required) and, when the
``gh`` CLI is installed and authenticated, fetches merged PR titles, bodies,
and review threads.

All entries are filed under ``wing_code / git-decisions`` by default.
Commit mining requires only ``git``; PR and review mining requires ``gh``
(https://cli.github.com) to be installed and authenticated.
"""

import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .palace import get_collection
from .config import sanitize_name, sanitize_content


# ── Constants ──────────────────────────────────────────────────────────────────

DEFAULT_WING = "wing_code"
DEFAULT_ROOM = "git-decisions"

# Record separator unlikely to appear in real commit messages.
_LOG_SEP = ">>MP<<"

# Keywords that signal a decision, rationale, or architectural choice.
_DECISION_RE = re.compile(
    r"\b(decided|because|instead of|rather than|trade-?off|"
    r"approach|strategy|architecture|chose|went with|"
    r"migrate|refactor|deprecat|introduced|removed|replaced|switched)\b",
    re.IGNORECASE,
)

MAX_FILE_SIZE = 10 * 1024 * 1024  # not used for git, kept for parity


# ── Public data class ──────────────────────────────────────────────────────────


class GitEntry:
    """One mined piece of content — a commit, PR summary, or review thread."""

    __slots__ = ("source", "ref", "title", "body", "author", "date")

    def __init__(self, source: str, ref: str, title: str, body: str, author: str, date: str):
        self.source = source  # "commit" | "pr" | "review"
        self.ref = ref  # short SHA or PR number string
        self.title = title
        self.body = body
        self.author = author
        self.date = date

    def has_decision_signal(self) -> bool:
        return bool(_DECISION_RE.search(self.title) or _DECISION_RE.search(self.body))

    def format(self) -> str:
        """Produce the verbatim text stored in a drawer."""
        lines = []
        if self.source == "commit":
            lines.append(f"COMMIT {self.ref} | {self.author} | {self.date}")
            lines.append(f"Subject: {self.title}")
        elif self.source == "pr":
            lines.append(f"PR #{self.ref} | {self.author} | {self.date}")
            lines.append(f"Title: {self.title}")
        else:
            lines.append(f"REVIEW {self.ref} | {self.author} | {self.date}")
            lines.append(f"PR: {self.title}")
        if self.body:
            lines.append("")
            lines.append(self.body)
        return "\n".join(lines)

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
) -> list:
    """Return a list of GitEntry objects parsed from ``git log``.

    Args:
        repo_dir: Path to the git repository root.
        max_commits: Cap on commits returned (0 = all).
        since: Only include commits after this date string (e.g. ``"2025-01-01"``).
        include_all: If ``False`` (default), skip commits that have no body and
            no decision signal in the subject.
    """
    fmt = f"--pretty=format:{_LOG_SEP}%H|%an|%aI|%s|%b{_LOG_SEP}"
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
        sha, author, date, subject = parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3].strip()
        body = parts[4].strip() if len(parts) == 5 else ""
        if not sha or not subject:
            continue
        entry = GitEntry(
            source="commit",
            ref=sha[:12],
            title=subject,
            body=body,
            author=author,
            date=date,
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
) -> tuple:
    """Return ``(pr_entries, review_entries)`` fetched via ``gh``.

    Returns empty lists (with a warning printed) when ``gh`` is unavailable or
    not authenticated — PR mining is optional and degrades gracefully.

    Args:
        repo_dir: Path to the git repository root (used as cwd for ``gh``).
        max_prs: Maximum number of merged PRs to fetch (default 25).
        no_reviews: Skip per-PR review thread fetching when ``True``.
    """
    if not _gh_available():
        print(
            "  [git-mine] gh CLI not found — skipping PR mining. "
            "Install from https://cli.github.com to enable PR indexing.",
            file=sys.stderr,
        )
        return [], []

    limit = max(1, max_prs)

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
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        print(
            f"  [git-mine] gh pr list failed — skipping PR mining: {exc.stderr.strip()!r}",
            file=sys.stderr,
        )
        return [], []

    try:
        prs = json.loads(raw.stdout)
    except json.JSONDecodeError:
        return [], []

    pr_entries = []
    review_entries = []

    for pr in prs:
        body = (pr.get("body") or "").strip()
        pr_entries.append(
            GitEntry(
                source="pr",
                ref=str(pr["number"]),
                title=pr.get("title", ""),
                body=body,
                author=(pr.get("author") or {}).get("login", ""),
                date=pr.get("createdAt", ""),
            )
        )

        if not no_reviews:
            review_entries.extend(_fetch_reviews(repo_dir, pr["number"], pr.get("title", "")))

    return pr_entries, review_entries


def _fetch_reviews(repo_dir: str, pr_number: int, pr_title: str) -> list:
    """Fetch non-empty review bodies for one PR."""
    try:
        raw = subprocess.run(
            [
                "gh", "pr", "view", str(pr_number),
                "--json", "reviews",
            ],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        detail = json.loads(raw.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return []

    entries = []
    for i, rev in enumerate(detail.get("reviews", [])):
        body = (rev.get("body") or "").strip()
        if not body:
            continue
        entries.append(
            GitEntry(
                source="review",
                ref=f"{pr_number}.{i}",
                title=f"Review on PR #{pr_number}: {pr_title}",
                body=body,
                author=(rev.get("author") or {}).get("login", ""),
                date=rev.get("createdAt", ""),
            )
        )
    return entries


# ── Core pipeline ──────────────────────────────────────────────────────────────


def collect_entries(
    repo_dir: str,
    max_commits: int = 0,
    max_prs: int = 25,
    since: str = "",
    include_all: bool = False,
    no_reviews: bool = False,
    decision_only: bool = False,
) -> list:
    """Collect all git entries without writing to the palace.

    Useful for dry-run previews and testing.
    """
    entries = collect_commits(repo_dir, max_commits=max_commits, since=since, include_all=include_all)
    pr_entries, review_entries = collect_prs(repo_dir, max_prs=max_prs, no_reviews=no_reviews)
    entries = entries + pr_entries + review_entries

    if decision_only:
        entries = [e for e in entries if e.has_decision_signal()]

    return entries


def mine_git(
    repo_dir: str,
    palace_path: str,
    wing: str = DEFAULT_WING,
    room: str = DEFAULT_ROOM,
    agent: str = "git-mine",
    max_commits: int = 0,
    max_prs: int = 25,
    since: str = "",
    include_all: bool = False,
    no_reviews: bool = False,
    decision_only: bool = False,
    dry_run: bool = False,
) -> dict:
    """Mine a git repository and file entries into the palace.

    Args:
        repo_dir: Path to the git repository root.
        palace_path: Path to the ChromaDB palace directory.
        wing: Wing to file into (default: ``wing_code``).
        room: Room to file into (default: ``git-decisions``).
        agent: Agent name recorded in drawer metadata.
        max_commits: Cap on commits (0 = all).
        max_prs: Cap on PRs fetched via gh (default 25).
        since: Only include commits after this date (e.g. ``"2025-01-01"``).
        include_all: Include commits with no body and no decision signal.
        no_reviews: Skip per-PR review thread fetching.
        decision_only: Only file entries matching decision-signal keywords.
        dry_run: Print entries without writing to the palace.

    Returns:
        A dict with keys ``commits``, ``prs``, ``reviews``, ``filed``, ``errors``.
    """
    try:
        wing = sanitize_name(wing, "wing")
        room = sanitize_name(room, "room")
    except ValueError as exc:
        return {"error": str(exc)}

    repo_path = str(Path(repo_dir).expanduser().resolve())

    entries = collect_entries(
        repo_path,
        max_commits=max_commits,
        max_prs=max_prs,
        since=since,
        include_all=include_all,
        no_reviews=no_reviews,
        decision_only=decision_only,
    )

    commits = sum(1 for e in entries if e.source == "commit")
    prs = sum(1 for e in entries if e.source == "pr")
    reviews = sum(1 for e in entries if e.source == "review")

    _print_header(repo_path, wing, room, len(entries), dry_run)

    if dry_run:
        for i, entry in enumerate(entries, 1):
            print(f"  [{i:4}] {entry.source.upper():6} {entry.ref:12} {entry.author:20} {entry.title[:55]}")
        print(f"\n  Total: {len(entries)} entries (not written)")
        _print_footer(wing)
        return {"commits": commits, "prs": prs, "reviews": reviews, "filed": 0, "errors": []}

    collection = get_collection(palace_path)
    filed = 0
    errors = []
    room_counts = defaultdict(int)

    for entry in entries:
        content = entry.format()
        try:
            content = sanitize_content(content)
        except ValueError:
            continue

        drawer_id = entry.drawer_id(wing, room)
        try:
            collection.upsert(
                ids=[drawer_id],
                documents=[content],
                metadatas=[
                    {
                        "wing": wing,
                        "room": room,
                        "source_file": f"{entry.source}:{entry.ref}",
                        "chunk_index": 0,
                        "added_by": agent,
                        "filed_at": datetime.now().isoformat(),
                        "ingest_mode": "git-mine",
                    }
                ],
            )
            filed += 1
            room_counts[room] += 1
        except Exception as exc:
            errors.append(f"{entry.source} {entry.ref}: {exc}")

    _print_results(commits, prs, reviews, filed, wing, room, errors)
    return {"commits": commits, "prs": prs, "reviews": reviews, "filed": filed, "errors": errors}


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
    commits: int, prs: int, reviews: int, filed: int, wing: str, room: str, errors: list
) -> None:
    print(f"\n{'=' * 55}")
    print(f"  Commits scanned:  {commits}")
    print(f"  PRs scanned:      {prs}")
    print(f"  Reviews scanned:  {reviews}")
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
    parser.add_argument("--wing", default=DEFAULT_WING)
    parser.add_argument("--room", default=DEFAULT_ROOM)
    parser.add_argument("--since", default="", help="Only commits after this date")
    parser.add_argument("--max-commits", type=int, default=0)
    parser.add_argument("--max-prs", type=int, default=25)
    parser.add_argument("--no-reviews", action="store_true")
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
