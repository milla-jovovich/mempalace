"""
pruner.py — Detect and remove stale drawers from the palace.

Stale drawers arise when:
  1. Source files are deleted but their drawers remain (strategy: existence)
  2. Source files are modified but old chunks linger (strategy: mtime)
  3. Orphaned chunks remain after a file shrinks (strategy: orphans)

Usage:
  from mempalace.pruner import prune
  result = prune(palace_path, strategy="existence", dry_run=True)
"""

import os
import hashlib
from collections import defaultdict
from datetime import datetime

from .palace import get_collection


# ── Batch helpers ────────────────────────────────────────────────────────────

_BATCH = 5000


def _iter_all_drawers(collection, wing=None):
    """Yield all (id, metadata) tuples from the collection, in batches."""
    offset = 0
    while True:
        kwargs = {"include": ["metadatas"], "limit": _BATCH, "offset": offset}
        if wing:
            kwargs["where"] = {"wing": wing}
        try:
            batch = collection.get(**kwargs)
        except Exception:
            break
        ids = batch.get("ids", [])
        metas = batch.get("metadatas", [])
        if not ids:
            break
        for drawer_id, meta in zip(ids, metas):
            yield drawer_id, meta
        if len(ids) < _BATCH:
            break
        offset += len(ids)


def _batch_delete(collection, ids, wal_log=None):
    """Delete drawer IDs in ChromaDB-safe batches."""
    deleted = 0
    for i in range(0, len(ids), _BATCH):
        batch = ids[i : i + _BATCH]
        if wal_log:
            wal_log("prune_batch", {"count": len(batch), "ids": batch[:10]})
        collection.delete(ids=batch)
        deleted += len(batch)
    return deleted


# ── Strategies ───────────────────────────────────────────────────────────────


def _find_stale_existence(collection, wing=None):
    """Find drawers whose source_file no longer exists on disk."""
    stale = []
    checked_paths = {}

    for drawer_id, meta in _iter_all_drawers(collection, wing):
        source = meta.get("source_file", "")
        if not source:
            continue

        if source not in checked_paths:
            checked_paths[source] = os.path.exists(source)

        if not checked_paths[source]:
            stale.append({
                "id": drawer_id,
                "source_file": source,
                "wing": meta.get("wing", "?"),
                "room": meta.get("room", "?"),
                "reason": "file_deleted",
            })

    return stale


def _find_stale_mtime(collection, wing=None):
    """Find drawers whose source_file has been modified since mining."""
    stale = []
    checked_files = {}

    for drawer_id, meta in _iter_all_drawers(collection, wing):
        source = meta.get("source_file", "")
        stored_mtime = meta.get("source_mtime")
        if not source or stored_mtime is None:
            continue

        if source not in checked_files:
            try:
                checked_files[source] = os.path.getmtime(source)
            except OSError:
                checked_files[source] = None

        current_mtime = checked_files[source]
        if current_mtime is None:
            # File deleted — caught by existence strategy
            continue

        if float(stored_mtime) != current_mtime:
            stale.append({
                "id": drawer_id,
                "source_file": source,
                "wing": meta.get("wing", "?"),
                "room": meta.get("room", "?"),
                "stored_mtime": stored_mtime,
                "current_mtime": current_mtime,
                "reason": "file_modified",
            })

    return stale


def _find_stale_orphans(collection, wing=None):
    """Find orphaned chunks: file exists and has been re-mined, but old
    chunks with higher chunk_index than current chunking remain.

    For each source_file, compute how many chunks the current content
    would produce, then flag drawers with chunk_index >= that count.
    """
    from .miner import chunk_text, MIN_CHUNK_SIZE

    # Group drawers by source_file
    file_drawers = defaultdict(list)
    for drawer_id, meta in _iter_all_drawers(collection, wing):
        source = meta.get("source_file", "")
        if not source:
            continue
        chunk_index = meta.get("chunk_index", 0)
        file_drawers[source].append((drawer_id, chunk_index, meta))

    stale = []
    for source, drawers in file_drawers.items():
        if not os.path.exists(source):
            continue  # Handled by existence strategy

        try:
            content = open(source, encoding="utf-8", errors="replace").read().strip()
        except OSError:
            continue

        if len(content) < MIN_CHUNK_SIZE:
            expected_chunks = 0
        else:
            expected_chunks = len(chunk_text(content, source))

        for drawer_id, chunk_index, meta in drawers:
            if chunk_index >= expected_chunks:
                stale.append({
                    "id": drawer_id,
                    "source_file": source,
                    "wing": meta.get("wing", "?"),
                    "room": meta.get("room", "?"),
                    "chunk_index": chunk_index,
                    "expected_chunks": expected_chunks,
                    "reason": "orphaned_chunk",
                })

    return stale


# ── Main entry point ─────────────────────────────────────────────────────────

STRATEGIES = {
    "existence": _find_stale_existence,
    "mtime": _find_stale_mtime,
    "orphans": _find_stale_orphans,
    "all": None,  # runs all strategies
}


def prune(
    palace_path: str,
    strategy: str = "all",
    wing: str = None,
    dry_run: bool = True,
    wal_log=None,
):
    """Detect and optionally remove stale drawers.

    Args:
        palace_path: Path to the palace directory.
        strategy: Detection strategy — 'existence', 'mtime', 'orphans', or 'all'.
        wing: Limit scan to a specific wing (optional).
        dry_run: If True, only report — don't delete.
        wal_log: Optional WAL logging function(operation, params).

    Returns:
        dict with results: stale drawers found, deleted count, etc.
    """
    if strategy not in STRATEGIES:
        return {"error": f"Unknown strategy: {strategy}. Choose: {', '.join(STRATEGIES)}"}

    collection = get_collection(palace_path)
    total_before = collection.count()

    # Collect stale drawers
    all_stale = []

    if strategy == "all":
        for name, fn in STRATEGIES.items():
            if fn is not None:
                all_stale.extend(fn(collection, wing))
    else:
        all_stale = STRATEGIES[strategy](collection, wing)

    # Deduplicate by drawer ID
    seen = set()
    unique_stale = []
    for entry in all_stale:
        if entry["id"] not in seen:
            seen.add(entry["id"])
            unique_stale.append(entry)

    # Group by reason for summary
    by_reason = defaultdict(int)
    by_file = defaultdict(int)
    for entry in unique_stale:
        by_reason[entry["reason"]] += 1
        by_file[entry.get("source_file", "?")] += 1

    result = {
        "total_drawers": total_before,
        "stale_found": len(unique_stale),
        "by_reason": dict(by_reason),
        "stale_files": len(by_file),
        "dry_run": dry_run,
        "strategy": strategy,
        "wing": wing,
        "deleted": 0,
    }

    if dry_run:
        # Include details for review
        result["stale_drawers"] = unique_stale[:50]  # Cap preview at 50
        if len(unique_stale) > 50:
            result["truncated"] = True
    else:
        # Actually delete
        ids_to_delete = [e["id"] for e in unique_stale]
        if ids_to_delete:
            result["deleted"] = _batch_delete(collection, ids_to_delete, wal_log)

    return result


def prune_file(collection, source_file: str):
    """Delete all drawers for a specific source file.

    Used by the miner before re-mining a modified file to prevent
    orphaned chunks. Returns the number of drawers deleted.
    """
    try:
        results = collection.get(
            where={"source_file": source_file},
            include=["metadatas"],
            limit=10000,
        )
        ids = results.get("ids", [])
        if not ids:
            return 0
        collection.delete(ids=ids)
        return len(ids)
    except Exception:
        return 0
