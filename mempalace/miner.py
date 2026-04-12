#!/usr/bin/env python3
"""
miner.py — Files everything into the palace.

Reads mempalace.yaml from the project directory to know the wing + rooms.
Routes each file to the right room based on content.
Stores verbatim chunks as drawers. No summaries. Ever.
"""

import logging
import os
import re
import sys
import hashlib
import fnmatch
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from .palace import SKIP_DIRS, get_collection, file_already_mined, bulk_check_mined

logger = logging.getLogger(__name__)

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

# Patterns for files that are technically text but useless for semantic search.
# Matched against the filename (case-insensitive).
SKIP_PATTERNS = [
    ".min.js",  # minified JS (jquery.min.js, etc.)
    ".min.css",  # minified CSS
    ".bundle.js",  # bundled JS
    ".chunk.js",  # webpack chunks
    ".map",  # source maps
    "-lock.json",  # lockfiles (yarn.lock handled by extension)
    ".lock",  # lockfiles
]

# Files larger than this are likely dumps/generated — skip them even if under MAX_FILE_SIZE.
# This catches database dumps, large SQL exports, huge JSON fixtures, etc.
JUNK_FILE_SIZE = 500 * 1024  # 500 KB — most useful source files are well under this

CHUNK_SIZE = 800  # chars per drawer
CHUNK_OVERLAP = 100  # overlap between chunks
MIN_CHUNK_SIZE = 50  # skip tiny chunks
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB — skip files larger than this


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
    1. Folder path exactly matches a room name or keyword
    2. Filename exactly matches a room name or keyword
    3. Content keyword scoring (word-boundary matching)
    4. Fallback: "general"
    """
    relative = str(filepath.relative_to(project_path)).lower()
    filename = filepath.stem.lower()
    # Use more content for keyword scoring: full file up to 10KB, else first 5KB
    scan_limit = len(content) if len(content) <= 10000 else 5000
    content_lower = content[:scan_limit].lower()

    # Priority 1: folder path exactly matches room name or keywords
    path_parts = relative.replace("\\", "/").split("/")
    for part in path_parts[:-1]:  # skip filename itself
        for room in rooms:
            candidates = [room["name"].lower()] + [k.lower() for k in room.get("keywords", [])]
            if any(part == c for c in candidates):
                return room["name"]

    # Priority 2: filename exactly matches room name or keyword
    for room in rooms:
        candidates = [room["name"].lower()] + [k.lower() for k in room.get("keywords", [])]
        if any(filename == c for c in candidates):
            return room["name"]

    # Priority 3: keyword scoring with word-boundary matching
    scores = defaultdict(int)
    for room in rooms:
        keywords = room.get("keywords", []) + [room["name"]]
        for kw in keywords:
            count = len(re.findall(r"\b" + re.escape(kw.lower()) + r"\b", content_lower))
            scores[room["name"]] += count

    if scores:
        best = max(scores, key=scores.get)
        if scores[best] > 0:
            return best

    return "general"


# =============================================================================
# CHUNKING
# =============================================================================


def chunk_text(
    content: str,
    source_file: str,
    chunk_size: int = None,
    chunk_overlap: int = None,
    min_chunk_size: int = None,
) -> list:
    """
    Split content into drawer-sized chunks.
    Tries to split on paragraph/line boundaries.
    Returns list of {"content": str, "chunk_index": int}

    Optional params override module-level defaults when provided.
    """
    if chunk_size is None:
        chunk_size = CHUNK_SIZE
    if chunk_overlap is None:
        chunk_overlap = CHUNK_OVERLAP
    if min_chunk_size is None:
        min_chunk_size = MIN_CHUNK_SIZE

    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError(
            f"chunk_overlap ({chunk_overlap}) must be >= 0 and < chunk_size ({chunk_size})"
        )

    # Clean up
    content = content.strip()
    if not content:
        return []

    chunks = []
    start = 0
    chunk_index = 0

    while start < len(content):
        end = min(start + chunk_size, len(content))

        # Try to break at paragraph boundary
        if end < len(content):
            newline_pos = content.rfind("\n\n", start, end)
            if newline_pos > start + chunk_size // 2:
                end = newline_pos
            else:
                newline_pos = content.rfind("\n", start, end)
                if newline_pos > start + chunk_size // 2:
                    end = newline_pos

        chunk = content[start:end].strip()
        if len(chunk) >= min_chunk_size:
            chunks.append(
                {
                    "content": chunk,
                    "chunk_index": chunk_index,
                }
            )
            chunk_index += 1

        start = end - chunk_overlap if end < len(content) else end

    return chunks


# =============================================================================
# PALACE — ChromaDB operations
# =============================================================================


def add_drawer(
    collection, wing: str, room: str, content: str, source_file: str, chunk_index: int, agent: str
):
    """Add one drawer to the palace."""
    drawer_id = f"drawer_{wing}_{room}_{hashlib.sha256((source_file + str(chunk_index)).encode()).hexdigest()[:24]}"
    try:
        metadata = {
            "wing": wing,
            "room": room,
            "source_file": source_file,
            "chunk_index": chunk_index,
            "added_by": agent,
            "filed_at": datetime.now().isoformat(),
        }
        # Store file mtime so we can detect modifications later.
        try:
            metadata["source_mtime"] = os.path.getmtime(source_file)
        except OSError:
            pass
        collection.upsert(
            documents=[content],
            ids=[drawer_id],
            metadatas=[metadata],
        )
        return True
    except Exception:
        raise


# =============================================================================
# PROCESS ONE FILE
# =============================================================================


def _prepare_file(
    filepath: Path,
    project_path: Path,
    wing: str,
    rooms: list,
    agent: str,
    chunk_size: int = None,
    chunk_overlap: int = None,
    min_chunk_size: int = None,
) -> tuple:
    """Read, chunk, and route one file without writing to ChromaDB.

    Returns (batch_docs, batch_ids, batch_metas, room) or (None, None, None, None)
    when the file should be skipped (unreadable, too small, etc.).
    This is the pure-computation half of process_file, safe for concurrent use.
    """
    effective_min = min_chunk_size if min_chunk_size is not None else MIN_CHUNK_SIZE
    source_file = str(filepath)

    try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None, None, None

    content = content.strip()
    if len(content) < effective_min:
        return None, None, None, None

    room = detect_room(filepath, content, rooms, project_path)
    chunks = chunk_text(
        content,
        source_file,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        min_chunk_size=min_chunk_size,
    )

    if not chunks:
        return None, None, None, None

    batch_docs = []
    batch_ids = []
    batch_metas = []
    try:
        file_mtime = os.path.getmtime(source_file)
    except OSError:
        file_mtime = None

    for chunk in chunks:
        drawer_id = f"drawer_{wing}_{room}_{hashlib.sha256((source_file + str(chunk['chunk_index'])).encode()).hexdigest()[:24]}"
        metadata = {
            "wing": wing,
            "room": room,
            "source_file": source_file,
            "chunk_index": chunk["chunk_index"],
            "added_by": agent,
            "filed_at": datetime.now().isoformat(),
        }
        if file_mtime is not None:
            metadata["source_mtime"] = file_mtime
        batch_docs.append(chunk["content"])
        batch_ids.append(drawer_id)
        batch_metas.append(metadata)

    return batch_docs, batch_ids, batch_metas, room


def process_file(
    filepath: Path,
    project_path: Path,
    collection,
    wing: str,
    rooms: list,
    agent: str,
    dry_run: bool,
    chunk_size: int = None,
    chunk_overlap: int = None,
    min_chunk_size: int = None,
) -> tuple:
    """Read, chunk, route, and file one file. Returns (drawer_count, room_name)."""
    effective_min = min_chunk_size if min_chunk_size is not None else MIN_CHUNK_SIZE

    # Skip if already filed
    source_file = str(filepath)
    if not dry_run and file_already_mined(collection, source_file, check_mtime=True):
        return 0, "general"

    try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0, "general"

    content = content.strip()
    if len(content) < MIN_CHUNK_SIZE:
        return 0, "general"

    room = detect_room(filepath, content, rooms, project_path)
    chunks = chunk_text(content, source_file)

    if dry_run:
        print(f"    [DRY RUN] {filepath.name} → room:{room} ({len(chunks)} drawers)")
        return len(chunks), room

    # Purge stale drawers for this file before re-inserting the fresh chunks.
    # Converts modified-file re-mines from upsert-over-existing-IDs (which hits
    # hnswlib's thread-unsafe updatePoint path and can segfault on macOS ARM
    # with chromadb 0.6.3) into a clean delete+insert, bypassing the update
    # path entirely.
    try:
        collection.delete(where={"source_file": source_file})
    except Exception:
        pass

    batch_docs, batch_ids, batch_metas, room = _prepare_file(
        filepath,
        project_path,
        wing,
        rooms,
        agent,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        min_chunk_size=min_chunk_size,
    )
    if batch_docs is None:
        return 0, None

    collection.upsert(
        documents=batch_docs,
        ids=batch_ids,
        metadatas=batch_metas,
    )

    return len(batch_docs), room


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
            # Skip minified/bundled/lock files — text but useless for recall
            if not force_include:
                lower_name = filename.lower()
                if any(lower_name.endswith(pat) for pat in SKIP_PATTERNS):
                    continue
            if respect_gitignore and active_matchers and not force_include:
                if is_gitignored(filepath, active_matchers, is_dir=False):
                    continue
            # Skip symlinks — prevents following links to /dev/urandom, etc.
            if filepath.is_symlink():
                continue
            # Skip files exceeding size limit
            try:
                fsize = filepath.stat().st_size
                if fsize > MAX_FILE_SIZE:
                    continue
                # Skip suspiciously large text files (SQL dumps, generated JSON, etc.)
                if not force_include and fsize > JUNK_FILE_SIZE:
                    continue
            except OSError:
                continue
            files.append(filepath)
    return files


# =============================================================================
# MAIN: MINE
# =============================================================================


def _is_already_mined(source_file: str, mined_map: dict) -> bool:
    """Check if a file is already mined using the bulk-fetched mined_map.

    Compares stored mtime against current file mtime using epsilon tolerance,
    matching the logic in file_already_mined() but without per-file DB queries.
    """
    stored_mtime = mined_map.get(source_file)
    if stored_mtime is None:
        return False
    try:
        current_mtime = os.path.getmtime(source_file)
        return abs(float(stored_mtime) - current_mtime) < 0.01
    except (OSError, TypeError, ValueError):
        return False


# Maximum documents per ChromaDB upsert call
_UPSERT_BATCH_SIZE = 100


def mine(
    project_dir: str,
    palace_path: str,
    wing_override: str = None,
    agent: str = "mempalace",
    limit: int = 0,
    dry_run: bool = False,
    respect_gitignore: bool = True,
    include_ignored: list = None,
    workers: int = 0,
):
    """Mine a project directory into the palace.

    When workers > 1, files are read/chunked/routed in parallel threads
    and then written to ChromaDB sequentially (the Python client is not
    thread-safe for concurrent writes to the same collection).
    """
    import concurrent.futures
    import threading

    from .config import MempalaceConfig

    project_path = Path(project_dir).expanduser().resolve()
    config = load_config(project_dir)
    palace_config = MempalaceConfig()

    cfg_chunk_size = palace_config.chunk_size
    cfg_chunk_overlap = palace_config.chunk_overlap
    cfg_min_chunk_size = palace_config.min_chunk_size

    wing = wing_override or config["wing"]
    rooms = config.get("rooms", [{"name": "general", "description": "All project files"}])

    files = scan_project(
        project_dir,
        respect_gitignore=respect_gitignore,
        include_ignored=include_ignored,
    )
    if limit > 0:
        files = files[:limit]

    if workers <= 0:
        workers = min(8, os.cpu_count() or 4)

    print(f"\n{'=' * 55}")
    print("  MemPalace Mine")
    print(f"{'=' * 55}")
    print(f"  Wing:    {wing}")
    print(f"  Rooms:   {', '.join(r['name'] for r in rooms)}")
    print(f"  Files:   {len(files)}")
    print(f"  Palace:  {palace_path}")
    if workers > 1:
        print(f"  Workers: {workers}")
    if dry_run:
        print("  DRY RUN — nothing will be filed")
    if not respect_gitignore:
        print("  .gitignore: DISABLED")
    if include_ignored:
        print(f"  Include: {', '.join(sorted(normalize_include_paths(include_ignored)))}")
    print(f"{'─' * 55}\n")

    if not dry_run:
        collection = get_collection(palace_path)
    else:
        collection = None

    total_drawers = 0
    files_skipped = 0
    room_counts = defaultdict(int)

    # --- Sequential path (workers=1 or dry_run) ---
    if workers <= 1 or dry_run:
        for i, filepath in enumerate(files, 1):
            drawers, room = process_file(
                filepath=filepath,
                project_path=project_path,
                collection=collection,
                wing=wing,
                rooms=rooms,
                agent=agent,
                dry_run=dry_run,
                chunk_size=cfg_chunk_size,
                chunk_overlap=cfg_chunk_overlap,
                min_chunk_size=cfg_min_chunk_size,
            )
            if drawers == 0 and not dry_run:
                files_skipped += 1
            else:
                total_drawers += drawers
                room_counts[room or "general"] += 1
                if not dry_run:
                    print(f"  \u2713 [{i:4}/{len(files)}] {filepath.name[:50]:50} +{drawers}")
    else:
        # --- Concurrent path (workers > 1) ---

        # Phase 0: bulk-fetch already-mined mtimes to skip files without
        # per-file DB queries.
        mined_map = bulk_check_mined(collection)

        # Filter out already-mined files before spawning threads.
        files_to_process = []
        for filepath in files:
            if _is_already_mined(str(filepath), mined_map):
                files_skipped += 1
            else:
                files_to_process.append(filepath)

        # Phase 1: parallel read/chunk/route
        counter_lock = threading.Lock()
        processed_count = 0

        def prepare_one(filepath):
            return filepath, _prepare_file(
                filepath,
                project_path,
                wing,
                rooms,
                agent,
                chunk_size=cfg_chunk_size,
                chunk_overlap=cfg_chunk_overlap,
                min_chunk_size=cfg_min_chunk_size,
            )

        # Phase 1 read/chunk + Phase 2 write as futures complete (stream to DB)
        pending_docs = []
        pending_ids = []
        pending_metas = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(prepare_one, fp): fp for fp in files_to_process}
            for future in concurrent.futures.as_completed(futures):
                try:
                    filepath, (batch_docs, batch_ids, batch_metas, room) = future.result()
                except Exception as exc:
                    failed_path = futures[future]
                    logger.warning("Skipping %s: %s", failed_path, exc)
                    with counter_lock:
                        files_skipped += 1
                    continue
                if batch_docs is None:
                    with counter_lock:
                        files_skipped += 1
                    continue

                total_drawers += len(batch_docs)
                room_counts[room or "general"] += 1
                pending_docs.extend(batch_docs)
                pending_ids.extend(batch_ids)
                pending_metas.extend(batch_metas)

                # Flush when batch is large enough
                if len(pending_docs) >= _UPSERT_BATCH_SIZE:
                    collection.upsert(
                        documents=pending_docs,
                        ids=pending_ids,
                        metadatas=pending_metas,
                    )
                    pending_docs = []
                    pending_ids = []
                    pending_metas = []

                with counter_lock:
                    processed_count += 1
                    print(
                        f"  \u2713 [{processed_count:4}/{len(files_to_process)}] "
                        f"{filepath.name[:50]:50} +{len(batch_docs)}"
                    )

        # Flush remainder
        if pending_docs:
            collection.upsert(
                documents=pending_docs,
                ids=pending_ids,
                metadatas=pending_metas,
            )

    print(f"\n{'=' * 55}")
    print("  Done.")
    print(f"  Files processed: {len(files) - files_skipped}")
    print(f"  Files skipped (already filed): {files_skipped}")
    print(f"  Drawers filed: {total_drawers}")
    print("\n  By room:")
    for room, count in sorted(room_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"    {room:20} {count} files")
    print('\n  Next: mempalace search "what you\'re looking for"')
    print(f"{'=' * 55}\n")


# =============================================================================
# STATUS
# =============================================================================


def status(palace_path: str):
    """Show what's been filed in the palace."""
    try:
        col = get_collection(palace_path, create=False)
    except Exception:
        print(f"\n  No palace found at {palace_path}")
        print("  Run: mempalace init <dir> then mempalace mine <dir>")
        return

    total = col.count()

    # Paginate all metadata to get accurate wing/room counts
    wing_rooms = defaultdict(lambda: defaultdict(int))
    offset = 0
    while offset < total:
        r = col.get(limit=10000, offset=offset, include=["metadatas"])
        if not r["metadatas"]:
            break
        for m in r["metadatas"]:
            wing_rooms[m.get("wing", "?")][m.get("room", "?")] += 1
        offset += len(r["metadatas"])

    print(f"\n{'=' * 55}")
    print(f"  MemPalace Status — {total:,} drawers")
    print(f"{'=' * 55}\n")
    for wing, rooms in sorted(wing_rooms.items()):
        print(f"  WING: {wing}")
        for room, count in sorted(rooms.items(), key=lambda x: x[1], reverse=True):
            print(f"    ROOM: {room:20} {count:>8,} drawers")
        print()
    print(f"{'=' * 55}\n")
