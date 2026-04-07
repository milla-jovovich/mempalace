#!/usr/bin/env python3
"""
miner.py — Files everything into the palace.

Reads mempalace.yaml from the project directory to know the wing + rooms.
Routes each file to the right room based on content.
Stores verbatim chunks as drawers. No summaries. Ever.
"""

import os
import sys
import signal
import hashlib
from pathlib import Path
from datetime import datetime
from collections import defaultdict

import chromadb

from .checkpoint import MineCheckpoint

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
BATCH_SIZE = 50  # drawers per ChromaDB write


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


def get_collection(palace_path: str):
    os.makedirs(palace_path, exist_ok=True)
    client = chromadb.PersistentClient(path=palace_path)
    try:
        return client.get_collection("mempalace_drawers")
    except Exception:
        return client.create_collection("mempalace_drawers")


def check_palace_health(palace_path: str) -> bool:
    """Return True if the palace is readable, False if corrupted."""
    try:
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
        col.count()
        return True
    except Exception:
        return False


def _find_hnsw_dir(palace_path: str):
    """Walk palace_path to find the directory containing link_lists.bin."""
    for root, _dirs, files in os.walk(palace_path):
        if "link_lists.bin" in files:
            return root
    return None


def repair_palace(palace_path: str, force: bool = False) -> bool:
    """Delete corrupted HNSW index files so ChromaDB rebuilds on next access.

    Returns True if repair was performed.
    """
    hnsw_dir = _find_hnsw_dir(palace_path)
    if hnsw_dir is None:
        return False

    link_lists = os.path.join(hnsw_dir, "link_lists.bin")
    size_bytes = os.path.getsize(link_lists) if os.path.exists(link_lists) else 0
    size_gb = size_bytes / (1024 ** 3)

    # Heuristic: link_lists.bin should never exceed ~100 MB for reasonable collections
    if force or size_gb > 1.0:
        label = f"{size_gb:.1f} GB" if size_gb >= 1.0 else f"{size_bytes} bytes"
        print(f"  ⚠️  Corrupted HNSW index detected ({label}). Rebuilding...")
        for fname in ["link_lists.bin", "data_level0.bin", "length.bin", "header.bin"]:
            path = os.path.join(hnsw_dir, fname)
            if os.path.exists(path):
                os.remove(path)
        return True
    return False


def file_already_mined(collection, source_file: str) -> bool:
    """Fast check: has this file been filed before?"""
    try:
        results = collection.get(where={"source_file": source_file}, limit=1)
        return len(results.get("ids", [])) > 0
    except Exception:
        return False


def make_drawer_id(wing: str, room: str, source_file: str, chunk_index: int) -> str:
    return f"drawer_{wing}_{room}_{hashlib.md5((source_file + str(chunk_index)).encode()).hexdigest()[:16]}"


def add_drawer(
    collection, wing: str, room: str, content: str, source_file: str, chunk_index: int, agent: str
):
    """Add one drawer to the palace."""
    drawer_id = make_drawer_id(wing, room, source_file, chunk_index)
    try:
        collection.add(
            documents=[content],
            ids=[drawer_id],
            metadatas=[
                {
                    "wing": wing,
                    "room": room,
                    "source_file": source_file,
                    "chunk_index": chunk_index,
                    "added_by": agent,
                    "filed_at": datetime.now().isoformat(),
                }
            ],
        )
        return True
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            return False
        raise


class DrawerBatch:
    """Accumulates drawers and flushes to ChromaDB in batches."""

    def __init__(self, collection, batch_size: int = BATCH_SIZE):
        self._collection = collection
        self._batch_size = batch_size
        self._ids = []
        self._documents = []
        self._metadatas = []

    def add(self, drawer_id: str, content: str, metadata: dict):
        self._ids.append(drawer_id)
        self._documents.append(content)
        self._metadatas.append(metadata)
        if len(self._ids) >= self._batch_size:
            self.flush()

    def flush(self):
        if not self._ids:
            return
        try:
            self._collection.add(
                ids=self._ids,
                documents=self._documents,
                metadatas=self._metadatas,
            )
        except Exception as e:
            # If batch add fails due to some duplicates, fall back to one-by-one
            if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                for i in range(len(self._ids)):
                    try:
                        self._collection.add(
                            ids=[self._ids[i]],
                            documents=[self._documents[i]],
                            metadatas=[self._metadatas[i]],
                        )
                    except Exception:
                        pass
            else:
                raise
        self._ids.clear()
        self._documents.clear()
        self._metadatas.clear()

    @property
    def pending(self) -> int:
        return len(self._ids)


