"""
repair.py — Scan, prune corrupt entries, and rebuild HNSW index
================================================================

When ChromaDB's HNSW index accumulates duplicate entries (from repeated
add() calls with the same ID), link_lists.bin can grow unbounded —
terabytes on large palaces — eventually causing segfaults.

This module provides three operations:

  scan    — find every corrupt/unfetchable ID in the palace
  prune   — delete only the corrupt IDs (surgical)
  rebuild — extract all drawers, delete the collection, recreate with
            correct HNSW settings, and upsert everything back
  signals — backfill hall/support retrieval signals for older palaces

The rebuild backs up ONLY chroma.sqlite3 (the source of truth), not the
full palace directory — so it works even when link_lists.bin is bloated.

Usage (standalone):
    python -m mempalace.repair scan [--wing X]
    python -m mempalace.repair prune --confirm
    python -m mempalace.repair rebuild
    python -m mempalace.repair signals [--dry-run]

Usage (from CLI):
    mempalace repair
    mempalace repair-scan [--wing X]
    mempalace repair-prune --confirm
"""

import argparse
import os
import shutil
import time

import chromadb

from .miner import build_retrieval_artifacts
from .palace import DRAWERS_COLLECTION_NAME, SUPPORT_COLLECTION_NAME

COLLECTION_NAME = DRAWERS_COLLECTION_NAME


def _get_palace_path():
    """Resolve palace path from config."""
    try:
        from .config import MempalaceConfig

        return MempalaceConfig().palace_path
    except Exception:
        default = os.path.join(os.path.expanduser("~"), ".mempalace", "palace")
        return default


def _paginate_ids(col, where=None):
    """Pull all IDs in a collection using pagination."""
    ids = []
    page = 1000
    offset = 0
    while True:
        try:
            r = col.get(where=where, include=[], limit=page, offset=offset)
        except Exception:
            try:
                r = col.get(where=where, include=[], limit=page)
                new_ids = [i for i in r["ids"] if i not in set(ids)]
                if not new_ids:
                    break
                ids.extend(new_ids)
                offset += len(new_ids)
                continue
            except Exception:
                break
        n = len(r["ids"]) if r["ids"] else 0
        if n == 0:
            break
        ids.extend(r["ids"])
        offset += n
        if n < page:
            break
    return ids


def _paginate_drawers(col, batch_size: int = 1000):
    """Yield raw drawer rows in stable batches.

    Repair-style operations need to scan the full collection without loading an
    arbitrarily large palace into memory at once. Keeping pagination here makes
    rebuild/backfill share one traversal path instead of each reinventing it.
    """
    offset = 0
    while True:
        batch = col.get(limit=batch_size, offset=offset, include=["documents", "metadatas"])
        ids = batch.get("ids") or []
        if not ids:
            break

        documents = batch.get("documents") or []
        metadatas = batch.get("metadatas") or []
        for drawer_id, document, metadata in zip(ids, documents, metadatas):
            yield drawer_id, document, metadata or {}

        offset += len(ids)
        if len(ids) < batch_size:
            break


