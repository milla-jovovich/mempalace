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
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from .drawer_store import DrawerNamespace, DrawerStore, REFRESH_OWNER_KEY

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

SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    ".next",
    "coverage",
    ".mempalace",
}

CHUNK_SIZE = 800  # chars per drawer
CHUNK_OVERLAP = 100  # overlap between chunks
MIN_CHUNK_SIZE = 50  # skip tiny chunks
PROJECT_PIPELINE_FINGERPRINT = (
    f"projects:v2:chunk={CHUNK_SIZE}:overlap={CHUNK_OVERLAP}:min={MIN_CHUNK_SIZE}:single-room"
)


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

    # Priority 1: folder path contains room name
    path_parts = relative.replace("\\", "/").split("/")
    for part in path_parts[:-1]:  # skip filename itself
        for room in rooms:
            if room["name"].lower() in part or part in room["name"].lower():
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
# PALACE — ChromaDB operations
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
    digest = hashlib.md5((source_file + str(chunk_index)).encode()).hexdigest()[:16]
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
    namespace = DrawerNamespace(wing=wing, source_file=source_file, ingest_mode="projects")
    existing_rows = []

    try:
        existing_rows = store.get_namespace_rows(namespace)
    except Exception:
        existing_rows = []

    try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
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
        stale_ids = [row["id"] for row in existing_rows if row["id"] not in {r["id"] for r in new_rows}]
        if stale_ids:
            store.delete_ids(stale_ids)
    except Exception as exc:
        return ProcessResult(status="error", error=str(exc))

    status = "new" if not existing_rows else "updated"
    return ProcessResult(status=status, drawers=len(new_rows), room_counts={room: len(new_rows)})


# =============================================================================
# SCAN PROJECT
# =============================================================================


def scan_project(project_dir: str) -> list:
    """Return list of all readable file paths."""
    project_path = Path(project_dir).expanduser().resolve()
    files = []
    for root, dirs, filenames in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for filename in filenames:
            filepath = Path(root) / filename
            if filepath.suffix.lower() in READABLE_EXTENSIONS:
                # Skip config files
                if filename in (
                    "mempalace.yaml",
                    "mempalace.yml",
                    "mempal.yaml",
                    "mempal.yml",
                    ".gitignore",
                    "package-lock.json",
                ):
                    continue
                files.append(filepath)
    return files


# =============================================================================
# MAIN: MINE
# =============================================================================


def mine(
    project_dir: str,
    palace_path: str = None,
    collection_name: str = None,
    wing_override: str = None,
    agent: str = "mempalace",
    limit: int = 0,
    dry_run: bool = False,
):
    """Mine a project directory into the palace."""

    project_path = Path(project_dir).expanduser().resolve()
    config = load_config(project_dir)

    wing = wing_override or config["wing"]
    rooms = config.get("rooms", [{"name": "general", "description": "All project files"}])

    files = scan_project(project_dir)
    if limit > 0:
        files = files[:limit]

    print(f"\n{'=' * 55}")
    print("  MemPalace Mine")
    print(f"{'=' * 55}")
    print(f"  Wing:    {wing}")
    print(f"  Rooms:   {', '.join(r['name'] for r in rooms)}")
    print(f"  Files:   {len(files)}")
    store = DrawerStore(palace_path=palace_path, collection_name=collection_name)
    print(f"  Palace:  {store.palace_path}")
    if dry_run:
        print("  DRY RUN — nothing will be filed")
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
            print(f"  ✓ [{i:4}/{len(files)}] {filepath.name[:50]:50} {result.status:7} +{result.drawers}")
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


def status(palace_path: str = None, collection_name: str = None):
    """Show what's been filed in the palace."""
    store = DrawerStore(palace_path=palace_path, collection_name=collection_name)
    try:
        total_drawers = store.count()
        rows = store.get_rows(include_documents=False)
    except Exception:
        print(f"\n  No palace found at {store.palace_path}")
        print("  Run: mempalace init <dir> then mempalace mine <dir>")
        return

    wing_rooms = defaultdict(lambda: defaultdict(int))
    for row in rows:
        m = row["metadata"]
        wing_rooms[m.get("wing", "?")][m.get("room", "?")] += 1

    print(f"\n{'=' * 55}")
    print(f"  MemPalace Status — {total_drawers} drawers")
    print(f"{'=' * 55}\n")
    for wing, rooms in sorted(wing_rooms.items()):
        print(f"  WING: {wing}")
        for room, count in sorted(rooms.items(), key=lambda x: x[1], reverse=True):
            print(f"    ROOM: {room:20} {count:5} drawers")
        print()
    print(f"{'=' * 55}\n")
