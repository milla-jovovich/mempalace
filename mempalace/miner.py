#!/usr/bin/env python3
"""
miner.py — Files everything into the palace.

Reads mempalace.yaml from the project directory to know the wing + rooms.
Routes each file to the right room based on content.
Stores verbatim chunks as drawers. No summaries. Ever.
"""

import os
import sys
import hashlib
import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
from collections import defaultdict

import chromadb

from .palace import SKIP_DIRS
from .drawer_store import DrawerNamespace, DrawerStore, PROJECT_INGEST_MODE, REFRESH_OWNER_KEY

READABLE_EXTENSIONS = {
    ".txt",
    ".md",
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".json",
    ".yaml",
    ".yml",
    ".html",
    ".css",
    ".java",
    ".go",
    ".rs",
    ".rb",
    ".sh",
    ".csv",
    ".sql",
    ".toml",
}

SKIP_FILENAMES = {
    "mempalace.yaml",
    "mempalace.yml",
    "mempal.yaml",
    "mempal.yml",
    ".gitignore",
    "package-lock.json",
}

CHUNK_SIZE = 800  # chars per drawer
CHUNK_OVERLAP = 100  # overlap between chunks
MIN_CHUNK_SIZE = 50  # skip tiny chunks
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB — skip files larger than this
PROJECT_PIPELINE_FINGERPRINT = (
    f"projects:v2:chunk={CHUNK_SIZE}:overlap={CHUNK_OVERLAP}:min={MIN_CHUNK_SIZE}:single-room"
)


# =============================================================================
# IGNORE MATCHING
# =============================================================================


class GitignoreMatcher:
    """Lightweight matcher for one directory's .gitignore patterns."""

    def __init__(self, base_dir: Path, rules: list):
        self.base_dir = base_dir
        self.rules = rules

    @classmethod
    def from_dir(cls, dir_path: Path):
        gitignore_path = dir_path / ".gitignore"
        if not gitignore_path.is_file():
            return None

        try:
            lines = gitignore_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return None

        rules = []
        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue

            if line.startswith("\\#") or line.startswith("\\!"):
                line = line[1:]
            elif line.startswith("#"):
                continue

            negated = line.startswith("!")
            if negated:
                line = line[1:]

            anchored = line.startswith("/")
            if anchored:
                line = line.lstrip("/")

            dir_only = line.endswith("/")
            if dir_only:
                line = line.rstrip("/")

            if not line:
                continue

            rules.append(
                {
                    "pattern": line,
                    "anchored": anchored,
                    "dir_only": dir_only,
                    "negated": negated,
                }
            )

        if not rules:
            return None

        return cls(dir_path, rules)

    def matches(self, path: Path, is_dir: bool = None):
        try:
            relative = path.relative_to(self.base_dir).as_posix().strip("/")
        except ValueError:
            return None

        if not relative:
            return None

        if is_dir is None:
            is_dir = path.is_dir()

        ignored = None
        for rule in self.rules:
            if self._rule_matches(rule, relative, is_dir):
                ignored = not rule["negated"]
        return ignored

    def _rule_matches(self, rule: dict, relative: str, is_dir: bool) -> bool:
        pattern = rule["pattern"]
        parts = relative.split("/")
        pattern_parts = pattern.split("/")

        if rule["dir_only"]:
            target_parts = parts if is_dir else parts[:-1]
            if not target_parts:
                return False
            if rule["anchored"] or len(pattern_parts) > 1:
                return self._match_from_root(target_parts, pattern_parts)
            return any(fnmatch.fnmatch(part, pattern) for part in target_parts)

        if rule["anchored"] or len(pattern_parts) > 1:
            return self._match_from_root(parts, pattern_parts)

        return any(fnmatch.fnmatch(part, pattern) for part in parts)

    def _match_from_root(self, target_parts: list, pattern_parts: list) -> bool:
        def matches(path_index: int, pattern_index: int) -> bool:
            if pattern_index == len(pattern_parts):
                return True

            if path_index == len(target_parts):
                return all(part == "**" for part in pattern_parts[pattern_index:])

            pattern_part = pattern_parts[pattern_index]
            if pattern_part == "**":
                return matches(path_index, pattern_index + 1) or matches(
                    path_index + 1, pattern_index
                )

            if not fnmatch.fnmatch(target_parts[path_index], pattern_part):
                return False

            return matches(path_index + 1, pattern_index + 1)

        return matches(0, 0)


