"""SQLite-backed knowledge graph.

This is the original ``KnowledgeGraph`` implementation, lifted verbatim
behind the :class:`BaseKnowledgeGraph` interface. Behavior is unchanged
so existing tests pass without modification.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .base import BaseKnowledgeGraph

DEFAULT_KG_PATH = os.path.expanduser("~/.mempalace/knowledge_graph.sqlite3")


class SqliteKnowledgeGraph(BaseKnowledgeGraph):
    """SQLite-backed KG. Single persistent connection, thread-safe via a Lock."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_KG_PATH
        if self.db_path != ":memory:":
            db_parent = Path(self.db_path).parent
            db_parent.mkdir(parents=True, exist_ok=True)
            try:
                db_parent.chmod(0o700)
            except (OSError, NotImplementedError):
                pass
        self._connection: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()
        self._init_db()

    # ── Connection ───────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        if self._connection is None:
            self._connection = sqlite3.connect(
                self.db_path, timeout=10, check_same_thread=False
            )
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def _init_db(self) -> None:
        conn = self._conn()
        conn.executescript(
            """
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT DEFAULT 'unknown',
                properties TEXT DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS triples (
                id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object TEXT NOT NULL,
                valid_from TEXT,
                valid_to TEXT,
                confidence REAL DEFAULT 1.0,
                source_closet TEXT,
                source_file TEXT,
                source_drawer_id TEXT,
                adapter_name TEXT,
                extracted_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (subject) REFERENCES entities(id),
                FOREIGN KEY (object) REFERENCES entities(id)
            );

            CREATE INDEX IF NOT EXISTS idx_triples_subject ON triples(subject);
            CREATE INDEX IF NOT EXISTS idx_triples_object ON triples(object);
            CREATE INDEX IF NOT EXISTS idx_triples_predicate ON triples(predicate);
            CREATE INDEX IF NOT EXISTS idx_triples_valid ON triples(valid_from, valid_to);
            """
        )
        self._migrate_schema(conn)
        conn.commit()

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(triples)")}
        if "source_drawer_id" not in existing:
            conn.execute("ALTER TABLE triples ADD COLUMN source_drawer_id TEXT")
        if "adapter_name" not in existing:
            conn.execute("ALTER TABLE triples ADD COLUMN adapter_name TEXT")

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    # ── Writes ───────────────────────────────────────────────────────────

    def add_entity(
        self,
        name: str,
        entity_type: str = "unknown",
        properties: Optional[dict] = None,
    ) -> str:
        eid = self.entity_id(name)
        props = json.dumps(properties or {})
        with self._lock:
            conn = self._conn()
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO entities (id, name, type, properties) VALUES (?, ?, ?, ?)",
                    (eid, name, entity_type, props),
                )
        return eid

    def add_triple(
        self,
        subject: str,
        predicate: str,
        obj: str,
        valid_from: Optional[str] = None,
        valid_to: Optional[str] = None,
        confidence: float = 1.0,
        source_closet: Optional[str] = None,
        source_file: Optional[str] = None,
        source_drawer_id: Optional[str] = None,
        adapter_name: Optional[str] = None,
    ) -> str:
        sub_id = self.entity_id(subject)
        obj_id = self.entity_id(obj)
        pred = predicate.lower().replace(" ", "_")

        with self._lock:
            conn = self._conn()
            with conn:
                conn.execute(
                    "INSERT OR IGNORE INTO entities (id, name) VALUES (?, ?)",
                    (sub_id, subject),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO entities (id, name) VALUES (?, ?)",
                    (obj_id, obj),
                )

                existing = conn.execute(
                    "SELECT id FROM triples "
                    "WHERE subject=? AND predicate=? AND object=? AND valid_to IS NULL",
                    (sub_id, pred, obj_id),
                ).fetchone()

                if existing:
                    return existing["id"]

                triple_id = (
                    f"t_{sub_id}_{pred}_{obj_id}_"
                    + hashlib.sha256(
                        f"{valid_from}{datetime.now().isoformat()}".encode()
                    ).hexdigest()[:12]
                )

                conn.execute(
                    """INSERT INTO triples (
                        id, subject, predicate, object,
                        valid_from, valid_to, confidence,
                        source_closet, source_file,
                        source_drawer_id, adapter_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        triple_id,
                        sub_id,
                        pred,
                        obj_id,
                        valid_from,
                        valid_to,
                        confidence,
                        source_closet,
                        source_file,
                        source_drawer_id,
                        adapter_name,
                    ),
                )
        return triple_id

    def invalidate(
        self,
        subject: str,
        predicate: str,
        obj: str,
        ended: Optional[str] = None,
    ) -> None:
        sub_id = self.entity_id(subject)
        obj_id = self.entity_id(obj)
        pred = predicate.lower().replace(" ", "_")
        ended = ended or date.today().isoformat()

        with self._lock:
            conn = self._conn()
            with conn:
                conn.execute(
                    "UPDATE triples SET valid_to=? "
                    "WHERE subject=? AND predicate=? AND object=? AND valid_to IS NULL",
                    (ended, sub_id, pred, obj_id),
                )

    # ── Reads ────────────────────────────────────────────────────────────

    def query_entity(
        self,
        name: str,
        as_of: Optional[str] = None,
        direction: str = "outgoing",
    ) -> list[dict]:
        eid = self.entity_id(name)
        results: list[dict] = []
        with self._lock:
            conn = self._conn()

            if direction in ("outgoing", "both"):
                query = (
                    "SELECT t.*, e.name as obj_name FROM triples t "
                    "JOIN entities e ON t.object = e.id WHERE t.subject = ?"
                )
                params: list = [eid]
                if as_of:
                    query += (
                        " AND (t.valid_from IS NULL OR t.valid_from <= ?)"
                        " AND (t.valid_to IS NULL OR t.valid_to >= ?)"
                    )
                    params.extend([as_of, as_of])
                for row in conn.execute(query, params).fetchall():
                    results.append(
                        {
                            "direction": "outgoing",
                            "subject": name,
                            "predicate": row["predicate"],
                            "object": row["obj_name"],
                            "valid_from": row["valid_from"],
                            "valid_to": row["valid_to"],
                            "confidence": row["confidence"],
                            "source_closet": row["source_closet"],
                            "current": row["valid_to"] is None,
                        }
                    )

            if direction in ("incoming", "both"):
                query = (
                    "SELECT t.*, e.name as sub_name FROM triples t "
                    "JOIN entities e ON t.subject = e.id WHERE t.object = ?"
                )
                params = [eid]
                if as_of:
                    query += (
                        " AND (t.valid_from IS NULL OR t.valid_from <= ?)"
                        " AND (t.valid_to IS NULL OR t.valid_to >= ?)"
                    )
                    params.extend([as_of, as_of])
                for row in conn.execute(query, params).fetchall():
                    results.append(
                        {
                            "direction": "incoming",
                            "subject": row["sub_name"],
                            "predicate": row["predicate"],
                            "object": name,
                            "valid_from": row["valid_from"],
                            "valid_to": row["valid_to"],
                            "confidence": row["confidence"],
                            "source_closet": row["source_closet"],
                            "current": row["valid_to"] is None,
                        }
                    )

        return results

    def query_relationship(
        self, predicate: str, as_of: Optional[str] = None
    ) -> list[dict]:
        pred = predicate.lower().replace(" ", "_")
        query = (
            "SELECT t.*, s.name as sub_name, o.name as obj_name "
            "FROM triples t "
            "JOIN entities s ON t.subject = s.id "
            "JOIN entities o ON t.object = o.id "
            "WHERE t.predicate = ?"
        )
        params: list = [pred]
        if as_of:
            query += (
                " AND (t.valid_from IS NULL OR t.valid_from <= ?)"
                " AND (t.valid_to IS NULL OR t.valid_to >= ?)"
            )
            params.extend([as_of, as_of])

        results: list[dict] = []
        with self._lock:
            conn = self._conn()
            for row in conn.execute(query, params).fetchall():
                results.append(
                    {
                        "subject": row["sub_name"],
                        "predicate": pred,
                        "object": row["obj_name"],
                        "valid_from": row["valid_from"],
                        "valid_to": row["valid_to"],
                        "current": row["valid_to"] is None,
                    }
                )
        return results

    def timeline(self, entity_name: Optional[str] = None) -> list[dict]:
        with self._lock:
            conn = self._conn()
            if entity_name:
                eid = self.entity_id(entity_name)
                rows = conn.execute(
                    """
                    SELECT t.*, s.name as sub_name, o.name as obj_name
                    FROM triples t
                    JOIN entities s ON t.subject = s.id
                    JOIN entities o ON t.object = o.id
                    WHERE (t.subject = ? OR t.object = ?)
                    ORDER BY t.valid_from ASC NULLS LAST
                    LIMIT 100
                    """,
                    (eid, eid),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT t.*, s.name as sub_name, o.name as obj_name
                    FROM triples t
                    JOIN entities s ON t.subject = s.id
                    JOIN entities o ON t.object = o.id
                    ORDER BY t.valid_from ASC NULLS LAST
                    LIMIT 100
                    """
                ).fetchall()

        return [
            {
                "subject": r["sub_name"],
                "predicate": r["predicate"],
                "object": r["obj_name"],
                "valid_from": r["valid_from"],
                "valid_to": r["valid_to"],
                "current": r["valid_to"] is None,
            }
            for r in rows
        ]

    def stats(self) -> dict:
        with self._lock:
            conn = self._conn()
            entities = conn.execute("SELECT COUNT(*) as cnt FROM entities").fetchone()["cnt"]
            triples = conn.execute("SELECT COUNT(*) as cnt FROM triples").fetchone()["cnt"]
            current = conn.execute(
                "SELECT COUNT(*) as cnt FROM triples WHERE valid_to IS NULL"
            ).fetchone()["cnt"]
            expired = triples - current
            predicates = [
                r["predicate"]
                for r in conn.execute(
                    "SELECT DISTINCT predicate FROM triples ORDER BY predicate"
                ).fetchall()
            ]
        return {
            "entities": entities,
            "triples": triples,
            "current_facts": current,
            "expired_facts": expired,
            "relationship_types": predicates,
        }
