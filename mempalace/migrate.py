#!/usr/bin/env python3
"""
mempalace migrate — Recover a palace created with a different ChromaDB version.

Reads documents and metadata directly from the palace's SQLite database
(bypassing ChromaDB's API, which fails on version-mismatched palaces),
then re-imports everything into a fresh palace using the currently installed
ChromaDB version.

This fixes the 3.0.0 → 3.1.0 upgrade path where chromadb was downgraded
from 1.5.x to 0.6.x, breaking the on-disk storage format.

Usage:
    mempalace migrate                          # migrate default palace
    mempalace migrate --palace /path/to/palace  # migrate specific palace
    mempalace migrate --dry-run                # show what would be migrated
"""

import os
import shutil
import sqlite3
from collections import defaultdict
from datetime import datetime


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
    import chromadb

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
    print(f"  Source:    ChromaDB {source_version}")
    print(f"  Target:    ChromaDB {chromadb.__version__}")

    # Try reading with current chromadb first
    try:
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
        count = col.count()
        print(f"\n  Palace is already readable by chromadb {chromadb.__version__}.")
        print(f"  {count} drawers found. No migration needed.")
        return True
    except Exception:
        print(f"\n  Palace is NOT readable by chromadb {chromadb.__version__}.")
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
    client = chromadb.PersistentClient(path=temp_palace)
    col = client.get_or_create_collection("mempalace_drawers", metadata={"hnsw:space": "cosine"})

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
    del client

    # Swap: remove old palace, move new one into place
    print("  Swapping old palace for migrated version...")
    shutil.rmtree(palace_path)
    shutil.move(temp_palace, palace_path)

    print("\n  Migration complete.")
    print(f"  Drawers migrated: {final_count}")
    print(f"  Backup at: {backup_path}")

    if final_count != len(drawers):
        print(f"  WARNING: Expected {len(drawers)}, got {final_count}")

    print(f"\n{'=' * 60}\n")
    return True