def load_gitignore_matcher(dir_path: Path, cache: dict):
    """Load and cache one directory's .gitignore matcher."""
    if dir_path not in cache:
        cache[dir_path] = GitignoreMatcher.from_dir(dir_path)
    return cache[dir_path]


def is_gitignored(path: Path, matchers: list, is_dir: bool = False) -> bool:
    """Apply active .gitignore matchers in ancestor order; last match wins."""
    ignored = False
    for matcher in matchers:
        decision = matcher.matches(path, is_dir=is_dir)
        if decision is not None:
            ignored = decision
    return ignored


def should_skip_dir(dirname: str) -> bool:
    """Skip known generated/cache directories before gitignore matching."""
    return dirname in SKIP_DIRS or dirname.endswith(".egg-info")


def normalize_include_paths(include_ignored: list) -> set:
    """Normalize comma-parsed include paths into project-relative POSIX strings."""
    normalized = set()
    for raw_path in include_ignored or []:
        candidate = str(raw_path).strip().strip("/")
        if candidate:
            normalized.add(Path(candidate).as_posix())
    return normalized


def is_exact_force_include(path: Path, project_path: Path, include_paths: set) -> bool:
    """Return True when a path exactly matches an explicit include override."""
    if not include_paths:
        return False

    try:
        relative = path.relative_to(project_path).as_posix().strip("/")
    except ValueError:
        return False

    return relative in include_paths


def is_force_included(path: Path, project_path: Path, include_paths: set) -> bool:
    """Return True when a path or one of its ancestors/descendants was explicitly included."""
    if not include_paths:
        return False

    try:
        relative = path.relative_to(project_path).as_posix().strip("/")
    except ValueError:
        return False

    if not relative:
        return False

    for include_path in include_paths:
        if relative == include_path:
            return True
        if relative.startswith(f"{include_path}/"):
            return True
        if include_path.startswith(f"{relative}/"):
            return True

    return False


# =============================================================================
# CONFIG
# =============================================================================


def load_config(project_dir: str) -> dict:
    """Load mempalace.yaml from project directory (falls back to mempal.yaml)."""
    import yaml

    config_path = Path(project_dir).expanduser().resolve() / "mempalace.yaml"
    if not config_path.exists():
        # Fallback to legacy name
        legacy_path = Path(project_dir).expanduser().resolve() / "mempal.yaml"
        if legacy_path.exists():
            config_path = legacy_path
        else:
            print(f"ERROR: No mempalace.yaml found in {project_dir}")
            print(f"Run: mempalace init {project_dir}")
            sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f)


# =============================================================================
# FILE ROUTING — which room does this file belong to?
# =============================================================================


def detect_room(filepath: Path, content: str, rooms: list, project_path: Path) -> str:
    """
    Route a file to the right room.
    Priority:
    1. Folder path matches a room name
    2. Filename matches a room name or keyword
    3. Content keyword scoring
    4. Fallback: "general"
    """
    relative = str(filepath.relative_to(project_path)).lower()
    filename = filepath.stem.lower()
    content_lower = content[:2000].lower()

    # Priority 1: folder path matches room name or keywords
    path_parts = relative.replace("\\", "/").split("/")
    for part in path_parts[:-1]:  # skip filename itself
        for room in rooms:
            candidates = [room["name"].lower()] + [k.lower() for k in room.get("keywords", [])]
            if any(part == c or c in part or part in c for c in candidates):
                return room["name"]

    # Priority 2: filename matches room name
    for room in rooms:
        if room["name"].lower() in filename or filename in room["name"].lower():
            return room["name"]

    # Priority 3: keyword scoring from room keywords + name
    scores = defaultdict(int)
    for room in rooms:
        keywords = room.get("keywords", []) + [room["name"]]
        for kw in keywords:
            count = content_lower.count(kw.lower())
            scores[room["name"]] += count

    if scores:
        best = max(scores, key=scores.get)
        if scores[best] > 0:
            return best

    return "general"


# =============================================================================
# CHUNKING
# =============================================================================


