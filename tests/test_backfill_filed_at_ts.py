"""Tests for mempalace.backfill_filed_at_ts."""
from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mempalace.backfill_filed_at_ts import (
    _parse_iso_to_epoch,
    backfill,
)


def _make_test_palace(tmp_path: Path) -> str:
    """Create a minimal chroma.sqlite3 with the embedding_metadata schema."""
    palace = tmp_path / "palace"
    palace.mkdir()
    db_path = palace / "chroma.sqlite3"
    conn = sqlite3.connect(str(db_path))
    # Schema modeled on Chroma's embedding_metadata table; only the columns
    # the backfill touches are required.
    conn.execute(
        """
        CREATE TABLE embedding_metadata (
            id INTEGER NOT NULL,
            key TEXT NOT NULL,
            string_value TEXT,
            int_value INTEGER,
            float_value REAL,
            bool_value INTEGER,
            PRIMARY KEY (id, key)
        )
        """
    )
    conn.commit()
    conn.close()
    return str(palace)


def _seed(palace_path: str, rows: list[tuple[int, str, str | None]]) -> None:
    """Seed (id, key, string_value) tuples into embedding_metadata."""
    db = sqlite3.connect(str(Path(palace_path) / "chroma.sqlite3"))
    db.executemany(
        "INSERT INTO embedding_metadata (id, key, string_value) VALUES (?, ?, ?)",
        rows,
    )
    db.commit()
    db.close()


def _read_filed_at_ts(palace_path: str) -> dict[int, float | None]:
    db = sqlite3.connect(str(Path(palace_path) / "chroma.sqlite3"))
    cur = db.execute(
        "SELECT id, float_value FROM embedding_metadata WHERE key = 'filed_at_ts'"
    )
    out = {row[0]: row[1] for row in cur.fetchall()}
    db.close()
    return out


# ---------------------------------------------------------------------------
# Pure-function tests
# ---------------------------------------------------------------------------

class TestParseIsoToEpoch:
    def test_iso_with_tz(self):
        e = _parse_iso_to_epoch("2026-04-27T12:00:00+00:00")
        assert e is not None
        # Round-trip through datetime to confirm
        assert datetime.fromtimestamp(e, tz=timezone.utc).isoformat().startswith(
            "2026-04-27T12:00:00"
        )

    def test_iso_zulu(self):
        e = _parse_iso_to_epoch("2026-04-27T12:00:00Z")
        assert e is not None

    def test_iso_naive(self):
        # Naive ISO — interpreted as local time, so we just assert it parses
        e = _parse_iso_to_epoch("2026-04-27T12:00:00")
        assert e is not None

    def test_unparseable(self):
        assert _parse_iso_to_epoch("not a date") is None

    def test_empty(self):
        assert _parse_iso_to_epoch("") is None

    def test_non_string(self):
        assert _parse_iso_to_epoch(None) is None
        assert _parse_iso_to_epoch(42) is None


# ---------------------------------------------------------------------------
# Backfill end-to-end
# ---------------------------------------------------------------------------

class TestBackfill:
    def test_inserts_filed_at_ts_for_each_filed_at(self, tmp_path):
        palace = _make_test_palace(tmp_path)
        _seed(palace, [
            (1, "filed_at", "2026-04-27T12:00:00+00:00"),
            (2, "filed_at", "2026-04-26T08:30:00+00:00"),
            (3, "filed_at", "2026-04-25T20:00:00+00:00"),
        ])
        stats = backfill(palace_path=palace, batch_size=10)
        assert stats["scanned"] == 3
        assert stats["inserted"] == 3
        assert stats["unparseable"] == 0
        out = _read_filed_at_ts(palace)
        assert set(out.keys()) == {1, 2, 3}
        # Newer dates have larger epochs
        assert out[1] > out[2] > out[3]

    def test_dry_run_writes_nothing(self, tmp_path):
        palace = _make_test_palace(tmp_path)
        _seed(palace, [(1, "filed_at", "2026-04-27T12:00:00+00:00")])
        stats = backfill(palace_path=palace, dry_run=True, batch_size=10)
        assert stats["scanned"] == 1
        assert stats["inserted"] == 1  # counted but not committed
        assert _read_filed_at_ts(palace) == {}

    def test_idempotent_skips_existing(self, tmp_path):
        palace = _make_test_palace(tmp_path)
        _seed(palace, [
            (1, "filed_at", "2026-04-27T12:00:00+00:00"),
            (2, "filed_at", "2026-04-26T08:30:00+00:00"),
        ])
        # Pre-seed a filed_at_ts for id=1; backfill should leave it alone
        db = sqlite3.connect(str(Path(palace) / "chroma.sqlite3"))
        db.execute(
            "INSERT INTO embedding_metadata (id, key, float_value) "
            "VALUES (1, 'filed_at_ts', 999.0)"
        )
        db.commit()
        db.close()
        stats = backfill(palace_path=palace, batch_size=10)
        # Only id=2 should be backfilled this run
        assert stats["scanned"] == 1
        assert stats["inserted"] == 1
        out = _read_filed_at_ts(palace)
        assert out[1] == 999.0  # unchanged
        assert out[2] is not None and out[2] != 999.0

    def test_unparseable_filed_at_counted_separately(self, tmp_path):
        palace = _make_test_palace(tmp_path)
        _seed(palace, [
            (1, "filed_at", "2026-04-27T12:00:00+00:00"),
            (2, "filed_at", "garbage"),
            (3, "filed_at", "2026-04-25T20:00:00+00:00"),
        ])
        stats = backfill(palace_path=palace, batch_size=10)
        assert stats["scanned"] == 3
        assert stats["inserted"] == 2  # 1 + 3
        assert stats["unparseable"] == 1
        out = _read_filed_at_ts(palace)
        assert set(out.keys()) == {1, 3}

    def test_missing_db_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            backfill(palace_path=str(tmp_path / "nonexistent"))

    def test_batch_size_smaller_than_rows(self, tmp_path):
        palace = _make_test_palace(tmp_path)
        # 25 rows, batch_size=10 → should still process all of them
        rows = [
            (i, "filed_at", f"2026-04-{i:02d}T00:00:00+00:00")
            for i in range(1, 26)
        ]
        _seed(palace, rows)
        stats = backfill(palace_path=palace, batch_size=10)
        assert stats["scanned"] == 25
        assert stats["inserted"] == 25
        assert len(_read_filed_at_ts(palace)) == 25
