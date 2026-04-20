#!/usr/bin/env python3
"""
git_miner.py — Mines a git repo commit by commit, branch by branch.

Extracts commit messages, diffs, metadata, and files changed.
Stores verbatim content as drawers. No summaries. Ever.
"""

import git
import hashlib
from datetime import datetime
from pathlib import Path
from collections import defaultdict

from .palace import (
    build_closet_lines,
    file_already_mined,
    get_closets_collection,
    get_collection,
    mine_lock,
    purge_file_closets,
    upsert_closet_lines,
)


def get_branches(repo: git.Repo) -> list:
    """Get all local and remote branch names."""
    return [b.name for b in repo.branches]


def get_all_commits(repo: git.Repo, branch: str = None) -> list:
    """Get all commits for a branch (newest first)."""
    commits = []
    for commit in repo.iter_commits(branch):
        commits.append({
            "hash": commit.hexsha,
            "date": commit.committed_datetime.isoformat(),
            "author": commit.author.name,
            "author_email": commit.author.email,
            "subject": commit.message.split("\n")[0],
            "body": commit.message,
        })
    return commits


def get_commit_diff(repo: git.Repo, commit_hash: str) -> str:
    """Get the diff for a commit (excluding binary files)."""
    try:
        commit = repo.commit(commit_hash)
        parent = commit.parents[0] if commit.parents else None
        if parent:
            diff_index = parent.diff(commit)
            diffs = []
            for d in diff_index:
                if d.change_type in ("A", "C", "M"):  # Added, Copied, Modified
                    if d.new_file:
                        diffs.append(f"+++ {d.b_path}\n")
                    else:
                        diffs.append(d.diff.decode("utf-8", errors="replace"))
            return "\n".join(diffs)
        else:
            tree = commit.tree
            diffs = []
            for blob in tree.traverse(prune=[]):
                if blob.type == "blob":
                    try:
                        content = blob.data_stream.read().decode("utf-8", errors="replace")
                        diffs.append(f"+++ {blob.path}\n{content}")
                    except Exception:
                        pass
            return "\n".join(diffs)
    except Exception:
        return ""


def get_commit_files_changed(repo: git.Repo, commit_hash: str) -> list:
    """List of files changed in a commit."""
    try:
        commit = repo.commit(commit_hash)
        parent = commit.parents[0] if commit.parents else None
        if parent:
            diff_index = parent.diff(commit)
            return [d.b_path for d in diff_index if d.b_path]
        else:
            return [blob.path for blob in commit.tree.traverse() if blob.type == "blob"]
    except Exception:
        return []


def detect_room_from_files(filepaths: list, fallback: str = "general") -> str:
    """Infer room from files changed in a commit."""
    if not filepaths:
        return fallback

    file_counts = defaultdict(int)
    for fp in filepaths:
        parts = fp.split("/")
        for part in parts:
            if part and not part.startswith("."):
                file_counts[part] += 1

    if not file_counts:
        return fallback

    top_file = max(file_counts, key=file_counts.get)
    ext = Path(top_file).suffix.lower()

    room_mapping = {
        ".py": "code",
        ".js": "code",
        ".ts": "code",
        ".jsx": "code",
        ".tsx": "code",
        ".go": "code",
        ".rs": "code",
        ".java": "code",
        ".md": "docs",
        ".txt": "docs",
        ".yaml": "config",
        ".yml": "config",
        ".json": "config",
        ".toml": "config",
        ".sql": "database",
        ".css": "styles",
        ".scss": "styles",
    }
    if ext in room_mapping:
        return room_mapping[ext]

    return top_file if file_counts[top_file] > 1 else fallback


def add_git_drawer(
    collection,
    wing: str,
    room: str,
    content: str,
    source: str,
    chunk_index: int,
    agent: str,
):
    """Add one drawer for a git commit."""
    drawer_id = f"git_{wing}_{room}_{hashlib.sha256((source + str(chunk_index)).encode()).hexdigest()[:24]}"
    try:
        metadata = {
            "wing": wing,
            "room": room,
            "source_file": source,
            "chunk_index": chunk_index,
            "added_by": agent,
            "filed_at": datetime.now().isoformat(),
        }
        collection.upsert(
            documents=[content],
            ids=[drawer_id],
            metadatas=[metadata],
        )
        return True
    except Exception:
        raise


