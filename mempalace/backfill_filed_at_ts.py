#!/usr/bin/env python3
"""Backfill ``filed_at_ts`` numeric metadata on existing drawers.

Companion to the write-time addition of ``filed_at_ts`` (epoch seconds) to
drawer metadata. New drawers get the field automatically; this script
backfills it on existing drawers so server-side date filters
(``{"filed_at_ts": {"$gte": cutoff_epoch}}``) return the correct subset.

Operates via direct SQL UPDATE on ``embedding_metadata`` in the palace's
``chroma.sqlite3``. Bypasses the ChromaDB API and HNSW entirely — safe for
TB-scale palaces (issue #525 / chromadb #2515 / #2594 / #913). Per the
global ChromaDB safety contract, ``col.update(metadatas=...)`` is unsafe
on existing palaces; this script does NOT use that path.

Usage:
    python -m mempalace.backfill_filed_at_ts                  # default palace
    python -m mempalace.backfill_filed_at_ts --palace /path
    python -m mempalace.backfill_filed_at_ts --dry-run
    python -m mempalace.backfill_filed_at_ts --batch-size 5000

The script is idempotent: rows that already have a ``filed_at_ts`` entry
are skipped.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


DEFAULT_PALACE_PATH = os.path.expanduser("~/.mempalace/palace")


def _parse_iso_to_epoch(value: str) -> float | None:
    """Parse an ISO-8601 string to Unix epoch seconds.

    Returns None for unparseable values. Naive datetimes are assumed local
    time (matching the producers in miner.py / convo_miner.py / etc.,
    which call ``datetime.now()`` without an explicit timezone). UTC-bearing
    strings are parsed correctly via fromisoformat.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        # Python 3.11+ accepts the trailing Z; older versions need the swap.
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return dt.timestamp()


def _open_db(palace_path: str) -> sqlite3.Connection:
    db_path = Path(palace_path) / "chroma.sqlite3"
    if not db_path.exists():
        raise FileNotFoundError(f"chroma.sqlite3 not found at {db_path}")
    return sqlite3.connect(str(db_path))


def _count_rows_needing_backfill(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        """
        SELECT COUNT(*)
        FROM embedding_metadata m
        WHERE m.key = 'filed_at'
          AND m.string_value IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM embedding_metadata m2
              WHERE m2.id = m.id AND m2.key = 'filed_at_ts'
          )
        """
    )
    return cur.fetchone()[0]


def _iter_rows_to_backfill(conn: sqlite3.Connection, batch_size: int):
    """Yield (id, filed_at_string) for rows that need filed_at_ts inserted.

    Cursor-paginates by tracking the highest id processed so far. We can't
    use OFFSET because the WHERE clause (NOT EXISTS filed_at_ts) is
    self-modifying — once a batch is committed, those rows drop out of the
    matching set, and OFFSET would skip past unprocessed rows. Tracking
    last_id is stable under that mutation.
    """
    last_id = -1
    while True:
        cur = conn.execute(
            """
            SELECT m.id, m.string_value
            FROM embedding_metadata m
            WHERE m.key = 'filed_at'
              AND m.string_value IS NOT NULL
              AND m.id > ?
              AND NOT EXISTS (
                  SELECT 1 FROM embedding_metadata m2
                  WHERE m2.id = m.id AND m2.key = 'filed_at_ts'
              )
            ORDER BY m.id
            LIMIT ?
            """,
            (last_id, batch_size),
        )
        rows = cur.fetchall()
        if not rows:
            return
        yield from rows
        last_id = rows[-1][0]
        if len(rows) < batch_size:
            return


def backfill(
    palace_path: str = DEFAULT_PALACE_PATH,
    dry_run: bool = False,
    batch_size: int = 5000,
) -> dict[str, int]:
    """Add filed_at_ts (REAL) for every row that has filed_at (TEXT) but
    no filed_at_ts yet.

    Returns counts: {"scanned", "inserted", "unparseable", "skipped"}.
    """
    conn = _open_db(palace_path)
    try:
        total = _count_rows_needing_backfill(conn)
        print(
            f"[backfill] palace={palace_path} rows_needing_backfill={total} "
            f"batch_size={batch_size} dry_run={dry_run}",
            flush=True,
        )

        scanned = 0
        inserted = 0
        unparseable = 0
        pending: list[tuple[int, str, float]] = []

        for row_id, iso_value in _iter_rows_to_backfill(conn, batch_size):
            scanned += 1
            epoch = _parse_iso_to_epoch(iso_value)
            if epoch is None:
                unparseable += 1
                continue
            pending.append((row_id, "filed_at_ts", epoch))

            if len(pending) >= batch_size:
                if not dry_run:
                    conn.executemany(
                        "INSERT OR IGNORE INTO embedding_metadata "
                        "(id, key, float_value) VALUES (?, ?, ?)",
                        pending,
                    )
                    conn.commit()
                inserted += len(pending)
                pending.clear()
                print(
                    f"[backfill] progress scanned={scanned} "
                    f"inserted={inserted} unparseable={unparseable}",
                    flush=True,
                )

        if pending:
            if not dry_run:
                conn.executemany(
                    "INSERT OR IGNORE INTO embedding_metadata "
                    "(id, key, float_value) VALUES (?, ?, ?)",
                    pending,
                )
                conn.commit()
            inserted += len(pending)
            pending.clear()

        skipped = total - scanned  # rows discovered after the initial count
        print(
            f"[backfill] done scanned={scanned} inserted={inserted} "
            f"unparseable={unparseable} skipped={skipped} dry_run={dry_run}",
            flush=True,
        )
        return {
            "scanned": scanned,
            "inserted": inserted,
            "unparseable": unparseable,
            "skipped": skipped,
        }
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill numeric filed_at_ts on existing drawers.",
    )
    parser.add_argument(
        "--palace",
        default=DEFAULT_PALACE_PATH,
        help=f"Path to palace directory (default: {DEFAULT_PALACE_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be backfilled without writing",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5000,
        help="Rows per executemany batch (default: 5000)",
    )
    args = parser.parse_args(argv)

    try:
        backfill(
            palace_path=args.palace,
            dry_run=args.dry_run,
            batch_size=args.batch_size,
        )
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