def chunk_text(content: str, source_file: str) -> list:
    """
    Split content into drawer-sized chunks.
    Tries to split on paragraph/line boundaries.
    Returns list of {"content": str, "chunk_index": int}
    """
    # Clean up
    content = content.strip()
    if not content:
        return []

    chunks = []
    start = 0
    chunk_index = 0

    while start < len(content):
        end = min(start + CHUNK_SIZE, len(content))

        # Try to break at paragraph boundary
        if end < len(content):
            newline_pos = content.rfind("\n\n", start, end)
            if newline_pos > start + CHUNK_SIZE // 2:
                end = newline_pos
            else:
                newline_pos = content.rfind("\n", start, end)
                if newline_pos > start + CHUNK_SIZE // 2:
                    end = newline_pos

        chunk = content[start:end].strip()
        if len(chunk) >= MIN_CHUNK_SIZE:
            chunks.append(
                {
                    "content": chunk,
                    "chunk_index": chunk_index,
                }
            )
            chunk_index += 1

        start = end - CHUNK_OVERLAP if end < len(content) else end

    return chunks


# =============================================================================
# PALACE — source refresh operations
# =============================================================================


@dataclass
class ProcessResult:
    status: str
    drawers: int = 0
    cleared: int = 0
    room_counts: dict = field(default_factory=dict)
    error: str = ""


