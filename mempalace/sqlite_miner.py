#!/usr/bin/env python3
"""
sqlite_miner.py — Mine SQLite3 databases into the palace.

Extracts schema (tables, indexes, views) and data from SQLite3 files.
Samples large tables to stay within reasonable limits.
Files verbatim SQL and data into drawers.
"""

import os
import hashlib
import sqlite3
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from .palace import (
    NORMALIZE_VERSION,
    file_already_mined,
    get_collection,
    mine_lock,
)
from .config import normalize_wing_name

CHUNK_SIZE = 800
MIN_CHUNK_SIZE = 50
DRAWER_UPSERT_BATCH_SIZE = 1000
MAX_FILE_SIZE = 500 * 1024 * 1024
MAX_ROWS_PER_TABLE = 1000
SCHEMA_PRIORITY = ["table", "index", "view"]

def _extract_schema(conn) -> str:
    """Extract database schema as SQL statements."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name"
    )
    rows = cursor.fetchall()
    parts = []
    for row in rows:
        type_name, name, sql = row
        parts.append(f"-- {type_name.upper()}: {name}\n{sql};\n")
    return "\n".join(parts)

def _extract_table_data(conn, table_name: str, limit: int = MAX_ROWS_PER_TABLE) -> str:
    """Extract data from a table as INSERT statements."""
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT * FROM '{table_name}' LIMIT {limit}")
        rows = cursor.fetchall()
        if not rows:
            return ""
        cursor.execute(f"PRAGMA table_info('{table_name}')")
        columns = [col[1] for col in cursor.fetchall()]
        col_str = ", ".join(f"'{c}'" for c in columns)
        parts = [f"-- DATA: {table_name} ({len(rows)} rows, capped at {limit})\n"]
        for row in rows:
            values = []
            for v in row:
                if v is None:
                    values.append("NULL")
                elif isinstance(v, str):
                    values.append(f"'{v.replace(chr(39), chr(39)+chr(39))}'")
                else:
                    values.append(str(v))
            parts.append(f"INSERT INTO '{table_name}' ({col_str}) VALUES ({', '.join(values)});")
        return "\n".join(parts)
    except Exception:
        return f"-- ERROR reading table {table_name}"

def _extract_table_counts(conn) -> str:
    """Get row counts for all tables."""
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]
    parts = ["-- TABLE COUNTS"]
    for table in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM '{table}'")
            count = cursor.fetchone()[0]
            parts.append(f"-- {table}: {count} rows")
        except Exception:
            parts.append(f"-- {table}: unknown")
    return "\n".join(parts)

def read_sqlite_file(filepath: Path) -> str:
    """Read a SQLite3 file and return formatted text representation."""
    try:
        conn = sqlite3.connect(str(filepath))
        conn.row_factory = sqlite3.Row
        parts = []
        parts.append(f"-- SQLite3 Database: {filepath.name}")
        parts.append(f"-- File size: {filepath.stat().st_size} bytes")
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode")
            journal = cursor.fetchone()[0]
            parts.append(f"-- Journal mode: {journal}")
        except Exception:
            pass
        parts.append("\n" + "=" * 60)
        parts.append("SCHEMA")
        parts.append("=" * 60)
        parts.append(_extract_schema(conn))
        parts.append("\n" + "=" * 60)
        parts.append("TABLE COUNTS")
        parts.append("=" * 60)
        parts.append(_extract_table_counts(conn))
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        for table in tables:
            parts.append("\n" + "-" * 60)
            parts.append(f"TABLE DATA: {table}")
            parts.append("-" * 60)
            parts.append(_extract_table_data(conn, table))
        conn.close()
        return "\n".join(parts)
    except Exception as e:
        return f"-- Error reading SQLite3 file: {e}"

def chunk_sqlite_content(content: str) -> list:
    """Chunk SQLite content by sections (schema, table data)."""
    chunks = []
    current_chunk = []
    current_size = 0
    lines = content.split("\n")
    for line in lines:
        line_size = len(line) + 1
        if current_size + line_size > CHUNK_SIZE and current_chunk:
            chunk_text = "\n".join(current_chunk).strip()
            if len(chunk_text) >= MIN_CHUNK_SIZE:
                chunks.append({"content": chunk_text, "chunk_index": len(chunks)})
            current_chunk = []
            current_size = 0
        current_chunk.append(line)
        current_size += line_size
    if current_chunk:
        chunk_text = "\n".join(current_chunk).strip()
        if len(chunk_text) >= MIN_CHUNK_SIZE:
            chunks.append({"content": chunk_text, "chunk_index": len(chunks)})
    return chunks

def detect_sqlite_room(filepath: Path, content: str) -> str:
    """Detect room based on database name and content."""
    filename = filepath.stem.lower()
    content_lower = content[:2000].lower()
    if "CREATE TABLE" in content and "CREATE INDEX" in content:
        return "schema"
    if "PRAGMA" in content and "journal_mode" in content_lower:
        return "metadata"
    for keyword in ["user", "account", "auth", "session"]:
        if keyword in filename or keyword in content_lower[:1000]:
            return "auth"
    for keyword in ["log", "event", "audit", "history"]:
        if keyword in filename or keyword in content_lower[:1000]:
            return "logs"
    return "data"

def _build_drawer_metadata(wing: str, room: str, source_file: str, chunk_index: int, agent: str, content: str, source_mtime: float = None) -> dict:
    """Build metadata dict for a drawer."""
    metadata = {
        "wing": wing,
        "room": room,
        "source_file": source_file,
        "chunk_index": chunk_index,
        "added_by": agent,
        "filed_at": datetime.now().isoformat(),
        "normalize_version": NORMALIZE_VERSION,
        "ingest_mode": "sqlite",
    }
    if source_mtime is not None:
        metadata["source_mtime"] = source_mtime
    return metadata

def process_sqlite_file(
    filepath: Path,
    collection,
    wing: str,
    agent: str = "mempalace",
    dry_run: bool = False,
) -> tuple:
    """Process one SQLite file and file into palace."""
    source_file = str(filepath)
    if not dry_run and file_already_mined(collection, source_file, check_mtime=True):
        return 0, "general"
    try:
        content = read_sqlite_file(filepath)
    except Exception:
        return 0, "general"
    if len(content) < MIN_CHUNK_SIZE:
        return 0, "general"
    room = detect_sqlite_room(filepath, content)
    chunks = chunk_sqlite_content(content)
    if dry_run:
        print(f"    [DRY RUN] {filepath.name} -> room:{room} ({len(chunks)} drawers)")
        return len(chunks), room
    with mine_lock(source_file):
        if file_already_mined(collection, source_file, check_mtime=True):
            return 0, room
        try:
            collection.delete(where={"source_file": source_file})
        except Exception:
            pass
        try:
            source_mtime = os.path.getmtime(source_file)
        except OSError:
            source_mtime = None
        drawers_added = 0
        for batch_start in range(0, len(chunks), DRAWER_UPSERT_BATCH_SIZE):
            batch_docs = []
            batch_ids = []
            batch_metas = []
            for chunk in chunks[batch_start : batch_start + DRAWER_UPSERT_BATCH_SIZE]:
                chunk_room = room
                drawer_id = f"drawer_{wing}_{chunk_room}_{hashlib.sha256((source_file + str(chunk['chunk_index'])).encode()).hexdigest()[:24]}"
                batch_docs.append(chunk["content"])
                batch_ids.append(drawer_id)
                batch_metas.append(
                    _build_drawer_metadata(
                        wing, chunk_room, source_file, chunk["chunk_index"], agent, chunk["content"], source_mtime
                    )
                )
            try:
                collection.upsert(
                    documents=batch_docs,
                    ids=batch_ids,
                    metadatas=batch_metas,
                )
                drawers_added += len(batch_docs)
            except Exception as e:
                if "already exists" not in str(e).lower():
                    raise
    return drawers_added, room

def scan_sqlite_files(directory: str) -> list:
    """Find all SQLite3 files in directory."""
    dir_path = Path(directory).expanduser().resolve()
    files = []
    sqlite_extensions = {".db", ".sqlite", ".sqlite3", ".db3"}
    for root, dirs, filenames in os.walk(dir_path):
        dirs[:] = [d for d in dirs if d not in {"__pycache__", ".git", "node_modules", "venv", ".venv"}]
        for filename in filenames:
            filepath = Path(root) / filename
            if filepath.suffix.lower() in sqlite_extensions:
                if filepath.is_symlink():
                    continue
                try:
                    if filepath.stat().st_size > MAX_FILE_SIZE:
                        continue
                except OSError:
                    continue
                files.append(filepath)
    return files

def mine_sqlite(
    directory: str,
    palace_path: str,
    wing: str = None,
    agent: str = "mempalace",
    limit: int = 0,
    dry_run: bool = False,
):
    """Mine SQLite3 files in a directory (or a single file) into the palace."""
    dir_path = Path(directory).expanduser().resolve()
    if not wing:
        wing = normalize_wing_name(dir_path.name)
    # Handle single file path directly
    if dir_path.is_file() and dir_path.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".db3"}:
        files = [dir_path]
    else:
        files = scan_sqlite_files(directory)
    if limit > 0:
        files = files[:limit]
    print(f"\n{'=' * 55}")
    print("  MemPalace Mine — SQLite3")
    print(f"{'=' * 55}")
    print(f"  Wing:    {wing}")
    print(f"  Source:  {dir_path}")
    print(f"  Files:   {len(files)}")
    print(f"  Palace:  {palace_path}")
    if dry_run:
        print("  DRY RUN — nothing will be filed")
    print(f"{'-' * 55}\n")
    collection = get_collection(palace_path) if not dry_run else None
    total_drawers = 0
    files_skipped = 0
    room_counts = defaultdict(int)
    for i, filepath in enumerate(files, 1):
        try:
            drawers, room = process_sqlite_file(
                filepath=filepath,
                collection=collection,
                wing=wing,
                agent=agent,
                dry_run=dry_run,
            )
        except KeyboardInterrupt:
            raise
        if drawers == 0 and not dry_run:
            files_skipped += 1
        else:
            total_drawers += drawers
            room_counts[room] += 1
            if not dry_run:
                print(f"  + [{i:4}/{len(files)}] {filepath.name[:50]:50} +{drawers}")
    print(f"\n{'=' * 55}")
    print("  Done.")
    print(f"  Files processed: {len(files) - files_skipped}")
    print(f"  Files skipped (already filed): {files_skipped}")
    print(f"  Drawers filed: {total_drawers}")
    if room_counts:
        print("\n  By room:")
        for room, count in sorted(room_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"    {room:20} {count} files")
    print('\n  Next: mempalace search "what you\'re looking for"')
    print(f"{'=' * 55}\n")
