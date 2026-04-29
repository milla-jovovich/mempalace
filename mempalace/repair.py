"""
repair.py — Scan, prune corrupt entries, and rebuild HNSW index
================================================================

When ChromaDB's HNSW index accumulates duplicate entries (from repeated
add() calls with the same ID), link_lists.bin can grow unbounded —
terabytes on large palaces — eventually causing segfaults.

This module provides several operations:

  status       — compare sqlite vs HNSW element counts (read-only health check)
  scan         — find every corrupt/unfetchable ID in the palace
  prune        — delete only the corrupt IDs (surgical)
  rebuild      — extract all drawers, delete the collection, recreate with
                 correct HNSW settings, and upsert everything back
  hnsw-rebuild — segment-level HNSW rebuild from data_level0.bin +
                 index_metadata.pickle; avoids re-embedding, bounded memory,
                 atomic swap-aside with rollback. Productionises the
                 recovery path from the 2026-04-19 incident. Issue #1046.
  max-seq-id   — un-poison ``max_seq_id`` rows corrupted by the legacy 0.6.x
                 BLOB shim misreading chromadb 1.5.x's native format.

The rebuild backs up ONLY chroma.sqlite3 (the source of truth), not the
full palace directory — so it works even when link_lists.bin is bloated.

Usage (standalone):
    python -m mempalace.repair status
    python -m mempalace.repair scan [--wing X]
    python -m mempalace.repair prune --confirm
    python -m mempalace.repair rebuild
    python -m mempalace.repair hnsw --segment <uuid> [--dry-run] [--purge-queue] ...
    python -m mempalace.repair max-seq-id [--segment <uuid>] [--from-sidecar <path>]

Usage (from CLI):
    mempalace repair
    mempalace repair --mode hnsw --segment <uuid>
    mempalace repair --mode max-seq-id [--segment <uuid>] [--from-sidecar <path>]

The hnsw-rebuild path imports numpy and hnswlib lazily — they are not
core mempalace dependencies (per CONTRIBUTING.md). Install only when
running this rescue command.
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import os
import pickle
import shutil
import sqlite3
import struct
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .backends.chroma import ChromaBackend, hnsw_capacity_status

logger = logging.getLogger(__name__)


COLLECTION_NAME = "mempalace_drawers"

_FLOAT32_SIZE = 4


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


def scan_palace(palace_path=None, only_wing=None):
    """Scan the palace for corrupt/unfetchable IDs.

    Probes in batches of 100, falls back to per-ID on failure.
    Writes corrupt_ids.txt to the palace directory for the prune step.

    Returns (good_set, bad_set).
    """
    palace_path = palace_path or _get_palace_path()
    print(f"\n  Palace: {palace_path}")
    print("  Loading...")

    col = ChromaBackend().get_collection(palace_path, COLLECTION_NAME)

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

    col = ChromaBackend().get_collection(palace_path, COLLECTION_NAME)
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


# ChromaDB's ``collection.get()`` enforces an internal default ``limit``
# of 10 000 rows when the caller does not pass one. We pass an explicit
# ``limit=batch_size`` below, but the underlying segment also caps reads
# during stale/quarantined-HNSW recovery flows: extraction silently stops
# at exactly 10 000 even on palaces with many more rows. Refusing to
# overwrite when this exact value comes back is the simplest signal we
# can detect without depending on chromadb internals.
CHROMADB_DEFAULT_GET_LIMIT = 10_000


class TruncationDetected(Exception):
    """Raised by :func:`check_extraction_safety` when extraction looks short.

    Carries the human-readable abort message so callers (CLI ``cmd_repair``,
    ``rebuild_index``) can print and exit consistently without re-deriving
    the wording.
    """

    def __init__(self, message: str, sqlite_count: "int | None", extracted: int):
        super().__init__(message)
        self.message = message
        self.sqlite_count = sqlite_count
        self.extracted = extracted


def check_extraction_safety(
    palace_path: str, extracted: int, confirm_truncation_ok: bool = False
) -> None:
    """Cross-check that ``extracted`` matches the SQLite ground truth.

    Two signals trip the guard:

    1. **Strong** — ``chroma.sqlite3`` reports more drawers than were
       extracted. This is the user-reported #1208 case: 67 580 on disk,
       10 000 came back through the chromadb collection layer, repair
       would have destroyed the difference.
    2. **Weak** — extracted count equals exactly ``CHROMADB_DEFAULT_GET_LIMIT``
       AND the SQLite check couldn't run (schema drift, locked file).
       Hitting the chromadb default ``get()`` cap exactly is suspicious
       enough to refuse without explicit acknowledgement.

    Raises :class:`TruncationDetected` with a printable message when the
    guard fires. Does nothing on safe extractions or when
    ``confirm_truncation_ok`` is set.
    """
    if confirm_truncation_ok:
        return

    sqlite_count = sqlite_drawer_count(palace_path)
    cap_signal = extracted == CHROMADB_DEFAULT_GET_LIMIT

    if sqlite_count is not None and sqlite_count > extracted:
        loss = sqlite_count - extracted
        pct = 100 * loss / sqlite_count
        message = (
            f"\n  ABORT: chroma.sqlite3 reports {sqlite_count:,} drawers but only {extracted:,}\n"
            "  came back through the chromadb collection layer. The segment metadata is\n"
            "  stale (often after manual HNSW quarantine) — proceeding would silently\n"
            f"  destroy {loss:,} drawers (~{pct:.0f}%).\n"
            "\n"
            "  Recovery options:\n"
            "    1. Restore from your most recent palace backup, then re-mine.\n"
            "    2. Direct-extract from chroma.sqlite3 (rows are still on disk) and\n"
            "       rebuild the palace from source files.\n"
            "    3. If you have independently confirmed the palace really contains only\n"
            f"       {extracted:,} drawers, re-run with --confirm-truncation-ok.\n"
        )
        raise TruncationDetected(message, sqlite_count, extracted)

    if cap_signal and sqlite_count is None:
        message = (
            f"\n  ABORT: extracted exactly {CHROMADB_DEFAULT_GET_LIMIT:,} drawers, which matches\n"
            "  ChromaDB's internal default get() limit. The on-disk SQLite count couldn't\n"
            "  be cross-checked from this Python context, so we can't tell whether the\n"
            f"  palace genuinely holds {CHROMADB_DEFAULT_GET_LIMIT:,} rows or whether extraction was\n"
            "  silently capped. Refusing to overwrite the palace.\n"
            "\n"
            "  If you have independently confirmed (e.g. via direct sqlite3 query) that\n"
            f"  the palace really contains exactly {CHROMADB_DEFAULT_GET_LIMIT:,} drawers, re-run with\n"
            "  --confirm-truncation-ok.\n"
        )
        raise TruncationDetected(message, sqlite_count, extracted)


def sqlite_drawer_count(palace_path: str) -> "int | None":
    """Count rows in ``chroma.sqlite3.embeddings`` for the drawers collection.

    Used as an independent ground-truth check against the chromadb
    collection-layer ``count()`` / ``get()``: when the on-disk SQLite
    row count exceeds the extraction count, the segment metadata is
    stale and repair would destroy the difference.

    Returns ``None`` when the schema isn't readable (chromadb version
    drift, missing tables, locked file). Callers treat ``None`` as
    "unknown" and fall back to the cap-detection check.
    """
    sqlite_path = os.path.join(palace_path, "chroma.sqlite3")
    if not os.path.exists(sqlite_path):
        return None
    try:
        import sqlite3

        conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
        try:
            row = conn.execute(
                """
                SELECT COUNT(*)
                FROM embeddings e
                JOIN segments s ON e.segment_id = s.id
                JOIN collections c ON s.collection = c.id
                WHERE c.name = ?
                """,
                (COLLECTION_NAME,),
            ).fetchone()
            return int(row[0]) if row and row[0] is not None else None
        finally:
            conn.close()
    except Exception:
        # chromadb schema differs by version (segments / collections column
        # names occasionally rename). Silent fallback is correct here —
        # the cap-detection check still catches the user-reported case.
        return None


def rebuild_index(palace_path=None, confirm_truncation_ok: bool = False):
    """Rebuild the HNSW index from scratch.

    1. Extract all drawers via ChromaDB get()
    2. Cross-check against the SQLite ground truth (#1208 guard)
    3. Back up ONLY chroma.sqlite3 (not the bloated HNSW files)
    4. Delete and recreate the collection with hnsw:space=cosine
    5. Upsert all drawers back

    ``confirm_truncation_ok`` overrides the safety guard from step 2.
    Set to ``True`` only when you have independently verified that the
    palace genuinely contains exactly the extracted number of drawers
    (typically only a concern for palaces sized at exactly 10 000 rows).
    """
    palace_path = palace_path or _get_palace_path()

    if not os.path.isdir(palace_path):
        print(f"\n  No palace found at {palace_path}")
        return

    print(f"\n{'=' * 55}")
    print("  MemPalace Repair — Index Rebuild")
    print(f"{'=' * 55}\n")
    print(f"  Palace: {palace_path}")

    backend = ChromaBackend()
    try:
        col = backend.get_collection(palace_path, COLLECTION_NAME)
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

    # ── #1208 guard ──────────────────────────────────────────────────
    # Refuse to ``delete_collection`` + rebuild when extraction looks
    # short of the SQLite ground truth (or when extraction == chromadb
    # default get() cap and the SQLite check couldn't run).
    try:
        check_extraction_safety(palace_path, len(all_ids), confirm_truncation_ok)
    except TruncationDetected as e:
        print(e.message)
        return

    # Back up ONLY the SQLite database, not the bloated HNSW files
    sqlite_path = os.path.join(palace_path, "chroma.sqlite3")
    backup_path = sqlite_path + ".backup"
    if os.path.exists(sqlite_path):
        print(f"  Backing up chroma.sqlite3 ({os.path.getsize(sqlite_path) / 1e6:.0f} MB)...")
        shutil.copy2(sqlite_path, backup_path)
        print(f"  Backup: {backup_path}")

    # Rebuild with correct HNSW settings
    print("  Rebuilding collection with hnsw:space=cosine...")
    backend.delete_collection(palace_path, COLLECTION_NAME)
    new_col = backend.create_collection(palace_path, COLLECTION_NAME)

    filed = 0
    try:
        for i in range(0, len(all_ids), batch_size):
            batch_ids = all_ids[i : i + batch_size]
            batch_docs = all_docs[i : i + batch_size]
            batch_metas = all_metas[i : i + batch_size]
            new_col.upsert(documents=batch_docs, ids=batch_ids, metadatas=batch_metas)
            filed += len(batch_ids)
            print(f"  Re-filed {filed}/{len(all_ids)} drawers...")
    except Exception as e:
        print(f"\n  ERROR during rebuild: {e}")
        print(f"  Only {filed}/{len(all_ids)} drawers were re-filed.")
        if os.path.exists(backup_path):
            print(f"  Restoring from backup: {backup_path}")
            backend.delete_collection(palace_path, COLLECTION_NAME)
            shutil.copy2(backup_path, sqlite_path)
            print("  Backup restored. Palace is back to pre-repair state.")
        else:
            print("  No backup available. Re-mine from source files to recover.")
        raise

    print(f"\n  Repair complete. {filed} drawers rebuilt.")
    print("  HNSW index is now clean with cosine distance metric.")
    print(f"\n{'=' * 55}\n")


def status(palace_path=None) -> dict:
    """Read-only health check: compare sqlite vs HNSW element counts.

    Catches the #1222 failure mode where chromadb's HNSW segment freezes
    at a stale ``max_elements`` while sqlite keeps accumulating rows.
    Once the divergence is large enough, every tool call segfaults when
    chromadb tries to load the undersized HNSW. Running ``mempalace
    repair-status`` *before* opening the segment lets the operator
    discover the problem without crashing the MCP server.

    The check itself never opens a chromadb client and never imports
    hnswlib — it reads ``chroma.sqlite3`` and ``index_metadata.pickle``
    directly via :func:`mempalace.backends.chroma.hnsw_capacity_status`.

    Returns the capacity-status dict (also printed). Returns a dict with
    ``status="unknown"`` when no palace exists at the given path.
    """
    palace_path = palace_path or _get_palace_path()
    print(f"\n{'=' * 55}")
    print("  MemPalace Repair — Status")
    print(f"{'=' * 55}\n")
    print(f"  Palace: {palace_path}")

    if not os.path.isdir(palace_path):
        print("  No palace found.\n")
        return {"status": "unknown", "message": "no palace at path"}

    drawers = hnsw_capacity_status(palace_path, "mempalace_drawers")
    closets = hnsw_capacity_status(palace_path, "mempalace_closets")

    for label, info in (("drawers", drawers), ("closets", closets)):
        print(f"\n  [{label}]")
        if info.get("segment_id"):
            print(f"    segment id:     {info['segment_id']}")
        if info["sqlite_count"] is None:
            print("    sqlite count:   (unreadable)")
        else:
            print(f"    sqlite count:   {info['sqlite_count']:,}")
        if info["hnsw_count"] is None:
            print("    hnsw count:     (no flushed metadata yet)")
        else:
            print(f"    hnsw count:     {info['hnsw_count']:,}")
        if info["divergence"] is not None:
            print(f"    divergence:     {info['divergence']:,}")
        marker = "DIVERGED" if info["diverged"] else info["status"].upper()
        print(f"    status:         {marker}")
        if info["message"]:
            print(f"    note:           {info['message']}")

    diverged_segments = [
        (label, info["segment_id"])
        for label, info in (("drawers", drawers), ("closets", closets))
        if info["diverged"] and info.get("segment_id")
    ]
    if drawers["diverged"] or closets["diverged"]:
        print("\n  Recommended next steps:")
        if diverged_segments:
            print(
                "    - Targeted segment rebuild (faster, no re-embed):"
                " `mempalace repair --mode hnsw --segment <uuid>`"
            )
            for label, seg_id in diverged_segments:
                print(f"        {label}: {seg_id}")
        print("    - Full-palace rebuild (re-embeds, slower): `mempalace repair`")
    print()
    return {"drawers": drawers, "closets": closets}


# ---------------------------------------------------------------------------
# hnsw-mode: segment-level rebuild (issue #1046)
# ---------------------------------------------------------------------------


class RebuildVerificationError(RuntimeError):
    """Raised when the rebuilt index fails its self-query sanity check."""


@dataclass
class _HnswHeader:
    """Subset of the chromadb-wrapped hnswlib header we rely on.

    Byte layout (little-endian) of the first 100 bytes:
      off  0:  u32  format_version
      off  4:  u64  offset_level0
      off 12:  u64  max_elements
      off 20:  u64  cur_count
      off 28:  u64  size_per_element
      off 36:  u64  label_offset
      off 44:  u64  offset_data
      off 52:  i32  maxlevel
      off 56:  u32  enterpoint_node
      off 60:  u64  maxM
      off 68:  u64  maxM0
      off 76:  u64  M
      off 84:  f64  mult
      off 92:  u64  ef_construction
    """

    format_version: int
    max_elements: int
    cur_count: int
    size_per_element: int
    label_offset: int
    offset_data: int
    M: int
    ef_construction: int
    dim: int


def _parse_hnsw_header(data: bytes) -> _HnswHeader:
    """Parse the 100-byte hnswlib header.

    Derives ``dim`` from ``size_per_element - offset_data - 8`` (trailing
    8 bytes are the u64 label), divided by 4 (float32).
    """
    if len(data) < 100:
        raise ValueError(f"HNSW header too short: {len(data)} bytes")

    format_version = struct.unpack_from("<I", data, 0)[0]
    max_elements = struct.unpack_from("<Q", data, 12)[0]
    cur_count = struct.unpack_from("<Q", data, 20)[0]
    size_per_element = struct.unpack_from("<Q", data, 28)[0]
    label_offset = struct.unpack_from("<Q", data, 36)[0]
    offset_data = struct.unpack_from("<Q", data, 44)[0]
    M = struct.unpack_from("<Q", data, 76)[0]
    ef_construction = struct.unpack_from("<Q", data, 92)[0]

    vector_bytes = size_per_element - offset_data - 8
    if vector_bytes <= 0 or vector_bytes % _FLOAT32_SIZE != 0:
        raise ValueError(
            f"Inferred vector width is invalid: "
            f"size_per_element={size_per_element}, offset_data={offset_data}"
        )
    dim = vector_bytes // _FLOAT32_SIZE

    return _HnswHeader(
        format_version=format_version,
        max_elements=max_elements,
        cur_count=cur_count,
        size_per_element=size_per_element,
        label_offset=label_offset,
        offset_data=offset_data,
        M=M,
        ef_construction=ef_construction,
        dim=dim,
    )


def _extract_vectors(data: bytes, hdr: _HnswHeader):
    """Return ``(labels, vectors)`` as numpy arrays of length ``cur_count``."""
    import numpy as np

    n = hdr.cur_count
    stride = hdr.size_per_element
    expected = hdr.max_elements * stride
    if len(data) < expected:
        raise ValueError(f"data_level0.bin is {len(data)} bytes, expected >= {expected}")

    labels = np.empty(n, dtype=np.uint64)
    vectors = np.empty((n, hdr.dim), dtype=np.float32)
    vec_end = hdr.offset_data + hdr.dim * _FLOAT32_SIZE
    for i in range(n):
        slot = i * stride
        vectors[i] = np.frombuffer(data[slot + hdr.offset_data : slot + vec_end], dtype=np.float32)
        labels[i] = struct.unpack_from("<Q", data, slot + hdr.label_offset)[0]
    return labels, vectors


def _sanitize_vectors(labels, vectors):
    """Drop ``label == 0`` and deduplicate, keeping the last occurrence.

    hnswlib rejects duplicate labels; drift sometimes leaves zero-labelled
    slots. Reverse-unique preserves the most-recent write for each label,
    which is the copy that matches the pickle mapping.
    """
    import numpy as np

    if len(labels) == 0:
        return labels, vectors

    n = len(labels)
    rev_idx = np.arange(n)[::-1]
    _, first_rev = np.unique(labels[::-1], return_index=True)
    keep = np.sort(rev_idx[first_rev])
    labels = labels[keep]
    vectors = vectors[keep]

    zero_mask = labels == 0
    if zero_mask.any():
        labels = labels[~zero_mask]
        vectors = vectors[~zero_mask]
    return labels, vectors


def _detect_space(palace_path: str, segment: str) -> str:
    """Look up ``hnsw:space`` for the collection that owns ``segment``.

    Falls back to ``"l2"`` (hnswlib's default) with a warning if absent —
    matches ChromaDB's default when no metadata is recorded.
    """
    db_path = os.path.join(palace_path, "chroma.sqlite3")
    if not os.path.isfile(db_path):
        logger.warning("No chroma.sqlite3 at %s — defaulting space to l2", palace_path)
        return "l2"

    row = None
    with sqlite3.connect(db_path) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(collection_metadata)").fetchall()]
        value_col = "str_value" if "str_value" in cols else "string_value"
        try:
            row = conn.execute(
                f"""
                SELECT cm.{value_col}
                FROM segments s
                JOIN collection_metadata cm ON cm.collection_id = s.collection
                WHERE s.id = ? AND cm.key = 'hnsw:space'
                """,
                (segment,),
            ).fetchone()
        except sqlite3.OperationalError:
            row = None

    if row and row[0]:
        return row[0]
    logger.warning("No hnsw:space for segment %s — defaulting to l2 (ChromaDB default)", segment)
    return "l2"


def _meta_get(meta, key):
    """Read a field from index_metadata (0.6.x attr-object or 1.5.x dict)."""
    return meta[key] if isinstance(meta, dict) else getattr(meta, key)


def _meta_set(meta, key, value):
    """Write a field to index_metadata (0.6.x attr-object or 1.5.x dict)."""
    if isinstance(meta, dict):
        meta[key] = value
    else:
        setattr(meta, key, value)


def _reconcile_with_pickle(labels, pickle_path: str):
    """Intersect HNSW labels with the pickle's ``label_to_id`` mapping.

    Returns ``(keep_mask, orphan_hnsw_labels, stale_pickle_ids, meta)``
    where ``meta`` has had its three mapping tables pruned to the healthy
    set (caller persists it afterwards).
    """
    import numpy as np

    with open(pickle_path, "rb") as f:
        meta = pickle.load(f)

    label_to_id = _meta_get(meta, "label_to_id")
    id_to_label = _meta_get(meta, "id_to_label")
    id_to_seq_id = _meta_get(meta, "id_to_seq_id")

    mapped_labels = set(label_to_id.keys())
    hnsw_labels = set(int(x) for x in labels)
    healthy = hnsw_labels & mapped_labels
    orphan_hnsw = hnsw_labels - mapped_labels
    stale_uids = [uid for lbl, uid in label_to_id.items() if lbl not in healthy]
    dropped_uid_set = set(stale_uids)

    _meta_set(
        meta,
        "label_to_id",
        {lbl: uid for lbl, uid in label_to_id.items() if lbl in healthy},
    )
    _meta_set(
        meta,
        "id_to_label",
        {uid: lbl for uid, lbl in id_to_label.items() if uid not in dropped_uid_set},
    )
    _meta_set(
        meta,
        "id_to_seq_id",
        {uid: sid for uid, sid in id_to_seq_id.items() if uid not in dropped_uid_set},
    )

    keep_mask = np.fromiter((int(x) in healthy for x in labels), dtype=bool, count=len(labels))
    return keep_mask, sorted(orphan_hnsw), stale_uids, meta


def _compute_max_elements(count: int, override: Optional[int]) -> int:
    """Pick the ``max_elements`` value for the new index.

    Default ``max(count * 1.3, 200_000)`` leaves headroom so the next
    flush does not auto-resize (the very bug #2594 we are fixing).
    """
    if override is not None:
        if override < count:
            raise ValueError(
                f"--max-elements={override} is smaller than healthy vector count {count}"
            )
        return int(override)
    return max(int(count * 1.3), 200_000)


def _build_persistent_index(
    vectors,
    labels,
    *,
    space: str,
    dim: int,
    max_elements: int,
    persistence_location: str,
    M: int = 16,
    ef_construction: int = 100,
):
    """Build a persistent hnswlib index and write it to ``persistence_location``."""
    import hnswlib

    idx = hnswlib.Index(space=space, dim=dim)
    idx.init_index(
        max_elements=max_elements,
        ef_construction=ef_construction,
        M=M,
        is_persistent_index=True,
        persistence_location=persistence_location,
    )
    idx.set_num_threads(1)

    n = len(labels)
    chunk = 10_000
    for i in range(0, n, chunk):
        j = min(i + chunk, n)
        idx.add_items(vectors[i:j], labels[i:j], num_threads=1)
    idx.persist_dirty()
    return idx


def _self_query_verify(index, sample_vectors, sample_labels) -> None:
    """Verify the rebuilt index returns each sample as its own top-1 neighbor."""
    if len(sample_labels) == 0:
        return
    labels, _dists = index.knn_query(sample_vectors, k=1)
    flat = labels.flatten()
    expected = [int(x) for x in sample_labels]
    got = [int(x) for x in flat]
    if got != expected:
        raise RebuildVerificationError(
            f"Self-query mismatch: expected top-1 labels {expected}, got {got}"
        )


def _atomic_swap_segment(tmpdir: str, segment_dir: str) -> None:
    """Rename-aside swap: move live out of the way, drop new in, rollback on failure."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stale = f"{segment_dir}.old-{stamp}"
    os.rename(segment_dir, stale)
    try:
        os.replace(tmpdir, segment_dir)
    except OSError:
        try:
            os.rename(stale, segment_dir)
        except OSError:
            logger.exception("Swap failed AND rollback failed. Live segment left at %s", stale)
        raise
    shutil.rmtree(stale, ignore_errors=True)


def _backup_segment(palace_path: str, segment: str, timestamp: str) -> str:
    """Copy chroma.sqlite3 plus the small HNSW files (skip bloated link_lists.bin)."""
    seg_dir = os.path.join(palace_path, segment)
    backup_dir = os.path.join(palace_path, f"{segment}.hnsw-backup-{timestamp}")
    os.makedirs(backup_dir, exist_ok=True)

    sqlite_path = os.path.join(palace_path, "chroma.sqlite3")
    if os.path.isfile(sqlite_path):
        shutil.copy2(sqlite_path, os.path.join(backup_dir, "chroma.sqlite3"))

    for fname in ("header.bin", "data_level0.bin", "index_metadata.pickle", "length.bin"):
        src = os.path.join(seg_dir, fname)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(backup_dir, fname))
    return backup_dir


def _purge_segment_queue(palace_path: str, segment: str) -> int:
    """Delete ``embeddings_queue`` rows for the collection that owns ``segment``.

    ``topic`` is ``persistent://default/default/<COLLECTION_UUID>`` — we look
    up the collection UUID via ``segments.collection`` and match by pattern.
    """
    db_path = os.path.join(palace_path, "chroma.sqlite3")
    if not os.path.isfile(db_path):
        return 0
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT collection FROM segments WHERE id = ?", (segment,)).fetchone()
        if not row:
            return 0
        collection_uuid = row[0]
        cur = conn.execute(
            "DELETE FROM embeddings_queue WHERE topic LIKE ?",
            (f"%{collection_uuid}%",),
        )
        deleted = cur.rowcount
        conn.commit()
    return int(deleted or 0)


def _quarantine_orphans(palace_path: str, stale_ids, orphan_labels) -> str:
    """Append dropped UUIDs + orphan HNSW labels to a sidecar JSON file."""
    sidecar = os.path.join(palace_path, "quarantined_orphans.json")
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "stale_pickle_ids": list(stale_ids),
        "orphan_hnsw_labels": [int(x) for x in orphan_labels],
    }
    history: list = []
    if os.path.isfile(sidecar):
        try:
            with open(sidecar) as f:
                history = json.load(f)
            if not isinstance(history, list):
                history = [history]
        except Exception:
            history = []
    history.append(entry)
    with open(sidecar, "w") as f:
        json.dump(history, f, indent=2)
    return sidecar


# ---------------------------------------------------------------------------
# max-seq-id mode: un-poison max_seq_id rows corrupted by the old shim
# ---------------------------------------------------------------------------


def _close_chroma_handles(palace_path: str) -> None:
    """Drop ChromaBackend + chromadb singleton caches so OS mmap handles release."""
    try:
        ChromaBackend().close_palace(palace_path)
    except Exception:
        pass
    try:
        from chromadb.api.client import SharedSystemClient

        SharedSystemClient.clear_system_cache()
    except Exception:
        pass
    gc.collect()


class MaxSeqIdVerificationError(RuntimeError):
    """Raised when post-repair detection still sees poisoned rows."""


#: Any ``max_seq_id.seq_id`` above this is unreachable by a real palace.
#: Clean values are bounded by the embeddings_queue's monotonic counter (<1e10
#: in practice), and 2**53 is the float64 exact-integer ceiling. Poisoned
#: values from the 0.6.x shim misinterpreting chromadb 1.5.x's
#: ``b'\x11\x11' + 6 ASCII digits`` format start at ~1.23e18, so anything
#: above the threshold is confidently a shim-poisoning artefact.
MAX_SEQ_ID_SANITY_THRESHOLD = 1 << 53


def _detect_poisoned_max_seq_ids(
    db_path: str,
    *,
    segment: Optional[str] = None,
    threshold: int = MAX_SEQ_ID_SANITY_THRESHOLD,
) -> list[tuple[str, int]]:
    """Return ``[(segment_id, poisoned_seq_id), ...]`` for rows above threshold.

    If ``segment`` is given, the detection is restricted to that segment id
    (still only returning it if it actually exceeds the threshold).
    """
    with sqlite3.connect(db_path) as conn:
        if segment is not None:
            rows = conn.execute(
                "SELECT segment_id, seq_id FROM max_seq_id WHERE segment_id = ? AND seq_id > ?",
                (segment, threshold),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT segment_id, seq_id FROM max_seq_id WHERE seq_id > ?",
                (threshold,),
            ).fetchall()
    return [(str(sid), int(val)) for sid, val in rows]


def _compute_heuristic_seq_id(cur: sqlite3.Cursor, segment_id: str) -> int:
    """Return ``MAX(embeddings.seq_id)`` over the collection owning ``segment_id``.

    Matches the METADATA segment's pre-poison value exactly (its max equals
    the collection-wide embeddings max). For the sibling VECTOR segment the
    value is a few seq_ids ahead of its own pre-poison max; the queue
    treats that as "already consumed", skipping a small window of
    already-indexed embeddings on next subscribe. That is an acceptable
    loss vs. resetting to 0 (which would re-process the entire queue and
    risk HNSW bloat from issue #1046).
    """
    row = cur.execute(
        """
        SELECT MAX(e.seq_id)
        FROM embeddings e
        JOIN segments s ON e.segment_id = s.id
        WHERE s.collection = (
            SELECT collection FROM segments WHERE id = ?
        )
        """,
        (segment_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return 0
    return int(row[0])


def _read_sidecar_seq_ids(sidecar_path: str) -> dict[str, int]:
    """Load ``{segment_id: seq_id}`` from a sidecar DB's ``max_seq_id`` table.

    Rejects sidecar files whose ``max_seq_id.seq_id`` is itself BLOB-typed
    — a sidecar that old predates chromadb's type normalisation and is not
    a trustworthy restoration source.
    """
    if not os.path.isfile(sidecar_path):
        raise FileNotFoundError(f"Sidecar database not found: {sidecar_path}")
    out: dict[str, int] = {}
    with sqlite3.connect(sidecar_path) as conn:
        rows = conn.execute("SELECT segment_id, seq_id, typeof(seq_id) FROM max_seq_id").fetchall()
    for segment_id, seq_id, kind in rows:
        if kind == "blob":
            raise ValueError(
                f"Sidecar has BLOB-typed seq_id for {segment_id}; refusing to use it. "
                "Pass a sidecar that was already migrated to INTEGER rows."
            )
        out[str(segment_id)] = int(seq_id)
    return out


def repair_max_seq_id(
    palace_path: str,
    *,
    segment: Optional[str] = None,
    from_sidecar: Optional[str] = None,
    threshold: int = MAX_SEQ_ID_SANITY_THRESHOLD,
    backup: bool = True,
    dry_run: bool = False,
    assume_yes: bool = False,
) -> dict:
    """Un-poison ``max_seq_id`` rows corrupted by ``_fix_blob_seq_ids`` misfire.

    The old shim ran ``int.from_bytes(blob, 'big')`` across every BLOB
    ``max_seq_id.seq_id`` row, including chromadb 1.5.x's native
    ``b'\\x11\\x11' + ASCII digits`` format. That conversion yields a
    ~1.23e18 integer that silently suppresses every subsequent
    ``embeddings_queue`` write for the affected segment. This command
    restores clean values either from a pre-corruption sidecar DB
    (exact) or heuristically (``MAX(embeddings.seq_id)`` over the owning
    collection).
    """
    from .migrate import confirm_destructive_action, contains_palace_database

    palace_path = os.path.abspath(os.path.expanduser(palace_path))
    db_path = os.path.join(palace_path, "chroma.sqlite3")

    result: dict = {
        "palace_path": palace_path,
        "dry_run": dry_run,
        "aborted": False,
        "segment_repaired": [],
        "before": {},
        "after": {},
        "backup": None,
    }

    print(f"\n{'=' * 55}")
    print("  MemPalace Repair — max_seq_id Un-poison")
    print(f"{'=' * 55}\n")
    print(f"  Palace:  {palace_path}")
    if segment:
        print(f"  Segment: {segment}")
    if from_sidecar:
        print(f"  Sidecar: {from_sidecar}")

    if not os.path.isdir(palace_path):
        print(f"  No palace found at {palace_path}")
        result["aborted"] = True
        result["reason"] = "palace-missing"
        return result
    if not contains_palace_database(palace_path):
        print(f"  No palace database at {palace_path}")
        result["aborted"] = True
        result["reason"] = "db-missing"
        return result

    poisoned = _detect_poisoned_max_seq_ids(db_path, segment=segment, threshold=threshold)
    if not poisoned:
        print("  No poisoned max_seq_id rows detected. Nothing to do.")
        print(f"\n{'=' * 55}\n")
        return result

    sidecar_map: dict[str, int] = {}
    if from_sidecar:
        sidecar_map = _read_sidecar_seq_ids(from_sidecar)

    plan: list[tuple[str, int, int]] = []
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        for seg_id, old_val in poisoned:
            if from_sidecar:
                if seg_id not in sidecar_map:
                    print(f"  Skipped segment {seg_id}: no sidecar entry")
                    continue
                new_val = sidecar_map[seg_id]
            else:
                new_val = _compute_heuristic_seq_id(cur, seg_id)
            plan.append((seg_id, old_val, new_val))
            result["before"][seg_id] = old_val
            result["after"][seg_id] = new_val

    print()
    print("  Report")
    print(f"    poisoned rows        {len(poisoned):>6}")
    print(f"    planned repairs      {len(plan):>6}")
    source = "sidecar" if from_sidecar else "heuristic (collection MAX)"
    print(f"    clean-value source   {source}")
    for seg_id, old_val, new_val in plan:
        print(f"    {seg_id}  {old_val}  →  {new_val}")

    if dry_run:
        print("\n  DRY RUN — no rows modified.\n" + "=" * 55 + "\n")
        return result

    if not plan:
        print("  No actionable repairs.")
        print(f"\n{'=' * 55}\n")
        return result

    if not confirm_destructive_action("Repair max_seq_id", palace_path, assume_yes=assume_yes):
        result["aborted"] = True
        result["reason"] = "user-aborted"
        return result

    if backup:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = os.path.join(palace_path, f"chroma.sqlite3.max-seq-id-backup-{timestamp}")
        shutil.copy2(db_path, backup_path)
        result["backup"] = backup_path
        print(f"  Backup:  {backup_path}")

    _close_chroma_handles(palace_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute("BEGIN")
        try:
            conn.executemany(
                "UPDATE max_seq_id SET seq_id = ? WHERE segment_id = ?",
                [(new_val, seg_id) for seg_id, _old, new_val in plan],
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    remaining = _detect_poisoned_max_seq_ids(db_path, segment=segment, threshold=threshold)
    if remaining:
        raise MaxSeqIdVerificationError(
            f"Post-repair detection still found {len(remaining)} poisoned row(s): "
            f"{[sid for sid, _ in remaining]}. Backup at {result['backup']}."
        )

    result["segment_repaired"] = [seg_id for seg_id, _old, _new in plan]
    print(f"\n  Repair complete. {len(plan)} row(s) restored.")
    print(f"  Backup:  {result['backup'] or '(skipped)'}")
    print(f"\n{'=' * 55}\n")
    return result


# ---------------------------------------------------------------------------
# hnsw-mode driver: rebuild a single segment from data_level0.bin (issue #1046)
# ---------------------------------------------------------------------------


def _peak_memory_mb() -> float:
    """Return the process peak RSS in MB (mac returns bytes, linux kilobytes)."""
    try:
        import resource
        import sys

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return peak / (1024 * 1024)
        return peak / 1024
    except Exception:
        return 0.0


def rebuild_hnsw_segment(
    palace_path: str,
    *,
    segment: str,
    max_elements: Optional[int] = None,
    backup: bool = True,
    purge_queue: bool = False,
    quarantine_orphans: bool = False,
    dry_run: bool = False,
    assume_yes: bool = False,
) -> dict:
    """Rebuild a single HNSW segment from on-disk ``data_level0.bin`` + pickle.

    Avoids re-embedding by reading vectors straight out of the persistent
    HNSW data file. Atomic swap-aside with rollback keeps the live palace
    untouched on any failure. Issue #1046.

    On successful completion the palace is healthy on disk; if the running
    MCP server still has ``_vector_disabled`` set from a prior #1222 capacity
    probe, calling ``mempalace_reconnect`` will refresh the probe and clear
    the flag — the runtime check is the authoritative source of truth and
    re-runs at every reconnect.
    """
    from .migrate import confirm_destructive_action, contains_palace_database

    palace_path = os.path.abspath(os.path.expanduser(palace_path))
    seg_dir = os.path.join(palace_path, segment)
    header_path = os.path.join(seg_dir, "header.bin")
    data_path = os.path.join(seg_dir, "data_level0.bin")
    pickle_path = os.path.join(seg_dir, "index_metadata.pickle")

    result: dict = {
        "palace_path": palace_path,
        "segment": segment,
        "dry_run": dry_run,
        "aborted": False,
    }

    print(f"\n{'=' * 55}")
    print("  MemPalace Repair — HNSW Segment Rebuild")
    print(f"{'=' * 55}\n")
    print(f"  Palace:  {palace_path}")
    print(f"  Segment: {segment}")

    if not os.path.isdir(palace_path):
        print(f"  No palace found at {palace_path}")
        result["aborted"] = True
        result["reason"] = "palace-missing"
        return result
    if not contains_palace_database(palace_path):
        print(f"  No palace database at {palace_path}")
        result["aborted"] = True
        result["reason"] = "db-missing"
        return result
    if not os.path.isdir(seg_dir):
        print(f"  Segment directory not found: {seg_dir}")
        result["aborted"] = True
        result["reason"] = "segment-missing"
        return result
    if not os.path.isfile(data_path):
        print(f"  data_level0.bin not found in {seg_dir}")
        result["aborted"] = True
        result["reason"] = "data-missing"
        return result

    try:
        import numpy  # noqa: F401
        import hnswlib  # noqa: F401
    except ImportError as e:
        print(f"  Required dependency missing: {e}")
        print("  Install with: pip install numpy chroma-hnswlib")
        result["aborted"] = True
        result["reason"] = "deps-missing"
        return result

    header_src = header_path if os.path.isfile(header_path) else data_path
    with open(header_src, "rb") as f:
        header_bytes = f.read(100)
    hdr = _parse_hnsw_header(header_bytes)
    print(
        f"  Header:  dim={hdr.dim}, cur_count={hdr.cur_count:,}, "
        f"max_elements={hdr.max_elements:,}, size_per_element={hdr.size_per_element}"
    )

    space = _detect_space(palace_path, segment)
    print(f"  Space:   {space}")

    with open(data_path, "rb") as f:
        data_bytes = f.read()
    labels, vectors = _extract_vectors(data_bytes, hdr)
    del data_bytes
    raw_n = len(labels)
    labels, vectors = _sanitize_vectors(labels, vectors)
    sanitized_n = len(labels)

    orphan_hnsw: list = []
    stale_uids: list = []
    meta = None
    if os.path.isfile(pickle_path):
        keep_mask, orphan_hnsw, stale_uids, meta = _reconcile_with_pickle(labels, pickle_path)
        labels = labels[keep_mask]
        vectors = vectors[keep_mask]
    else:
        logger.warning("No index_metadata.pickle for segment %s — skipping reconcile", segment)

    healthy_n = len(labels)
    new_max = _compute_max_elements(healthy_n, max_elements)

    data_bytes_size = os.path.getsize(data_path)
    link_lists_path = os.path.join(seg_dir, "link_lists.bin")
    link_lists_size = os.path.getsize(link_lists_path) if os.path.isfile(link_lists_path) else 0

    print()
    print("  Report")
    print(f"    raw labels          {raw_n:>10,}")
    print(f"    after dedup/zeros   {sanitized_n:>10,}")
    print(f"    healthy (in pickle) {healthy_n:>10,}")
    print(f"    orphan HNSW labels  {len(orphan_hnsw):>10,}")
    print(f"    stale pickle ids    {len(stale_uids):>10,}")
    print(f"    new max_elements    {new_max:>10,}")
    print(f"    data_level0.bin     {data_bytes_size:>10,} bytes")
    print(f"    link_lists.bin      {link_lists_size:>10,} bytes (will be rebuilt)")

    result.update(
        {
            "raw_labels": raw_n,
            "sanitized_labels": sanitized_n,
            "healthy_labels": healthy_n,
            "orphan_hnsw_labels": len(orphan_hnsw),
            "stale_pickle_ids": len(stale_uids),
            "max_elements": new_max,
            "data_bytes": data_bytes_size,
            "link_lists_bytes": link_lists_size,
            "space": space,
            "dim": hdr.dim,
        }
    )

    if dry_run:
        print("\n  DRY RUN — no files modified.\n" + "=" * 55 + "\n")
        return result

    if healthy_n == 0:
        print("  No healthy labels to rebuild — aborting.")
        result["aborted"] = True
        result["reason"] = "no-healthy-labels"
        return result

    if not confirm_destructive_action("Rebuild HNSW segment", palace_path, assume_yes=assume_yes):
        result["aborted"] = True
        result["reason"] = "user-aborted"
        return result

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    backup_dir: Optional[str] = None
    if backup:
        backup_dir = _backup_segment(palace_path, segment, timestamp)
        print(f"  Backup:  {backup_dir}")

    _close_chroma_handles(palace_path)

    tmpdir = tempfile.mkdtemp(prefix="mempalace_hnsw_", dir=palace_path)
    t0 = time.time()
    try:
        idx = _build_persistent_index(
            vectors,
            labels,
            space=space,
            dim=hdr.dim,
            max_elements=new_max,
            persistence_location=tmpdir,
            M=hdr.M or 16,
            ef_construction=hdr.ef_construction or 100,
        )
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    build_seconds = time.time() - t0
    print(f"  Built:   {healthy_n:,} vectors in {build_seconds:.1f}s")

    try:
        sample_n = min(3, healthy_n)
        _self_query_verify(idx, vectors[:sample_n], labels[:sample_n])
    except RebuildVerificationError:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    finally:
        del idx
        gc.collect()

    if meta is not None:
        _meta_set(meta, "total_elements_added", healthy_n)
        with open(os.path.join(tmpdir, "index_metadata.pickle"), "wb") as f:
            pickle.dump(meta, f, protocol=pickle.HIGHEST_PROTOCOL)

    _atomic_swap_segment(tmpdir, seg_dir)

    if purge_queue:
        deleted = _purge_segment_queue(palace_path, segment)
        print(f"  Queue:   purged {deleted:,} embeddings_queue rows")
        result["queue_rows_purged"] = deleted
    if quarantine_orphans and (stale_uids or orphan_hnsw):
        sidecar = _quarantine_orphans(palace_path, stale_uids, orphan_hnsw)
        print(f"  Orphans: appended to {sidecar}")
        result["orphan_sidecar"] = sidecar

    peak_mb = _peak_memory_mb()
    print(f"\n  Rebuild complete in {build_seconds:.1f}s (peak RSS ≈ {peak_mb:.0f} MB)")
    print(f"  Backup:  {backup_dir or '(skipped)'}")
    print("\n  If the MCP server is currently running with vector_disabled set")
    print("  (e.g. after a #1222 capacity-divergence detection), call the")
    print("  `mempalace_reconnect` tool to refresh the capacity probe and")
    print("  restore vector search.")
    print(f"\n{'=' * 55}\n")

    result.update({"build_seconds": build_seconds, "peak_rss_mb": peak_mb, "backup": backup_dir})
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="MemPalace repair tools")
    p.add_argument("--palace", default=None, help="Palace directory path")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Read-only sqlite-vs-HNSW capacity health check")
    p_scan = sub.add_parser("scan")
    p_scan.add_argument("--wing", default=None)
    p_prune = sub.add_parser("prune")
    p_prune.add_argument("--confirm", action="store_true")
    sub.add_parser("rebuild")
    p_hnsw = sub.add_parser("hnsw", help="Single-segment HNSW rebuild (issue #1046)")
    p_hnsw.add_argument("--segment", required=True)
    p_hnsw.add_argument("--max-elements", type=int, default=None)
    p_hnsw.add_argument("--backup", action=argparse.BooleanOptionalAction, default=True)
    p_hnsw.add_argument("--purge-queue", action="store_true")
    p_hnsw.add_argument("--quarantine-orphans", action="store_true")
    p_hnsw.add_argument("--dry-run", action="store_true")
    p_hnsw.add_argument("--yes", action="store_true")
    p_msi = sub.add_parser(
        "max-seq-id", help="Un-poison max_seq_id rows (legacy 0.6.x shim damage)"
    )
    p_msi.add_argument("--segment", default=None)
    p_msi.add_argument("--from-sidecar", default=None)
    p_msi.add_argument("--backup", action=argparse.BooleanOptionalAction, default=True)
    p_msi.add_argument("--dry-run", action="store_true")
    p_msi.add_argument("--yes", action="store_true")

    args = p.parse_args()
    path = os.path.expanduser(args.palace) if args.palace else None

    if args.command == "status":
        status(palace_path=path)
    elif args.command == "scan":
        scan_palace(palace_path=path, only_wing=args.wing)
    elif args.command == "prune":
        prune_corrupt(palace_path=path, confirm=args.confirm)
    elif args.command == "rebuild":
        rebuild_index(palace_path=path)
    elif args.command == "hnsw":
        rebuild_hnsw_segment(
            path or _get_palace_path(),
            segment=args.segment,
            max_elements=args.max_elements,
            backup=args.backup,
            purge_queue=args.purge_queue,
            quarantine_orphans=args.quarantine_orphans,
            dry_run=args.dry_run,
            assume_yes=args.yes,
        )
    elif args.command == "max-seq-id":
        repair_max_seq_id(
            path or _get_palace_path(),
            segment=args.segment,
            from_sidecar=args.from_sidecar,
            backup=args.backup,
            dry_run=args.dry_run,
            assume_yes=args.yes,
        )
