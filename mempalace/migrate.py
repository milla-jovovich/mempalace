#!/usr/bin/env python3
"""
mempalace migrate — Recover a palace created with a different ChromaDB version.

Reads documents and metadata directly from the palace's SQLite database
(bypassing ChromaDB's API, which fails on version-mismatched palaces),
then re-imports everything into a fresh palace using the currently installed
ChromaDB version.

Since mempalace 3.2.0 (chromadb>=1.5.4), chromadb automatically migrates
0.4.1+ databases on first open — no manual migration needed for upgrades.
Use this command only when downgrading chromadb (e.g. rolling back to an
older mempalace release) or if automatic migration fails.

Usage:
    mempalace migrate                          # migrate default palace
    mempalace migrate --palace /path/to/palace  # migrate specific palace
    mempalace migrate --dry-run                # show what would be migrated
"""

import errno
import os
import shutil
import sqlite3
from collections import defaultdict
from datetime import datetime

from .palace import _CHECKPOINT_TOPICS


def _restore_stale_palace(palace_path: str, stale_path: str) -> None:
    """Roll back a failed swap.

    shutil.move() can partially create palace_path before raising, which
    would make a bare os.replace(stale_path, palace_path) fail (dest exists).
    Clear any partial destination first, then restore. Best-effort: if the
    restore itself fails, log both paths so the operator can recover by hand.
    """
    try:
        if os.path.lexists(palace_path):
            shutil.rmtree(palace_path, ignore_errors=True)
        os.replace(stale_path, palace_path)
    except Exception as err:
        print(
            f"  CRITICAL: rollback failed — original palace at {stale_path}, "
            f"partial migration data at {palace_path}. Restore manually. "
            f"({err})"
        )


