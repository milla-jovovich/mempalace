"""Sync palace with source files — shared logic for CLI and other callers.

`sync_palace()` scans all drawers, compares stored `content_hash` against the
current file's hash, and classifies each source file as fresh/stale/missing/
legacy. In non-dry-run mode it atomically deletes stale drawers and immediately
re-mines the file. All storage access goes through `ChromaBackend` so it works
with any backend that implements the interface.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .backends.chroma import ChromaBackend


def _resolve_path(p: str) -> str:
    """Resolve a path, handling symlinks (e.g. macOS /var → /private/var)."""
    try:
        return str(Path(p).resolve())
    except OSError:
        return p


@dataclass
class SyncReport:
    """Structured result returned by `sync_palace`."""

    fresh: int = 0
    stale: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    no_hash: int = 0
    deleted: int = 0
    re_mined: int = 0
    total_drawers: int = 0
    total_source_files: int = 0


def _scan_source_files(col) -> dict:
    """Return {source_file: {hash, drawer_ids, wing, ingest_mode}}."""
    source_files: dict = {}
    total = col.count()
    batch_size = 500
    offset = 0
    while offset < total:
        batch = col.get(limit=batch_size, offset=offset, include=["metadatas"])
        if not batch["ids"]:
            break
        for drawer_id, meta in zip(batch["ids"], batch["metadatas"]):
            sf = meta.get("source_file", "")
            if not sf:
                continue
            if sf not in source_files:
                source_files[sf] = {
                    "hash": meta.get("content_hash", ""),
                    "drawer_ids": [],
                    "wing": meta.get("wing", ""),
                    "ingest_mode": meta.get("ingest_mode", ""),
                }
            source_files[sf]["drawer_ids"].append(drawer_id)
        offset += len(batch["ids"])
    return source_files


def sync_palace(  # noqa: C901
    palace_path: str,
    source_dir: Optional[str] = None,
    clean: bool = False,
    dry_run: bool = False,
    backend: Optional[ChromaBackend] = None,
    verbose: bool = True,
) -> SyncReport:
    """Scan the palace, classify source files, and (if not dry_run) delete+re-mine stale files.

    Returns a `SyncReport` with counts and stale/missing file lists.
    """
    from .miner import file_content_hash

    report = SyncReport()
    backend = backend or ChromaBackend()

    def _print(msg: str = "") -> None:
        if verbose:
            print(msg)

    _print(f"\n{'=' * 55}")
    _print("  MemPalace Sync")
    _print(f"{'=' * 55}\n")

    try:
        col = backend.get_collection(palace_path, "mempalace_drawers")
    except Exception:
        _print(f"  No palace found at {palace_path}")
        _print("  Run: mempalace init <dir> then mempalace mine <dir>")
        raise FileNotFoundError(palace_path)

    total = col.count()
    report.total_drawers = total
    if total == 0:
        _print("  Palace is empty. Nothing to sync.")
        return report

    _print(f"  Scanning {total} drawers for source files...")
    source_files = _scan_source_files(col)
    _print(f"  Found {len(source_files)} unique source files\n")

    if source_dir:
        sync_dir = str(Path(source_dir).expanduser().resolve())
        source_files = {
            sf: info for sf, info in source_files.items() if _resolve_path(sf).startswith(sync_dir)
        }
        _print(f"  Filtered to {len(source_files)} files in {sync_dir}\n")

    report.total_source_files = len(source_files)
    if not source_files:
        _print("  No source files to check.")
        return report

    for sf, info in sorted(source_files.items()):
        if not os.path.exists(sf):
            report.missing.append(sf)
            continue

        stored_hash = info["hash"]
        if not stored_hash:
            report.no_hash += 1
            continue

        try:
            current_hash = file_content_hash(Path(sf))
        except OSError:
            report.missing.append(sf)
            continue

        if current_hash != stored_hash:
            report.stale.append(sf)
        else:
            report.fresh += 1

    _print(f"  Fresh (unchanged):     {report.fresh}")
    _print(f"  Stale (changed):       {len(report.stale)}")
    _print(f"  Missing (deleted):     {len(report.missing)}")
    if report.no_hash:
        _print(f"  No hash (legacy):      {report.no_hash} (re-mine with --force to add hashes)")
    _print()

    if report.stale:
        _print("  Changed files:")
        for sf in report.stale[:20]:
            n = len(source_files[sf]["drawer_ids"])
            _print(f"    {Path(sf).name} ({n} drawers)")
        if len(report.stale) > 20:
            _print(f"    ... and {len(report.stale) - 20} more")
        _print()

    if report.missing:
        _print("  Missing files:")
        for sf in report.missing[:10]:
            n = len(source_files[sf]["drawer_ids"])
            _print(f"    {Path(sf).name} ({n} drawers)")
        if len(report.missing) > 10:
            _print(f"    ... and {len(report.missing) - 10} more")
        _print()

    if not report.stale and not report.missing:
        _print("  Everything is up to date!")
        _print(f"\n{'=' * 55}\n")
        return report

    if dry_run:
        total_stale = sum(len(source_files[sf]["drawer_ids"]) for sf in report.stale)
        total_missing = sum(len(source_files[sf]["drawer_ids"]) for sf in report.missing)
        _print(f"  [DRY RUN] Would delete {total_stale} stale + {total_missing} orphaned drawers")
        _print(f"  [DRY RUN] Would re-mine {len(report.stale)} changed files")
        _print(f"\n{'=' * 55}\n")
        return report

    if report.stale:
        from .miner import process_file
        from .convo_miner import mine_convos

        _print(f"  Re-syncing {len(report.stale)} changed files...")
        for sf in report.stale:
            info = source_files[sf]
            ids = info["drawer_ids"]
            wing = info["wing"]
            ingest_mode = info.get("ingest_mode", "")

            for i in range(0, len(ids), 100):
                col.delete(ids=ids[i : i + 100])
            report.deleted += len(ids)

            filepath = Path(sf)
            try:
                if ingest_mode == "convos":
                    mine_convos(
                        convo_dir=str(filepath.parent),
                        palace_path=palace_path,
                        wing=wing,
                        agent="mempalace",
                        filepath_filter=str(filepath),
                    )
                    report.re_mined += 1
                    _print(f"    {filepath.name}: re-mined (convos)")
                else:
                    rooms = [{"name": "general", "keywords": []}]
                    n = process_file(
                        filepath=filepath,
                        project_path=filepath.parent,
                        collection=col,
                        wing=wing,
                        rooms=rooms,
                        agent="mempalace",
                        dry_run=False,
                    )
                    if n > 0:
                        report.re_mined += 1
                        _print(f"    {filepath.name}: {n} drawers re-mined")
                    else:
                        _print(f"    {filepath.name}: skipped (empty or too small)")
            except Exception as e:
                _print(f"    {filepath.name}: ERROR — {e}")

    if report.missing and clean:
        _print("  Cleaning orphaned drawers...")
        orphan_count = 0
        for sf in report.missing:
            ids = source_files[sf]["drawer_ids"]
            for i in range(0, len(ids), 100):
                col.delete(ids=ids[i : i + 100])
            orphan_count += len(ids)
        report.deleted += orphan_count
        _print(f"  Cleaned {orphan_count} orphaned drawers")
    elif report.missing:
        _print(
            f"  Skipped {len(report.missing)} missing files (use --clean to remove orphaned drawers)"
        )

    _print("\n  Sync complete.")
    _print(f"  Deleted: {report.deleted} stale drawers")
    if report.re_mined:
        _print(f"  Re-mined: {report.re_mined} files")
    _print(f"\n{'=' * 55}\n")
    return report


def force_clean(palace_path: str, source_dir: str, backend: Optional[ChromaBackend] = None) -> int:
    """Delete all drawers whose source_file is under source_dir.

    Used by `mempalace mine --force`. Returns the number of drawers deleted.
    """
    backend = backend or ChromaBackend()
    try:
        col = backend.get_collection(palace_path, "mempalace_drawers")
    except Exception:
        return 0  # No palace yet — nothing to clean

    source_prefix = str(Path(source_dir).expanduser().resolve())
    batch_size = 500
    offset = 0
    to_delete: List[str] = []
    total = col.count()

    while offset < total:
        batch = col.get(limit=batch_size, offset=offset, include=["metadatas"])
        if not batch["ids"]:
            break
        for drawer_id, meta in zip(batch["ids"], batch["metadatas"]):
            sf = meta.get("source_file", "")
            try:
                sf_resolved = str(Path(sf).resolve()) if sf else ""
            except OSError:
                sf_resolved = sf
            if sf_resolved.startswith(source_prefix):
                to_delete.append(drawer_id)
        offset += len(batch["ids"])

    if to_delete:
        print(f"\n  --force: deleting {len(to_delete)} existing drawers from {source_prefix}...")
        for i in range(0, len(to_delete), 100):
            col.delete(ids=to_delete[i : i + 100])
        print("  Deleted. Re-mining fresh.\n")

    return len(to_delete)