def build_source_signature(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def build_drawer_id(wing: str, room: str, source_file: str, chunk_index: int) -> str:
    digest = hashlib.sha256((source_file + str(chunk_index)).encode()).hexdigest()[:24]
    return f"drawer_{wing}_{room}_{digest}"


def prepare_drawer_rows(
    namespace: DrawerNamespace,
    source_root: str,
    source_signature: str,
    room: str,
    chunks: list,
    agent: str,
) -> list:
    rows = []
    filed_at = datetime.now().isoformat()
    for chunk in chunks:
        rows.append(
            {
                "id": build_drawer_id(
                    wing=namespace.wing,
                    room=room,
                    source_file=namespace.source_file,
                    chunk_index=chunk["chunk_index"],
                ),
                "document": chunk["content"],
                "metadata": {
                    "wing": namespace.wing,
                    "room": room,
                    "source_file": namespace.source_file,
                    "source_root": source_root,
                    "source_signature": source_signature,
                    "pipeline_fingerprint": PROJECT_PIPELINE_FINGERPRINT,
                    "chunk_index": chunk["chunk_index"],
                    "added_by": agent,
                    "filed_at": filed_at,
                    "ingest_mode": namespace.ingest_mode,
                    REFRESH_OWNER_KEY: namespace.refresh_owner,
                },
            }
        )
    return rows


def namespace_is_current(existing_rows: list, new_rows: list, source_signature: str) -> bool:
    if not existing_rows or not new_rows:
        return False

    existing_ids = [row["id"] for row in existing_rows]
    new_ids = [row["id"] for row in new_rows]
    if len(existing_ids) != len(new_ids):
        return False
    if set(existing_ids) != set(new_ids):
        return False

    for row in existing_rows:
        metadata = row["metadata"]
        if metadata.get("source_signature") != source_signature:
            return False
        if metadata.get("pipeline_fingerprint") != PROJECT_PIPELINE_FINGERPRINT:
            return False

    return True


# =============================================================================
# PROCESS ONE FILE
# =============================================================================


def process_file(
    filepath: Path,
    project_path: Path,
    store: DrawerStore,
    wing: str,
    rooms: list,
    agent: str,
    dry_run: bool,
) -> ProcessResult:
    """Read, chunk, route, and refresh one source-backed namespace."""
    source_file = str(filepath)
    namespace = DrawerNamespace(
        wing=wing,
        source_file=source_file,
        ingest_mode=PROJECT_INGEST_MODE,
    )
    existing_rows = []

    try:
        existing_rows = store.get_namespace_rows(namespace)
    except Exception:
        existing_rows = []

    try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return ProcessResult(status="error", error=str(exc))

    content = content.strip()
    if len(content) < MIN_CHUNK_SIZE:
        if not existing_rows:
            return ProcessResult(status="ignored")
        if dry_run:
            return ProcessResult(status="cleared", cleared=len(existing_rows))
        try:
            store.delete_ids([row["id"] for row in existing_rows])
        except Exception as exc:
            return ProcessResult(status="error", error=str(exc))
        return ProcessResult(status="cleared", cleared=len(existing_rows))

    room = detect_room(filepath, content, rooms, project_path)
    chunks = chunk_text(content, source_file)
    if not chunks:
        if not existing_rows:
            return ProcessResult(status="ignored")
        if dry_run:
            return ProcessResult(status="cleared", cleared=len(existing_rows))
        try:
            store.delete_ids([row["id"] for row in existing_rows])
        except Exception as exc:
            return ProcessResult(status="error", error=str(exc))
        return ProcessResult(status="cleared", cleared=len(existing_rows))

    source_signature = build_source_signature(content)
    new_rows = prepare_drawer_rows(
        namespace=namespace,
        source_root=str(project_path),
        source_signature=source_signature,
        room=room,
        chunks=chunks,
        agent=agent,
    )

    if namespace_is_current(existing_rows, new_rows, source_signature):
        return ProcessResult(status="unchanged")

    if dry_run:
        status = "new" if not existing_rows else "updated"
        return ProcessResult(status=status, drawers=len(new_rows), room_counts={room: len(new_rows)})

    try:
        store.upsert_rows(new_rows)
        new_ids = {row["id"] for row in new_rows}
        stale_ids = [row["id"] for row in existing_rows if row["id"] not in new_ids]
        if stale_ids:
            store.delete_ids(stale_ids)
    except Exception as exc:
        return ProcessResult(status="error", error=str(exc))

    status = "new" if not existing_rows else "updated"
    return ProcessResult(status=status, drawers=len(new_rows), room_counts={room: len(new_rows)})


# =============================================================================
# SCAN PROJECT
# =============================================================================


def scan_project(
    project_dir: str,
    respect_gitignore: bool = True,
    include_ignored: list = None,
) -> list:
    """Return list of all readable file paths."""
    project_path = Path(project_dir).expanduser().resolve()
    files = []
    active_matchers = []
    matcher_cache = {}
    include_paths = normalize_include_paths(include_ignored)

    for root, dirs, filenames in os.walk(project_path):
        root_path = Path(root)

        if respect_gitignore:
            active_matchers = [
                matcher
                for matcher in active_matchers
                if root_path == matcher.base_dir or matcher.base_dir in root_path.parents
            ]
            current_matcher = load_gitignore_matcher(root_path, matcher_cache)
            if current_matcher is not None:
                active_matchers.append(current_matcher)

        dirs[:] = [
            d
            for d in dirs
            if is_force_included(root_path / d, project_path, include_paths)
            or not should_skip_dir(d)
        ]
        if respect_gitignore and active_matchers:
            dirs[:] = [
                d
                for d in dirs
                if is_force_included(root_path / d, project_path, include_paths)
                or not is_gitignored(root_path / d, active_matchers, is_dir=True)
            ]

        for filename in filenames:
            filepath = root_path / filename
            force_include = is_force_included(filepath, project_path, include_paths)
            exact_force_include = is_exact_force_include(filepath, project_path, include_paths)

            if not force_include and filename in SKIP_FILENAMES:
                continue
            if filepath.suffix.lower() not in READABLE_EXTENSIONS and not exact_force_include:
                continue
            if respect_gitignore and active_matchers and not force_include:
                if is_gitignored(filepath, active_matchers, is_dir=False):
                    continue
            # Skip symlinks — prevents following links to /dev/urandom, etc.
            if filepath.is_symlink():
                continue
            # Skip files exceeding size limit
            try:
                if filepath.stat().st_size > MAX_FILE_SIZE:
                    continue
            except OSError:
                continue
            files.append(filepath)
    return files


# =============================================================================
# MAIN: MINE
# =============================================================================


def mine(
    project_dir: str,
    palace_path: str,
    wing_override: str = None,
    agent: str = "mempalace",
    limit: int = 0,
    dry_run: bool = False,
    respect_gitignore: bool = True,
    include_ignored: list = None,
):
    """Mine a project directory into the palace."""

    project_path = Path(project_dir).expanduser().resolve()
    config = load_config(project_dir)

    wing = wing_override or config["wing"]
    rooms = config.get("rooms", [{"name": "general", "description": "All project files"}])

    files = scan_project(
        project_dir,
        respect_gitignore=respect_gitignore,
        include_ignored=include_ignored,
    )
    if limit > 0:
        files = files[:limit]

    print(f"\n{'=' * 55}")
    print("  MemPalace Mine")
    print(f"{'=' * 55}")
    print(f"  Wing:    {wing}")
    print(f"  Rooms:   {', '.join(r['name'] for r in rooms)}")
    print(f"  Files:   {len(files)}")
    store = DrawerStore(palace_path=palace_path)
    print(f"  Palace:  {store.palace_path}")
    if dry_run:
        print("  DRY RUN — nothing will be filed")
    if not respect_gitignore:
        print("  .gitignore: DISABLED")
    if include_ignored:
        print(f"  Include: {', '.join(sorted(normalize_include_paths(include_ignored)))}")
    print(f"{'─' * 55}\n")

    total_drawers = 0
    total_cleared = 0
    status_counts = defaultdict(int)
    room_counts = defaultdict(int)

    for i, filepath in enumerate(files, 1):
        result = process_file(
            filepath=filepath,
            project_path=project_path,
            store=store,
            wing=wing,
            rooms=rooms,
            agent=agent,
            dry_run=dry_run,
        )
        status_counts[result.status] += 1
        total_drawers += result.drawers
        total_cleared += result.cleared
        for room, count in result.room_counts.items():
            room_counts[room] += count

        if dry_run:
            detail = []
            if result.drawers:
                detail.append(f"{result.drawers} drawers")
            if result.cleared:
                detail.append(f"clear {result.cleared}")
            suffix = f" ({', '.join(detail)})" if detail else ""
            print(f"    [DRY RUN] {filepath.name} → {result.status}{suffix}")
            continue

        if result.status in ("new", "updated"):
            print(
                f"  ✓ [{i:4}/{len(files)}] {filepath.name[:50]:50} "
                f"{result.status:7} +{result.drawers}"
            )
        elif result.status == "cleared":
            print(f"  ✓ [{i:4}/{len(files)}] {filepath.name[:50]:50} cleared  -{result.cleared}")
        elif result.status == "error":
            print(f"  ! [{i:4}/{len(files)}] {filepath.name[:50]:50} error    {result.error}")

    print(f"\n{'=' * 55}")
    print("  Done.")
    print(f"  Files scanned: {len(files)}")
    print(f"  Files new: {status_counts['new']}")
    print(f"  Files updated: {status_counts['updated']}")
    print(f"  Files unchanged: {status_counts['unchanged']}")
    print(f"  Files cleared: {status_counts['cleared']}")
    print(f"  Files errored: {status_counts['error']}")
    if status_counts["ignored"]:
        print(f"  Files ignored (no usable content): {status_counts['ignored']}")
    print(f"  Drawers filed: {total_drawers}")
    print(f"  Drawers cleared: {total_cleared}")
    if room_counts:
        print("\n  Drawers filed by room:")
        for room, count in sorted(room_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"    {room:20} {count} drawers")
    print('\n  Next: mempalace search "what you\'re looking for"')
    print(f"{'=' * 55}\n")


# =============================================================================
# STATUS
# =============================================================================


def status(palace_path: str):
    """Show what's been filed in the palace."""
    try:
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
    except Exception:
        print(f"\n  No palace found at {palace_path}")
        print("  Run: mempalace init <dir> then mempalace mine <dir>")
        return

    # Count by wing and room
    r = col.get(limit=10000, include=["metadatas"])
    metas = r["metadatas"]

    wing_rooms = defaultdict(lambda: defaultdict(int))
    for m in metas:
        wing_rooms[m.get("wing", "?")][m.get("room", "?")] += 1

    print(f"\n{'=' * 55}")
    print(f"  MemPalace Status — {len(metas)} drawers")
    print(f"{'=' * 55}\n")
    for wing, rooms in sorted(wing_rooms.items()):
        print(f"  WING: {wing}")
        for room, count in sorted(rooms.items(), key=lambda x: x[1], reverse=True):
            print(f"    ROOM: {room:20} {count:5} drawers")
        print()
    print(f"{'=' * 55}\n")