def extract_drawers_from_sqlite(db_path: str) -> list:
    """Read all drawers directly from ChromaDB's SQLite, bypassing the API.

    Works regardless of which ChromaDB version created the database.
    Returns list of dicts with 'id', 'document', and 'metadata' keys.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Get all embedding IDs and their documents
    rows = conn.execute(
        """
        SELECT e.embedding_id,
               MAX(CASE WHEN em.key = 'chroma:document' THEN em.string_value END) as document
        FROM embeddings e
        JOIN embedding_metadata em ON em.id = e.id
        GROUP BY e.embedding_id
    """
    ).fetchall()

    drawers = []
    for row in rows:
        embedding_id = row["embedding_id"]
        document = row["document"]
        if not document:
            continue

        # Get metadata for this embedding
        meta_rows = conn.execute(
            """
            SELECT em.key, em.string_value, em.int_value, em.float_value, em.bool_value
            FROM embedding_metadata em
            JOIN embeddings e ON e.id = em.id
            WHERE e.embedding_id = ?
              AND em.key NOT LIKE 'chroma:%'
        """,
            (embedding_id,),
        ).fetchall()

        metadata = {}
        for mr in meta_rows:
            key = mr["key"]
            if mr["string_value"] is not None:
                metadata[key] = mr["string_value"]
            elif mr["int_value"] is not None:
                metadata[key] = mr["int_value"]
            elif mr["float_value"] is not None:
                metadata[key] = mr["float_value"]
            elif mr["bool_value"] is not None:
                metadata[key] = bool(mr["bool_value"])

        drawers.append(
            {
                "id": embedding_id,
                "document": document,
                "metadata": metadata,
            }
        )

    conn.close()
    return drawers


def detect_chromadb_version(db_path: str) -> str:
    """Detect which ChromaDB version created the database by checking schema."""
    conn = sqlite3.connect(db_path)
    try:
        # 1.x has schema_str column in collections table
        cols = [r[1] for r in conn.execute("PRAGMA table_info(collections)").fetchall()]
        if "schema_str" in cols:
            return "1.x"
        # 0.6.x has embeddings_queue but no schema_str
        tables = [
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        ]
        if "embeddings_queue" in tables:
            return "0.6.x"
        return "unknown"
    finally:
        conn.close()


def contains_palace_database(path: str) -> bool:
    """Return True when path looks like a MemPalace ChromaDB directory."""
    return os.path.isfile(os.path.join(path, "chroma.sqlite3"))


def confirm_destructive_action(
    operation_name: str, palace_path: str, assume_yes: bool = False
) -> bool:
    """Require confirmation before destructive palace operations."""
    if assume_yes:
        return True

    print(f"\n  {operation_name} will replace data in: {palace_path}")
    print("  A backup will be created first, then the palace will be rebuilt.")
    try:
        answer = input("  Continue? [y/N]: ").strip().lower()
    except EOFError:
        print("  Aborted. Re-run with --yes to confirm destructive changes.")
        return False

    if answer not in {"y", "yes"}:
        print("  Aborted.")
        return False
    return True


def migrate(palace_path: str, dry_run: bool = False, confirm: bool = False):
    """Migrate a palace to the currently installed ChromaDB version."""
    from .backends.chroma import ChromaBackend

    palace_path = os.path.abspath(os.path.expanduser(palace_path))
    db_path = os.path.join(palace_path, "chroma.sqlite3")

    if not os.path.isdir(palace_path) or not contains_palace_database(palace_path):
        print(f"\n  No palace database found at {db_path}")
        return False

    print(f"\n{'=' * 60}")
    print("  MemPalace Migrate")
    print(f"{'=' * 60}\n")
    print(f"  Palace:    {palace_path}")
    print(f"  Database:  {db_path}")
    print(f"  DB size:   {os.path.getsize(db_path) / 1024 / 1024:.1f} MB")

    # Detect version
    source_version = detect_chromadb_version(db_path)
    target_version = ChromaBackend.backend_version()
    print(f"  Source:    ChromaDB {source_version}")
    print(f"  Target:    ChromaDB {target_version}")

    # Try reading with current chromadb first
    try:
        col = ChromaBackend().get_collection(palace_path, "mempalace_drawers")
        count = col.count()
        print(f"\n  Palace is already readable by chromadb {target_version}.")
        print(f"  {count} drawers found. No migration needed.")
        return True
    except Exception:
        print(f"\n  Palace is NOT readable by chromadb {target_version}.")
        print("  Extracting from SQLite directly...")

    # Extract all drawers via raw SQL
    drawers = extract_drawers_from_sqlite(db_path)
    print(f"  Extracted {len(drawers)} drawers from SQLite")

    if not drawers:
        print("  Nothing to migrate.")
        return True

    # Show summary
    wings = defaultdict(lambda: defaultdict(int))
    for d in drawers:
        w = d["metadata"].get("wing", "?")
        r = d["metadata"].get("room", "?")
        wings[w][r] += 1

    print("\n  Summary:")
    for wing, rooms in sorted(wings.items()):
        total = sum(rooms.values())
        print(f"    WING: {wing} ({total} drawers)")
        for room, count in sorted(rooms.items(), key=lambda x: -x[1]):
            print(f"      ROOM: {room:30} {count:5}")

    if dry_run:
        print("\n  DRY RUN — no changes made.")
        print(f"  Would migrate {len(drawers)} drawers.")
        return True

    if not confirm_destructive_action("Migration", palace_path, assume_yes=confirm):
        return False

    # Backup the old palace
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{palace_path}.pre-migrate.{timestamp}"
    print(f"\n  Backing up to {backup_path}...")
    shutil.copytree(palace_path, backup_path)

    # Build fresh palace in a temp directory (avoids chromadb reading old state)
    import tempfile

    temp_palace = tempfile.mkdtemp(prefix="mempalace_migrate_")
    print(f"  Creating fresh palace in {temp_palace}...")
    fresh_backend = ChromaBackend()
    col = fresh_backend.get_or_create_collection(temp_palace, "mempalace_drawers")

    # Re-import in batches
    batch_size = 500
    imported = 0
    for i in range(0, len(drawers), batch_size):
        batch = drawers[i : i + batch_size]
        col.add(
            ids=[d["id"] for d in batch],
            documents=[d["document"] for d in batch],
            metadatas=[d["metadata"] for d in batch],
        )
        imported += len(batch)
        print(f"  Imported {imported}/{len(drawers)} drawers...")

    # Verify before swapping
    final_count = col.count()
    del col
    del fresh_backend

    # Swap: rename old palace aside, then move new one into place.
    # This avoids a window where both old and new are missing.
    print("  Swapping old palace for migrated version...")
    stale_path = palace_path + ".old"
    if os.path.exists(stale_path):
        shutil.rmtree(stale_path)
    os.replace(palace_path, stale_path)
    try:
        os.replace(temp_palace, palace_path)
    except OSError as e:
        # EXDEV = temp lives on a different filesystem; fall back to copy+delete.
        # Anything else is a real error — don't mask it with shutil.move.
        if getattr(e, "errno", None) != errno.EXDEV:
            _restore_stale_palace(palace_path, stale_path)
            raise
        try:
            shutil.move(temp_palace, palace_path)
        except Exception:
            _restore_stale_palace(palace_path, stale_path)
            raise
    shutil.rmtree(stale_path, ignore_errors=True)

    print("\n  Migration complete.")
    print(f"  Drawers migrated: {final_count}")
    print(f"  Backup at: {backup_path}")

    if final_count != len(drawers):
        print(f"  WARNING: Expected {len(drawers)}, got {final_count}")

    print(f"\n{'=' * 60}\n")
    return True


# ---------------------------------------------------------------------------
# Phase D: move existing topic=checkpoint drawers from the main searchable
# collection into the dedicated session-recovery collection. The main
# collection is the *verbatim* store — chats, tool calls, mined files —
# and should not carry derivative summary entries (Stop-hook auto-save
# checkpoints) that wreck vector ranking. See spec at
# docs/superpowers/specs/2026-04-25-checkpoint-collection-split.md.
# ---------------------------------------------------------------------------


def migrate_checkpoints_to_recovery(palace_path: str, batch_size: int = 1000) -> int:
    """Move all topic=checkpoint drawers from main → recovery collection.

    Idempotent: re-running on a fully-migrated palace returns 0. Drawer
    IDs and metadata are preserved exactly. The original drawer is added
    to the recovery collection first, then deleted from main — so a
    crash mid-migration leaves a duplicate (recoverable) rather than a
    loss.

    Returns the number of drawers moved on this invocation.
    """
    from .palace import get_collection, get_session_recovery_collection

    palace_path = os.path.abspath(os.path.expanduser(palace_path))
    if not contains_palace_database(palace_path):
        return 0

    try:
        main = get_collection(palace_path, create=False)
    except Exception:
        # Palace dir exists but main collection isn't readable — nothing to migrate.
        return 0
    recovery = get_session_recovery_collection(palace_path, create=True)

    moved_total = 0
    offset = 0
    # Walk the main collection in pages. We deliberately don't use a
    # ``where={"topic": {"$in": _CHECKPOINT_TOPICS}}`` clause: the
    # ChromaDB 1.5.x filter-planner bug surfaced earlier this week with
    # ``$in``/``$nin`` on metadata. Pull batches plain and filter in
    # Python.
    while True:
        try:
            batch = main.get(
                limit=batch_size,
                offset=offset,
                include=["documents", "metadatas"],
            )
        except Exception:
            # Defensive: a chromadb error on the read path stops the
            # migration cleanly without corrupting state. Caller can retry.
            break

        ids = batch.get("ids") or []
        if not ids:
            break

        docs = batch.get("documents") or []
        metas = batch.get("metadatas") or []

        ids_to_move: list = []
        docs_to_move: list = []
        metas_to_move: list = []

        for i, doc, meta in zip(ids, docs, metas):
            meta = meta or {}
            if meta.get("topic") in _CHECKPOINT_TOPICS:
                ids_to_move.append(i)
                docs_to_move.append(doc)
                metas_to_move.append(meta)

        if ids_to_move:
            recovery.add(
                ids=ids_to_move,
                documents=docs_to_move,
                metadatas=metas_to_move,
            )
            main.delete(ids=ids_to_move)
            moved_total += len(ids_to_move)
            # The delete shrinks main; the *next* page would skip
            # ``len(ids_to_move)`` drawers. Reset offset so we re-page
            # over the (now smaller) collection from the same logical
            # position — equivalent to the standard "delete-during-walk"
            # fixup.
            continue

        offset += len(ids)

    return moved_total