def process_commit(
    repo: git.Repo,
    commit: dict,
    collection,
    closets_col,
    wing: str,
    agent: str,
    dry_run: bool,
    repo_path: Path,
):
    """Process a single commit into the palace."""
    commit_hash = commit["hash"]
    source = f"{repo_path}:{commit_hash[:8]}"

    if not dry_run:
        if file_already_mined(collection, source, check_mtime=False):
            return 0, "general"

    diff = get_commit_diff(repo, commit_hash)
    files_changed = get_commit_files_changed(repo, commit_hash)

    subject = commit.get("subject", "")
    body = commit.get("body", "")
    author = commit.get("author", "")
    date = commit.get("date", "")

    content = f"""commit {commit_hash}
Author: {author} <{commit.get('author_email', '')}>
Date:   {date}

{subject}

{body}

Files changed:
{chr(10).join(files_changed) if files_changed else '(none)'}

Diff:
{diff}
""".strip()

    room = detect_room_from_files(files_changed)

    if dry_run:
        print(f"    [DRY RUN] {commit_hash[:8]} -> room:{room}")
        return 1, room

    with mine_lock(source):
        if file_already_mined(collection, source, check_mtime=False):
            return 0, room

        try:
            collection.delete(where={"source_file": source})
        except Exception:
            pass

        added = add_git_drawer(
            collection=collection,
            wing=wing,
            room=room,
            content=content,
            source=source,
            chunk_index=0,
            agent=agent,
        )

        if closets_col and added:
            drawer_id = f"git_{wing}_{room}_{hashlib.sha256((source + '0').encode()).hexdigest()[:24]}"
            closet_lines = build_closet_lines(source, [drawer_id], content, wing, room)
            closet_id_base = f"closet_{wing}_{room}_{hashlib.sha256(source.encode()).hexdigest()[:24]}"
            closet_meta = {
                "wing": wing,
                "room": room,
                "source_file": source,
                "drawer_count": 1,
                "filed_at": datetime.now().isoformat(),
            }
            purge_file_closets(closets_col, source)
            upsert_closet_lines(closets_col, closet_id_base, closet_lines, closet_meta)

        return 1 if added else 0, room


def mine_git(
    repo_dir: str,
    palace_path: str,
    wing: str = None,
    agent: str = "mempalace",
    limit: int = 0,
    dry_run: bool = False,
    branches: list = None,
):
    """Mine a git repo commit by commit."""
    repo_path = Path(repo_dir).expanduser().resolve()

    try:
        repo = git.Repo(repo_path)
    except Exception:
        print(f"  Not a git repo: {repo_path}")
        return

    all_branches = get_branches(repo)
    if not all_branches:
        print(f"  No branches found in {repo_path}")
        return

    target_branches = branches if branches else all_branches

    wing_name = wing or repo_path.name

    print(f"\n{'=' * 55}")
    print("  MemPalace Git Mine")
    print(f"{'=' * 55}")
    print(f"  Repo:    {repo_path}")
    print(f"  Wing:    {wing_name}")
    print(f"  Branches: {len(target_branches)}")
    print(f"  Palace:  {palace_path}")
    if dry_run:
        print("  DRY RUN — nothing will be filed")
    print(f"{'-' * 55}\n")

    if not dry_run:
        collection = get_collection(palace_path)
        closets_col = get_closets_collection(palace_path)
    else:
        collection = None
        closets_col = None

    total_drawers = 0
    commits_processed = 0
    commits_skipped = 0
    branch_counts = defaultdict(int)

    for branch in target_branches:
        print(f"  Branch: {branch}")
        commits = get_all_commits(repo, branch)

        for commit in commits:
            if limit > 0 and commits_processed >= limit:
                break

            drawers, room = process_commit(
                repo=repo,
                commit=commit,
                collection=collection,
                closets_col=closets_col,
                wing=wing_name,
                agent=agent,
                dry_run=dry_run,
                repo_path=repo_path,
            )

            if drawers == 0:
                commits_skipped += 1
            else:
                total_drawers += drawers
                branch_counts[branch] += 1
                commits_processed += 1
                if not dry_run:
                    print(f"    + {commit['hash'][:8]} {commit['subject'][:50]}")

        if limit > 0 and commits_processed >= limit:
            break

    print(f"\n{'=' * 55}")
    print("  Done.")
    print(f"  Commits processed: {commits_processed}")
    print(f"  Commits skipped (already filed): {commits_skipped}")
    print(f"  Drawers filed: {total_drawers}")
    print(f"  Next: mempalace search \"what you're looking for\"")
    print(f"{'=' * 55}\n")