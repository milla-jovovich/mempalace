"""
knowledge_graph.py — Temporal Entity-Relationship Graph for MemPalace
=====================================================================

Real knowledge graph with:
  - Entity nodes (people, projects, tools, concepts)
  - Typed relationship edges (daughter_of, does, loves, works_on, etc.)
  - Temporal validity (valid_from → valid_to — knows WHEN facts are true)
  - Closet references (links back to the verbatim memory)

Storage: LanceDB tables (same palace directory as drawers).
  - kg_entities: id, name, type, properties_json, created_at
  - kg_triples:  id, subject, predicate, object, valid_from, valid_to, ...

Falls back to SQLite for existing palaces (auto-detected).

Usage:
    from mempalace.knowledge_graph import KnowledgeGraph

    kg = KnowledgeGraph("/path/to/palace")
    kg.add_triple("Max", "child_of", "Alice", valid_from="2015-04-01")
    kg.query_entity("Max")
"""

import hashlib
import json
import os
import threading
from datetime import date, datetime
from pathlib import Path


DEFAULT_KG_PATH = os.path.expanduser("~/.mempalace/knowledge_graph.sqlite3")


class KnowledgeGraph:
    """Temporal knowledge graph backed by LanceDB or SQLite.

    If ``db_path`` ends with ``.sqlite3`` the legacy SQLite backend is used.
    If ``palace_path`` is given (a directory), LanceDB tables inside that
    directory are used instead.
    """

    def __init__(self, db_path: str = None, palace_path: str = None):
        if palace_path is not None:
            self._backend = "lance"
            self._palace_path = palace_path
            self._db = None
            self._entities_table = None
            self._triples_table = None
            self._init_lance()
        elif db_path is not None and not db_path.endswith(".sqlite3"):
            # Treat non-sqlite path as a palace directory
            self._backend = "lance"
            self._palace_path = db_path
            self._db = None
            self._entities_table = None
            self._triples_table = None
            self._init_lance()
        else:
            self._backend = "sqlite"
            self.db_path = db_path or DEFAULT_KG_PATH
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._connection = None
            self._lock = threading.Lock()
            self._init_sqlite()

    # ── Lance initialisation ──────────────────────────────────────────

    def _init_lance(self):
        import lancedb
        os.makedirs(self._palace_path, exist_ok=True)
        self._db = lancedb.connect(self._palace_path)
        tables = self._db.list_tables()
        table_names = tables.tables if hasattr(tables, "tables") else list(tables)
        if "kg_entities" in table_names:
            self._entities_table = self._db.open_table("kg_entities")
        if "kg_triples" in table_names:
            self._triples_table = self._db.open_table("kg_triples")

    def _ensure_entities_table(self, initial_record=None):
        if self._entities_table is not None:
            return
        if initial_record is None:
            return
        self._entities_table = self._db.create_table("kg_entities", data=[initial_record])

    def _ensure_triples_table(self, initial_record=None):
        if self._triples_table is not None:
            return
        if initial_record is None:
            return
        self._triples_table = self._db.create_table("kg_triples", data=[initial_record])

    def _lance_refresh(self, table):
        if table is not None:
            try:
                table.checkout_latest()
            except Exception:
                pass

    def _lance_get(self, table, where, limit=1000):
        """Query a lance table, return list of dicts."""
        if table is None:
            return []
        self._lance_refresh(table)
        try:
            q = table.search().where(where).limit(limit)
            return q.to_list()
        except Exception:
            return []

    # ── SQLite initialisation ─────────────────────────────────────────

    def _init_sqlite(self):
        import sqlite3
        conn = self._conn()
        conn.executescript("""
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
                extracted_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (subject) REFERENCES entities(id),
                FOREIGN KEY (object) REFERENCES entities(id)
            );

            CREATE INDEX IF NOT EXISTS idx_triples_subject ON triples(subject);
            CREATE INDEX IF NOT EXISTS idx_triples_object ON triples(object);
            CREATE INDEX IF NOT EXISTS idx_triples_predicate ON triples(predicate);
            CREATE INDEX IF NOT EXISTS idx_triples_valid ON triples(valid_from, valid_to);
        """)
        conn.commit()

    def _conn(self):
        import sqlite3
        if self._connection is None:
            self._connection = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def close(self):
        """Close the database connection."""
        if self._backend == "sqlite" and hasattr(self, "_connection") and self._connection is not None:
            self._connection.close()
            self._connection = None

    def _entity_id(self, name: str) -> str:
        return name.lower().replace(" ", "_").replace("'", "")

    # ── Write operations ──────────────────────────────────────────────

    def add_entity(self, name: str, entity_type: str = "unknown", properties: dict = None):
        """Add or update an entity node."""
        eid = self._entity_id(name)
        props = json.dumps(properties or {})

        if self._backend == "lance":
            record = {
                "id": eid, "name": name, "type": entity_type,
                "properties_json": props,
                "created_at": datetime.now().isoformat(),
            }
            if self._entities_table is None:
                self._ensure_entities_table(record)
            else:
                # Upsert
                try:
                    (self._entities_table.merge_insert("id")
                        .when_matched_update_all()
                        .when_not_matched_insert_all()
                        .execute([record]))
                except Exception:
                    esc = eid.replace("'", "''")
                    try:
                        self._entities_table.delete(f"id = '{esc}'")
                    except Exception:
                        pass
                    self._entities_table.add([record])
            return eid

        # SQLite
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
        valid_from: str = None,
        valid_to: str = None,
        confidence: float = 1.0,
        source_closet: str = None,
        source_file: str = None,
    ):
        """Add a relationship triple: subject → predicate → object."""
        sub_id = self._entity_id(subject)
        obj_id = self._entity_id(obj)
        pred = predicate.lower().replace(" ", "_")

        if self._backend == "lance":
            # Auto-create entities
            self.add_entity(subject)
            self.add_entity(obj)

            # Check for existing identical active triple
            if self._triples_table is not None:
                self._lance_refresh(self._triples_table)
                esc_sub = sub_id.replace("'", "''")
                esc_pred = pred.replace("'", "''")
                esc_obj = obj_id.replace("'", "''")
                existing = self._lance_get(
                    self._triples_table,
                    f"subject = '{esc_sub}' AND predicate = '{esc_pred}' AND object = '{esc_obj}' AND valid_to = ''",
                    limit=1,
                )
                if existing:
                    return existing[0].get("id", "")

            triple_id = f"t_{sub_id}_{pred}_{obj_id}_{hashlib.sha256(f'{valid_from}{datetime.now().isoformat()}'.encode()).hexdigest()[:12]}"
            record = {
                "id": triple_id, "subject": sub_id, "predicate": pred,
                "object": obj_id,
                "valid_from": valid_from or "",
                "valid_to": valid_to or "",
                "confidence": confidence,
                "source_closet": source_closet or "",
                "source_file": source_file or "",
                "extracted_at": datetime.now().isoformat(),
            }
            if self._triples_table is None:
                self._ensure_triples_table(record)
            else:
                self._triples_table.add([record])
            return triple_id

        # SQLite
        with self._lock:
            conn = self._conn()
            with conn:
                conn.execute("INSERT OR IGNORE INTO entities (id, name) VALUES (?, ?)", (sub_id, subject))
                conn.execute("INSERT OR IGNORE INTO entities (id, name) VALUES (?, ?)", (obj_id, obj))

                existing = conn.execute(
                    "SELECT id FROM triples WHERE subject=? AND predicate=? AND object=? AND valid_to IS NULL",
                    (sub_id, pred, obj_id),
                ).fetchone()

                if existing:
                    return existing["id"]

                triple_id = f"t_{sub_id}_{pred}_{obj_id}_{hashlib.sha256(f'{valid_from}{datetime.now().isoformat()}'.encode()).hexdigest()[:12]}"
                conn.execute(
                    """INSERT INTO triples (id, subject, predicate, object, valid_from, valid_to, confidence, source_closet, source_file)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (triple_id, sub_id, pred, obj_id, valid_from, valid_to, confidence, source_closet, source_file),
                )
        return triple_id

    def invalidate(self, subject: str, predicate: str, obj: str, ended: str = None):
        """Mark a relationship as no longer valid (set valid_to date)."""
        sub_id = self._entity_id(subject)
        obj_id = self._entity_id(obj)
        pred = predicate.lower().replace(" ", "_")
        ended = ended or date.today().isoformat()

        if self._backend == "lance":
            if self._triples_table is None:
                return
            self._lance_refresh(self._triples_table)
            esc_sub = sub_id.replace("'", "''")
            esc_pred = pred.replace("'", "''")
            esc_obj = obj_id.replace("'", "''")
            rows = self._lance_get(
                self._triples_table,
                f"subject = '{esc_sub}' AND predicate = '{esc_pred}' AND object = '{esc_obj}' AND valid_to = ''",
            )
            for row in rows:
                tid = row["id"]
                row_copy = dict(row)
                row_copy.pop("_distance", None)
                row_copy.pop("_relevance_score", None)
                row_copy["valid_to"] = ended
                try:
                    (self._triples_table.merge_insert("id")
                        .when_matched_update_all()
                        .when_not_matched_insert_all()
                        .execute([row_copy]))
                except Exception:
                    esc_tid = tid.replace("'", "''")
                    try:
                        self._triples_table.delete(f"id = '{esc_tid}'")
                    except Exception:
                        pass
                    self._triples_table.add([row_copy])
            return

        # SQLite
        with self._lock:
            conn = self._conn()
            with conn:
                conn.execute(
                    "UPDATE triples SET valid_to=? WHERE subject=? AND predicate=? AND object=? AND valid_to IS NULL",
                    (ended, sub_id, pred, obj_id),
                )

    # ── Query operations ──────────────────────────────────────────────

    def query_entity(self, name: str, as_of: str = None, direction: str = "outgoing"):
        """Get all relationships for an entity."""
        eid = self._entity_id(name)

        if self._backend == "lance":
            return self._lance_query_entity(eid, name, as_of, direction)

        # SQLite
        with self._lock:
            conn = self._conn()
            results = []

        if direction in ("outgoing", "both"):
            query = "SELECT t.*, e.name as obj_name FROM triples t JOIN entities e ON t.object = e.id WHERE t.subject = ?"
            params = [eid]
            if as_of:
                query += " AND (t.valid_from IS NULL OR t.valid_from <= ?) AND (t.valid_to IS NULL OR t.valid_to >= ?)"
                params.extend([as_of, as_of])
            for row in conn.execute(query, params).fetchall():
                results.append({
                    "direction": "outgoing", "subject": name,
                    "predicate": row["predicate"], "object": row["obj_name"],
                    "valid_from": row["valid_from"], "valid_to": row["valid_to"],
                    "confidence": row["confidence"], "source_closet": row["source_closet"],
                    "current": row["valid_to"] is None,
                })

        if direction in ("incoming", "both"):
            query = "SELECT t.*, e.name as sub_name FROM triples t JOIN entities e ON t.subject = e.id WHERE t.object = ?"
            params = [eid]
            if as_of:
                query += " AND (t.valid_from IS NULL OR t.valid_from <= ?) AND (t.valid_to IS NULL OR t.valid_to >= ?)"
                params.extend([as_of, as_of])
            for row in conn.execute(query, params).fetchall():
                results.append({
                    "direction": "incoming", "subject": row["sub_name"],
                    "predicate": row["predicate"], "object": name,
                    "valid_from": row["valid_from"], "valid_to": row["valid_to"],
                    "confidence": row["confidence"], "source_closet": row["source_closet"],
                    "current": row["valid_to"] is None,
                })

        return results

    def _lance_query_entity(self, eid, name, as_of, direction):
        """LanceDB implementation of query_entity."""
        if self._triples_table is None:
            return []
        self._lance_refresh(self._triples_table)
        self._lance_refresh(self._entities_table)

        results = []
        esc = eid.replace("'", "''")

        def _get_entity_name(entity_id):
            rows = self._lance_get(self._entities_table, f"id = '{entity_id.replace(chr(39), chr(39)*2)}'", limit=1)
            return rows[0]["name"] if rows else entity_id

        if direction in ("outgoing", "both"):
            rows = self._lance_get(self._triples_table, f"subject = '{esc}'")
            for row in rows:
                vf = row.get("valid_from", "") or ""
                vt = row.get("valid_to", "") or ""
                if as_of:
                    if vf and vf > as_of:
                        continue
                    if vt and vt < as_of:
                        continue
                results.append({
                    "direction": "outgoing", "subject": name,
                    "predicate": row.get("predicate", ""),
                    "object": _get_entity_name(row.get("object", "")),
                    "valid_from": vf or None, "valid_to": vt or None,
                    "confidence": row.get("confidence", 1.0),
                    "source_closet": row.get("source_closet", "") or None,
                    "current": not vt,
                })

        if direction in ("incoming", "both"):
            rows = self._lance_get(self._triples_table, f"object = '{esc}'")
            for row in rows:
                vf = row.get("valid_from", "") or ""
                vt = row.get("valid_to", "") or ""
                if as_of:
                    if vf and vf > as_of:
                        continue
                    if vt and vt < as_of:
                        continue
                results.append({
                    "direction": "incoming",
                    "subject": _get_entity_name(row.get("subject", "")),
                    "predicate": row.get("predicate", ""),
                    "object": name, "valid_from": vf or None, "valid_to": vt or None,
                    "confidence": row.get("confidence", 1.0),
                    "source_closet": row.get("source_closet", "") or None,
                    "current": not vt,
                })

        return results

    def query_relationship(self, predicate: str, as_of: str = None):
        """Get all triples with a given relationship type."""
        pred = predicate.lower().replace(" ", "_")

        if self._backend == "lance":
            if self._triples_table is None:
                return []
            self._lance_refresh(self._triples_table)
            self._lance_refresh(self._entities_table)
            esc = pred.replace("'", "''")
            rows = self._lance_get(self._triples_table, f"predicate = '{esc}'")

            def _name(eid):
                r = self._lance_get(self._entities_table, f"id = '{eid.replace(chr(39), chr(39)*2)}'", limit=1)
                return r[0]["name"] if r else eid

            results = []
            for row in rows:
                vf = row.get("valid_from", "") or ""
                vt = row.get("valid_to", "") or ""
                if as_of:
                    if vf and vf > as_of:
                        continue
                    if vt and vt < as_of:
                        continue
                results.append({
                    "subject": _name(row.get("subject", "")),
                    "predicate": pred,
                    "object": _name(row.get("object", "")),
                    "valid_from": vf or None, "valid_to": vt or None,
                    "current": not vt,
                })
            return results

        # SQLite
        with self._lock:
            conn = self._conn()
            query = """
                SELECT t.*, s.name as sub_name, o.name as obj_name
                FROM triples t JOIN entities s ON t.subject = s.id JOIN entities o ON t.object = o.id
                WHERE t.predicate = ?
            """
            params = [pred]
            if as_of:
                query += " AND (t.valid_from IS NULL OR t.valid_from <= ?) AND (t.valid_to IS NULL OR t.valid_to >= ?)"
                params.extend([as_of, as_of])
            return [
                {"subject": r["sub_name"], "predicate": pred, "object": r["obj_name"],
                 "valid_from": r["valid_from"], "valid_to": r["valid_to"], "current": r["valid_to"] is None}
                for r in conn.execute(query, params).fetchall()
            ]

    def timeline(self, entity_name: str = None):
        """Get all facts in chronological order."""
        if self._backend == "lance":
            return self._lance_timeline(entity_name)

        # SQLite
        with self._lock:
            conn = self._conn()
            if entity_name:
                eid = self._entity_id(entity_name)
                rows = conn.execute("""
                    SELECT t.*, s.name as sub_name, o.name as obj_name
                    FROM triples t JOIN entities s ON t.subject = s.id JOIN entities o ON t.object = o.id
                    WHERE (t.subject = ? OR t.object = ?) ORDER BY t.valid_from ASC NULLS LAST LIMIT 100
                """, (eid, eid)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT t.*, s.name as sub_name, o.name as obj_name
                    FROM triples t JOIN entities s ON t.subject = s.id JOIN entities o ON t.object = o.id
                    ORDER BY t.valid_from ASC NULLS LAST LIMIT 100
                """).fetchall()
            return [
                {"subject": r["sub_name"], "predicate": r["predicate"], "object": r["obj_name"],
                 "valid_from": r["valid_from"], "valid_to": r["valid_to"], "current": r["valid_to"] is None}
                for r in rows
            ]

    def _lance_timeline(self, entity_name=None):
        if self._triples_table is None:
            return []
        self._lance_refresh(self._triples_table)
        self._lance_refresh(self._entities_table)

        def _name(eid):
            r = self._lance_get(self._entities_table, f"id = '{eid.replace(chr(39), chr(39)*2)}'", limit=1)
            return r[0]["name"] if r else eid

        if entity_name:
            eid = self._entity_id(entity_name)
            esc = eid.replace("'", "''")
            rows_s = self._lance_get(self._triples_table, f"subject = '{esc}'")
            rows_o = self._lance_get(self._triples_table, f"object = '{esc}'")
            rows = rows_s + rows_o
        else:
            rows = self._lance_get(self._triples_table, "id != ''")

        results = []
        for r in rows:
            vf = r.get("valid_from", "") or ""
            vt = r.get("valid_to", "") or ""
            results.append({
                "subject": _name(r.get("subject", "")),
                "predicate": r.get("predicate", ""),
                "object": _name(r.get("object", "")),
                "valid_from": vf or None, "valid_to": vt or None,
                "current": not vt,
            })
        results.sort(key=lambda x: x.get("valid_from") or "9999")
        return results[:100]

    # ── Stats ─────────────────────────────────────────────────────────

    def stats(self):
        if self._backend == "lance":
            ent_count = self._entities_table.count_rows() if self._entities_table else 0
            tri_count = self._triples_table.count_rows() if self._triples_table else 0
            current = 0
            if self._triples_table:
                self._lance_refresh(self._triples_table)
                current = self._triples_table.count_rows(filter="valid_to = ''")
            expired = tri_count - current
            preds = set()
            if self._triples_table:
                for r in self._lance_get(self._triples_table, "id != ''", limit=100_000):
                    preds.add(r.get("predicate", ""))
            return {
                "entities": ent_count, "triples": tri_count,
                "current_facts": current, "expired_facts": expired,
                "relationship_types": sorted(preds),
            }

        # SQLite
        with self._lock:
            conn = self._conn()
            entities = conn.execute("SELECT COUNT(*) as cnt FROM entities").fetchone()["cnt"]
            triples = conn.execute("SELECT COUNT(*) as cnt FROM triples").fetchone()["cnt"]
            current = conn.execute("SELECT COUNT(*) as cnt FROM triples WHERE valid_to IS NULL").fetchone()["cnt"]
            expired = triples - current
            predicates = [r["predicate"] for r in conn.execute("SELECT DISTINCT predicate FROM triples ORDER BY predicate").fetchall()]
            return {"entities": entities, "triples": triples, "current_facts": current, "expired_facts": expired, "relationship_types": predicates}

    # ── Seed from known facts ─────────────────────────────────────────

    def seed_from_entity_facts(self, entity_facts: dict):
        """Seed the knowledge graph from fact_checker.py ENTITY_FACTS."""
        for key, facts in entity_facts.items():
            name = facts.get("full_name", key.capitalize())
            etype = facts.get("type", "person")
            self.add_entity(name, etype, {"gender": facts.get("gender", ""), "birthday": facts.get("birthday", "")})

            parent = facts.get("parent")
            if parent:
                self.add_triple(name, "child_of", parent.capitalize(), valid_from=facts.get("birthday"))
            partner = facts.get("partner")
            if partner:
                self.add_triple(name, "married_to", partner.capitalize())

            relationship = facts.get("relationship", "")
            if relationship == "daughter":
                self.add_triple(name, "is_child_of", facts.get("parent", "").capitalize() or name, valid_from=facts.get("birthday"))
            elif relationship == "husband":
                self.add_triple(name, "is_partner_of", facts.get("partner", name).capitalize())
            elif relationship == "brother":
                self.add_triple(name, "is_sibling_of", facts.get("sibling", name).capitalize())
            elif relationship == "dog":
                self.add_triple(name, "is_pet_of", facts.get("owner", name).capitalize())
                self.add_entity(name, "animal")

            for interest in facts.get("interests", []):
                self.add_triple(name, "loves", interest.capitalize(), valid_from="2025-01-01")