# =============================================================================
# PROCESS ONE FILE
# =============================================================================


def process_file(
    filepath: Path,
    project_path: Path,
    collection,
    wing: str,
    rooms: list,
    agent: str,
    dry_run: bool,
    checkpoint: MineCheckpoint = None,
    batch: DrawerBatch = None,
) -> int:
    """Read, chunk, route, and file one file. Returns drawer count."""

    source_file = str(filepath)

    # Skip if already filed (checkpoint first, then ChromaDB)
    if not dry_run:
        if checkpoint and checkpoint.is_completed(source_file):
            return 0
        if file_already_mined(collection, source_file):
            return 0

    try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return 0

    content = content.strip()
    if len(content) < MIN_CHUNK_SIZE:
        return 0

    room = detect_room(filepath, content, rooms, project_path)
    chunks = chunk_text(content, source_file)

    if dry_run:
        print(f"    [DRY RUN] {filepath.name} → room:{room} ({len(chunks)} drawers)")
        return len(chunks)

    drawers_added = 0
    for chunk in chunks:
        drawer_id = make_drawer_id(wing, room, source_file, chunk["chunk_index"])
        metadata = {
            "wing": wing,
            "room": room,
            "source_file": source_file,
            "chunk_index": chunk["chunk_index"],
            "added_by": agent,
            "filed_at": datetime.now().isoformat(),
        }
        if batch is not None:
            batch.add(drawer_id, chunk["content"], metadata)
            drawers_added += 1
        else:
            added = add_drawer(
                collection=collection,
                wing=wing,
                room=room,
                content=chunk["content"],
                source_file=source_file,
                chunk_index=chunk["chunk_index"],
                agent=agent,
            )
            if added:
                drawers_added += 1

    return drawers_added


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
    palace_path: str,
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
    print(f"  Palace:  {palace_path}")
    if dry_run:
        print("  DRY RUN — nothing will be filed")
    print(f"{'─' * 55}\n")

    collection = None
    checkpoint = None
    batch = None

    if not dry_run:
        # Health check: detect and repair corrupted HNSW index before proceeding
        os.makedirs(palace_path, exist_ok=True)
        if not check_palace_health(palace_path):
            print("  Palace health check failed — attempting repair...")
            if repair_palace(palace_path):
                print("  HNSW index removed. ChromaDB will rebuild it.")
            else:
                print("  Could not auto-repair. Try: mempalace repair --force")

        collection = get_collection(palace_path)
        checkpoint = MineCheckpoint(palace_path)
        batch = DrawerBatch(collection)

        if checkpoint.completed_count > 0:
            print(f"  Resuming: {checkpoint.completed_count} files already checkpointed")

        # Graceful shutdown: flush pending batch and save checkpoint on SIGINT/SIGTERM
        def _graceful_shutdown(signum, frame):
            print("\n  Interrupted — flushing pending batch...")
            try:
                if batch is not None:
                    batch.flush()
            except Exception:
                pass
            try:
                if checkpoint is not None:
                    checkpoint.save()
            except Exception:
                pass
            sys.exit(1)

        signal.signal(signal.SIGTERM, _graceful_shutdown)
        signal.signal(signal.SIGINT, _graceful_shutdown)

    total_drawers = 0
    files_skipped = 0
    room_counts = defaultdict(int)

    for i, filepath in enumerate(files, 1):
        drawers = process_file(
            filepath=filepath,
            project_path=project_path,
            collection=collection,
            wing=wing,
            rooms=rooms,
            agent=agent,
            dry_run=dry_run,
            checkpoint=checkpoint,
            batch=batch,
        )
        if drawers == 0 and not dry_run:
            files_skipped += 1
        else:
            total_drawers += drawers
            room = detect_room(filepath, "", rooms, project_path)
            room_counts[room] += 1
            if not dry_run:
                print(f"  ✓ [{i:4}/{len(files)}] {filepath.name[:50]:50} +{drawers}")

        # After each file: flush batch and update checkpoint
        if not dry_run and drawers > 0:
            batch.flush()
            checkpoint.mark_completed(str(filepath), drawers)
            checkpoint.save()

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