def _coerce_chunk_index(value) -> int:
    """Convert stored chunk_index values to integers with a safe fallback."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _signals_need_refresh(existing_meta: dict, derived_meta: dict) -> bool:
    """Return True when stored raw metadata is missing current retrieval hints."""
    return (
        existing_meta.get("hall") != derived_meta.get("hall")
        or existing_meta.get("ingest_mode") != derived_meta.get("ingest_mode")
    )


def _batch_upsert(collection, rows: list[tuple[str, str, dict]], batch_size: int = 1000):
    """Upsert ``(id, document, metadata)`` rows in batches.

    Both rebuild and signal backfill may touch large palaces, so batching keeps
    memory growth and SQLite parameter pressure predictable.
    """
    for i in range(0, len(rows), batch_size):
        chunk = rows[i : i + batch_size]
        collection.upsert(
            ids=[row_id for row_id, _document, _metadata in chunk],
            documents=[document for _row_id, document, _metadata in chunk],
            metadatas=[metadata for _row_id, _document, metadata in chunk],
        )


def backfill_retrieval_signals(palace_path=None, dry_run: bool = False):
    """Backfill mined hall/support signals for palaces created before v3 mining.

    The raw drawers are the source of truth. This pass re-derives the current
    hall and ingest-mode metadata from those drawers, updates any stale raw
    metadata in place, and rebuilds the support collection from scratch so the
    derived helper docs match the same heuristics as fresh mining runs.
    """
    palace_path = palace_path or _get_palace_path()

    if not os.path.isdir(palace_path):
        print(f"\n  No palace found at {palace_path}")
        return {"success": False, "reason": "missing_palace"}

    print(f"\n{'=' * 55}")
    print("  MemPalace Repair — Signal Backfill")
    print(f"{'=' * 55}\n")
    print(f"  Palace: {palace_path}")

    client = chromadb.PersistentClient(path=palace_path)
    try:
        col = client.get_collection(COLLECTION_NAME)
        total = col.count()
    except Exception as e:
        print(f"  Error reading palace: {e}")
        return {"success": False, "reason": "read_error", "error": str(e)}

    print(f"  Drawers found: {total}")
    if total == 0:
        print("  Nothing to backfill.")
        return {
            "success": True,
            "dry_run": dry_run,
            "raw_scanned": 0,
            "raw_updated": 0,
            "support_docs": 0,
        }

    raw_updates: list[tuple[str, str, dict]] = []
    support_rows: list[tuple[str, str, dict]] = []
    scanned = 0

    print("\n  Deriving retrieval signals from raw drawers...")
    for drawer_id, document, metadata in _paginate_drawers(col):
        scanned += 1
        derived = build_retrieval_artifacts(
            wing=metadata.get("wing", "unknown"),
            room=metadata.get("room", "general"),
            content=document,
            source_file=metadata.get("source_file", f"recovered_{drawer_id}.txt"),
            chunk_index=_coerce_chunk_index(metadata.get("chunk_index", 0)),
            agent=metadata.get("added_by", "mempalace"),
            ingest_mode=metadata.get("ingest_mode", "project"),
            extra_metadata=metadata,
            drawer_id_override=drawer_id,
        )

        if _signals_need_refresh(metadata, derived["metadata"]):
            raw_updates.append((drawer_id, document, derived["metadata"]))

        # Rebuilding support docs from the raw corpus is simpler and safer than
        # trying to diff or patch any older support collection in place.
        if derived["support_row"] is not None:
            support_rows.append(
                (
                    derived["support_row"]["id"],
                    derived["support_row"]["document"],
                    derived["support_row"]["metadata"],
                )
            )

        if scanned % 5000 == 0:
            print(f"    scanned {scanned}/{total} drawers...")

    print(f"  Raw drawers scanned: {scanned}")
    print(f"  Raw metadata updates: {len(raw_updates)}")
    print(f"  Support docs to rebuild: {len(support_rows)}")

    stats = {
        "success": True,
        "dry_run": dry_run,
        "raw_scanned": scanned,
        "raw_updated": len(raw_updates),
        "support_docs": len(support_rows),
    }

    if dry_run:
        print("\n  DRY RUN — no writes performed.")
        print(f"\n{'=' * 55}\n")
        return stats

    if raw_updates:
        print("\n  Updating raw drawer metadata...")
        _batch_upsert(col, raw_updates)

    print("  Rebuilding support collection...")
    try:
        client.delete_collection(SUPPORT_COLLECTION_NAME)
    except Exception:
        pass

    if support_rows:
        support_col = client.create_collection(
            SUPPORT_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        _batch_upsert(support_col, support_rows)

    print("\n  Signal backfill complete.")
    print(f"  Raw metadata updated: {len(raw_updates)}")
    print(f"  Support docs rebuilt: {len(support_rows)}")
    print(f"\n{'=' * 55}\n")
    return stats


def scan_palace(palace_path=None, only_wing=None):
    """Scan the palace for corrupt/unfetchable IDs.

    Probes in batches of 100, falls back to per-ID on failure.
    Writes corrupt_ids.txt to the palace directory for the prune step.

    Returns (good_set, bad_set).
    """
    palace_path = palace_path or _get_palace_path()
    print(f"\n  Palace: {palace_path}")
    print("  Loading...")

    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_collection(COLLECTION_NAME)

    where = {"wing": only_wing} if only_wing else None
    total = col.count()
    print(f"  Collection: {COLLECTION_NAME}, total: {total:,}")
    if only_wing:
        print(f"  Scanning wing: {only_wing}")

    print("\n  Step 1: listing all IDs...")
    t0 = time.time()
    all_ids = _paginate_ids(col, where=where)
    print(f"  Found {len(all_ids):,} IDs in {time.time() - t0:.1f}s\n")

    if not all_ids:
        print("  Nothing to scan.")
        return set(), set()

    print("  Step 2: probing each ID (batches of 100)...")
    t0 = time.time()
    good_set = set()
    bad_set = set()
    batch = 100

    for i in range(0, len(all_ids), batch):
        chunk = all_ids[i : i + batch]
        try:
            r = col.get(ids=chunk, include=["documents"])
            for got in r["ids"]:
                good_set.add(got)
            for mid in chunk:
                if mid not in good_set:
                    bad_set.add(mid)
        except Exception:
            for sid in chunk:
                try:
                    r = col.get(ids=[sid], include=["documents"])
                    if r["ids"]:
                        good_set.add(sid)
                    else:
                        bad_set.add(sid)
                except Exception:
                    bad_set.add(sid)

        if (i // batch) % 50 == 0:
            elapsed = time.time() - t0
            rate = (i + batch) / max(elapsed, 0.01)
            eta = (len(all_ids) - i - batch) / max(rate, 0.01)
            print(
                f"    {i + batch:>6}/{len(all_ids):>6}  "
                f"good={len(good_set):>6}  bad={len(bad_set):>6}  "
                f"eta={eta:.0f}s"
            )

    print(f"\n  Scan complete in {time.time() - t0:.1f}s")
    print(f"  GOOD: {len(good_set):,}")
    print(f"  BAD:  {len(bad_set):,}  ({len(bad_set) / max(len(all_ids), 1) * 100:.1f}%)")

    bad_file = os.path.join(palace_path, "corrupt_ids.txt")
    with open(bad_file, "w") as f:
        for bid in sorted(bad_set):
            f.write(bid + "\n")
    print(f"\n  Bad IDs written to: {bad_file}")
    return good_set, bad_set


def prune_corrupt(palace_path=None, confirm=False):
    """Delete corrupt IDs listed in corrupt_ids.txt."""
    palace_path = palace_path or _get_palace_path()
    bad_file = os.path.join(palace_path, "corrupt_ids.txt")

    if not os.path.exists(bad_file):
        print("  No corrupt_ids.txt found — run scan first.")
        return

    with open(bad_file) as f:
        bad_ids = [line.strip() for line in f if line.strip()]
    print(f"  {len(bad_ids):,} corrupt IDs queued for deletion")

    if not confirm:
        print("\n  DRY RUN — no deletions performed.")
        print("  Re-run with --confirm to actually delete.")
        return

    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_collection(COLLECTION_NAME)
    before = col.count()
    print(f"  Collection size before: {before:,}")

    batch = 100
    deleted = 0
    failed = 0
    for i in range(0, len(bad_ids), batch):
        chunk = bad_ids[i : i + batch]
        try:
            col.delete(ids=chunk)
            deleted += len(chunk)
        except Exception:
            for sid in chunk:
                try:
                    col.delete(ids=[sid])
                    deleted += 1
                except Exception:
                    failed += 1
        if (i // batch) % 20 == 0:
            print(f"    deleted {deleted}/{len(bad_ids)}  (failed: {failed})")

    after = col.count()
    print(f"\n  Deleted: {deleted:,}")
    print(f"  Failed:  {failed:,}")
    print(f"  Collection size: {before:,} → {after:,}")


def rebuild_index(palace_path=None):
    """Rebuild the HNSW index from scratch.

    1. Extract all drawers via ChromaDB get()
    2. Back up ONLY chroma.sqlite3 (not the bloated HNSW files)
    3. Delete and recreate the collection with hnsw:space=cosine
    4. Upsert all drawers back
    """
    palace_path = palace_path or _get_palace_path()

    if not os.path.isdir(palace_path):
        print(f"\n  No palace found at {palace_path}")
        return

    print(f"\n{'=' * 55}")
    print("  MemPalace Repair — Index Rebuild")
    print(f"{'=' * 55}\n")
    print(f"  Palace: {palace_path}")

    client = chromadb.PersistentClient(path=palace_path)
    try:
        col = client.get_collection(COLLECTION_NAME)
        total = col.count()
    except Exception as e:
        print(f"  Error reading palace: {e}")
        print("  Palace may need to be re-mined from source files.")
        return

    print(f"  Drawers found: {total}")

    if total == 0:
        print("  Nothing to repair.")
        return

    # Extract all drawers in batches
    print("\n  Extracting drawers...")
    batch_size = 5000
    all_ids = []
    all_docs = []
    all_metas = []
    offset = 0
    while offset < total:
        batch = col.get(limit=batch_size, offset=offset, include=["documents", "metadatas"])
        if not batch["ids"]:
            break
        all_ids.extend(batch["ids"])
        all_docs.extend(batch["documents"])
        all_metas.extend(batch["metadatas"])
        offset += len(batch["ids"])
    print(f"  Extracted {len(all_ids)} drawers")

    # Back up ONLY the SQLite database, not the bloated HNSW files
    sqlite_path = os.path.join(palace_path, "chroma.sqlite3")
    if os.path.exists(sqlite_path):
        backup_path = sqlite_path + ".backup"
        print(f"  Backing up chroma.sqlite3 ({os.path.getsize(sqlite_path) / 1e6:.0f} MB)...")
        shutil.copy2(sqlite_path, backup_path)
        print(f"  Backup: {backup_path}")

    # Rebuild with correct HNSW settings
    print("  Rebuilding collection with hnsw:space=cosine...")
    client.delete_collection(COLLECTION_NAME)
    new_col = client.create_collection(COLLECTION_NAME, metadata={"hnsw:space": "cosine"})

    filed = 0
    for i in range(0, len(all_ids), batch_size):
        batch_ids = all_ids[i : i + batch_size]
        batch_docs = all_docs[i : i + batch_size]
        batch_metas = all_metas[i : i + batch_size]
        new_col.upsert(documents=batch_docs, ids=batch_ids, metadatas=batch_metas)
        filed += len(batch_ids)
        print(f"  Re-filed {filed}/{len(all_ids)} drawers...")

    print(f"\n  Repair complete. {filed} drawers rebuilt.")
    print("  HNSW index is now clean with cosine distance metric.")
    print(f"\n{'=' * 55}\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="MemPalace repair tools")
    p.add_argument("command", choices=["scan", "prune", "rebuild", "signals"])
    p.add_argument("--palace", default=None, help="Palace directory path")
    p.add_argument("--wing", default=None, help="Scan only this wing")
    p.add_argument("--confirm", action="store_true", help="Actually delete corrupt IDs")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview signal backfill work without writing (used with signals)",
    )
    args = p.parse_args()

    path = os.path.expanduser(args.palace) if args.palace else None

    if args.command == "scan":
        scan_palace(palace_path=path, only_wing=args.wing)
    elif args.command == "prune":
        prune_corrupt(palace_path=path, confirm=args.confirm)
    elif args.command == "rebuild":
        rebuild_index(palace_path=path)
    elif args.command == "signals":
        backfill_retrieval_signals(palace_path=path, dry_run=args.dry_run)
