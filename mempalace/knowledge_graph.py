"""
knowledge_graph.py — Temporal Entity-Relationship Graph for MemPalace
=====================================================================

Real knowledge graph with:
  - Entity nodes (people, projects, tools, concepts)
  - Typed relationship edges (daughter_of, does, loves, works_on, etc.)
  - Temporal validity (valid_from → valid_to — knows WHEN facts are true)
  - Closet references (links back to the verbatim memory)

Storage: SQLite (local, no dependencies, no subscriptions)
Query: entity-first traversal with time filtering

This is what competes with Zep's temporal knowledge graph.
Zep uses Neo4j in the cloud ($25/mo+). We use SQLite locally (free).

Usage:
    from mempalace.knowledge_graph import KnowledgeGraph

    kg = KnowledgeGraph()
    kg.add_triple("Max", "child_of", "Alice", valid_from="2015-04-01")
    kg.add_triple("Max", "does", "swimming", valid_from="2025-01-01")
    kg.add_triple("Max", "loves", "chess", valid_from="2025-10-01")

    # Query: everything about Max
    kg.query_entity("Max")

    # Query: what was true about Max in January 2026?
    kg.query_entity("Max", as_of="2026-01-15")

    # Query: who is connected to Alice?
    kg.query_entity("Alice", direction="both")

    # Invalidate: Max's sports injury resolved
    kg.invalidate("Max", "has_issue", "sports_injury", ended="2026-02-15")
"""

import hashlib
import json
import os
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path


DEFAULT_KG_PATH = os.path.expanduser("~/.mempalace/knowledge_graph.sqlite3")


def normalize_entity_name(name: str) -> str:
    """Aggressive entity name normalization for dedup.

    Collapses: hyphens, underscores, dots, spaces, colons, slashes,
    backslashes, CamelCase boundaries, leading articles.

    Does NOT collapse: plurals, abbreviations (handled by semantic
    similarity on entity descriptions instead).

    Examples:
        "The Flowsev Repository" -> "flowsev_repository"
        "flowsev_repository"     -> "flowsev_repository"
        "FlowsevRepository"      -> "flowsev_repository"
        "D:\\Flowsev\\repo"      -> "d_flowsev_repo"
        "paperclip-server"       -> "paperclip_server"
        "paperclip_server"       -> "paperclip_server"
        "the GA agent"           -> "ga_agent"
    """
    if not isinstance(name, str) or not name.strip():
        return "unknown"
    s = name.strip()
    # Split CamelCase: "FlowsevRepo" -> "Flowsev Repo"
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    # Also split "HTTPServer" -> "HTTP Server"
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    # Lowercase
    s = s.lower()
    # Replace ALL non-alphanumeric with underscore (matches ChromaDB drawer ID convention)
    s = re.sub(r"[^a-z0-9]+", "_", s)
    # Collapse repeated underscores
    s = re.sub(r"_+", "_", s)
    # Strip leading/trailing underscores
    s = s.strip("_")
    # Strip leading articles
    for article in ("the_", "a_", "an_"):
        if s.startswith(article):
            s = s[len(article):]
            break
    return s or "unknown"


class KnowledgeGraph:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or DEFAULT_KG_PATH
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = None
        self._init_db()

    def _init_db(self):
        conn = self._conn()
        conn.executescript("""
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT DEFAULT 'unknown',
                properties TEXT DEFAULT '{}',
                description TEXT DEFAULT '',
                importance INTEGER DEFAULT 3,
                last_touched TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                merged_into TEXT DEFAULT NULL,
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

            CREATE TABLE IF NOT EXISTS entity_aliases (
                alias TEXT PRIMARY KEY,
                canonical_id TEXT NOT NULL,
                merged_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (canonical_id) REFERENCES entities(id)
            );

            CREATE INDEX IF NOT EXISTS idx_triples_subject ON triples(subject);
            CREATE INDEX IF NOT EXISTS idx_triples_object ON triples(object);
            CREATE INDEX IF NOT EXISTS idx_triples_predicate ON triples(predicate);
            CREATE INDEX IF NOT EXISTS idx_triples_valid ON triples(valid_from, valid_to);
        """)
        # Migrate existing databases that don't have the new columns
        self._migrate_schema(conn)
        # Create indexes on new columns AFTER migration ensures they exist
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_status ON entities(status)")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_aliases_canonical ON entity_aliases(canonical_id)")
        except sqlite3.OperationalError:
            pass
        conn.commit()

    def _migrate_schema(self, conn):
        """Add new columns to existing databases (backward compatible)."""
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(entities)").fetchall()}
        migrations = [
            ("description", "ALTER TABLE entities ADD COLUMN description TEXT DEFAULT ''"),
            ("importance", "ALTER TABLE entities ADD COLUMN importance INTEGER DEFAULT 3"),
            ("last_touched", "ALTER TABLE entities ADD COLUMN last_touched TEXT DEFAULT ''"),
            ("status", "ALTER TABLE entities ADD COLUMN status TEXT DEFAULT 'active'"),
            ("merged_into", "ALTER TABLE entities ADD COLUMN merged_into TEXT DEFAULT NULL"),
            ("kind", "ALTER TABLE entities ADD COLUMN kind TEXT DEFAULT 'entity'"),
        ]
        for col_name, sql in migrations:
            if col_name not in existing_cols:
                try:
                    conn.execute(sql)
                except sqlite3.OperationalError:
                    pass  # Column already exists (race condition)
        # Backfill kind from type for existing entities
        if "kind" not in existing_cols:
            try:
                # Map old type values to kind: predicate stays predicate, everything else is entity
                conn.execute("UPDATE entities SET kind = 'predicate' WHERE type = 'predicate'")
                conn.execute("UPDATE entities SET kind = 'entity' WHERE type != 'predicate' AND (kind IS NULL OR kind = 'entity')")
            except sqlite3.OperationalError:
                pass

        # Seed canonical ontology on first run (no "thing" class yet)
        # Only for production palaces — test KGs are empty by design
        if not os.environ.get("MEMPALACE_SKIP_SEED"):
            self.seed_ontology()

    def _conn(self):
        if self._connection is None:
            self._connection = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def seed_ontology(self):
        """Seed canonical classes, predicates, and intent types. Idempotent.

        Called automatically on first run (empty entities table) or on demand.
        Uses add_entity + add_triple, so normalization and schema are consistent.
        """
        conn = self._conn()
        # Check if ontology already seeded (look for root class "thing")
        thing = conn.execute("SELECT id FROM entities WHERE id = 'thing'").fetchone()
        if thing:
            return  # Already seeded

        # ── Classes (kind=class) ──
        classes = [
            ("thing", "Root class of the ontology. All other classes inherit from thing.", 5),
            ("system", "A running infrastructure component: servers, databases, containers, services", 4),
            ("person", "A human individual", 4),
            ("agent", "An AI agent in the paperclip system (PFE, TL, Director, GA, etc.)", 4),
            ("project", "A repository, codebase, or software product", 4),
            ("file", "A specific file or path in a project", 3),
            ("rule", "A standing order, directive, or constraint authored by a human", 4),
            ("tool", "A software tool, CLI, or library", 3),
            ("process", "A workflow, procedure, or recurring operation", 3),
            ("concept", "An abstract idea, pattern, formula, or design principle", 3),
            ("environment", "A runtime environment or container that hosts processes and services", 3),
            ("intent_type", "Class for intent types — the kind of action an agent declares before acting", 5),
        ]
        for name, desc, imp in classes:
            self.add_entity(name, kind="class", description=desc, importance=imp)
            if name != "thing":
                self.add_triple(name, "is-a", "thing")

        # ── Predicates (kind=predicate) with constraints ──
        predicates = [
            ("is_a", "Taxonomic classification: subject is an instance of object class, or a subtype of another entity in a hierarchy", 5,
             {"subject_kinds": ["entity"], "object_kinds": ["class", "entity"], "subject_classes": ["thing"], "object_classes": ["thing"], "cardinality": "many-to-many"}),
            ("has_value", "Subject has a specific attribute value as object", 4,
             {"subject_kinds": ["entity"], "object_kinds": ["entity", "literal"], "subject_classes": ["thing"], "object_classes": ["thing"], "cardinality": "many-to-many"}),
            ("has_property", "Subject has a named property described by object", 4,
             {"subject_kinds": ["entity"], "object_kinds": ["entity", "literal"], "subject_classes": ["thing"], "object_classes": ["thing"], "cardinality": "many-to-many"}),
            ("defaults_to", "Subject has a default value of object", 3,
             {"subject_kinds": ["entity"], "object_kinds": ["entity", "literal"], "subject_classes": ["thing"], "object_classes": ["thing"], "cardinality": "many-to-one"}),
            ("lives_at", "Subject is located at object (path, URL, address)", 4,
             {"subject_kinds": ["entity"], "object_kinds": ["entity", "literal"], "subject_classes": ["thing"], "object_classes": ["thing"], "cardinality": "many-to-one"}),
            ("runs_in", "Subject operates as a process inside object runtime", 4,
             {"subject_kinds": ["entity"], "object_kinds": ["entity"], "subject_classes": ["system", "process"], "object_classes": ["system"], "cardinality": "many-to-one"}),
            ("stored_in", "Subject data is persisted in object storage", 3,
             {"subject_kinds": ["entity"], "object_kinds": ["entity"], "subject_classes": ["thing"], "object_classes": ["thing"], "cardinality": "many-to-one"}),
            ("depends_on", "Subject requires object to function", 4,
             {"subject_kinds": ["entity"], "object_kinds": ["entity"], "subject_classes": ["thing"], "object_classes": ["thing"], "cardinality": "many-to-many"}),
            ("requires", "Subject needs object as a runtime prerequisite", 4,
             {"subject_kinds": ["entity"], "object_kinds": ["entity"], "subject_classes": ["thing"], "object_classes": ["thing"], "cardinality": "many-to-many"}),
            ("blocks", "Subject prevents object from proceeding", 3,
             {"subject_kinds": ["entity"], "object_kinds": ["entity"], "subject_classes": ["thing"], "object_classes": ["thing"], "cardinality": "many-to-many"}),
            ("enables", "Subject unlocks object capability", 3,
             {"subject_kinds": ["entity"], "object_kinds": ["entity"], "subject_classes": ["thing"], "object_classes": ["thing"], "cardinality": "many-to-many"}),
            ("must", "Subject is required to do/be object (positive rule)", 4,
             {"subject_kinds": ["entity"], "object_kinds": ["entity", "literal"], "subject_classes": ["thing"], "object_classes": ["thing"], "cardinality": "many-to-many"}),
            ("must_not", "Subject is forbidden from doing/being object (negative rule)", 4,
             {"subject_kinds": ["entity"], "object_kinds": ["entity", "literal"], "subject_classes": ["thing"], "object_classes": ["thing"], "cardinality": "many-to-many"}),
            ("forbids", "Subject prohibits object action", 3,
             {"subject_kinds": ["entity"], "object_kinds": ["entity", "literal"], "subject_classes": ["rule"], "object_classes": ["thing"], "cardinality": "many-to-many"}),
            ("has_gotcha", "Subject has a known pitfall described by object", 4,
             {"subject_kinds": ["entity"], "object_kinds": ["entity", "literal"], "subject_classes": ["thing"], "object_classes": ["thing"], "cardinality": "many-to-many"}),
            ("warns_about", "Subject raises a caution about object", 3,
             {"subject_kinds": ["entity"], "object_kinds": ["entity", "literal"], "subject_classes": ["thing"], "object_classes": ["thing"], "cardinality": "many-to-many"}),
            ("replaced_by", "Subject was superseded by object", 3,
             {"subject_kinds": ["entity"], "object_kinds": ["entity"], "subject_classes": ["thing"], "object_classes": ["thing"], "cardinality": "many-to-one"}),
            ("invalidated_by", "Subject was made obsolete by object event", 3,
             {"subject_kinds": ["entity"], "object_kinds": ["entity"], "subject_classes": ["thing"], "object_classes": ["thing"], "cardinality": "many-to-one"}),
            ("described_by", "Entity's canonical description lives in this drawer", 4,
             {"subject_kinds": ["entity"], "object_kinds": ["entity"], "subject_classes": ["thing"], "object_classes": ["thing"], "cardinality": "many-to-many"}),
            ("evidenced_by", "A rule or decision is backed by this drawer's content", 3,
             {"subject_kinds": ["entity"], "object_kinds": ["entity"], "subject_classes": ["thing"], "object_classes": ["thing"], "cardinality": "many-to-many"}),
            ("mentioned_in", "Entity is referenced in this drawer but not its main topic", 3,
             {"subject_kinds": ["entity"], "object_kinds": ["entity"], "subject_classes": ["thing"], "object_classes": ["thing"], "cardinality": "many-to-many"}),
            ("session_note_for", "A diary or session-log entry relevant to this entity", 3,
             {"subject_kinds": ["entity"], "object_kinds": ["entity"], "subject_classes": ["thing"], "object_classes": ["thing"], "cardinality": "many-to-many"}),
            ("derived_from", "Entity was extracted or created from this drawer's content", 3,
             {"subject_kinds": ["entity"], "object_kinds": ["entity"], "subject_classes": ["thing"], "object_classes": ["thing"], "cardinality": "many-to-many"}),
            ("tested_by", "Subject is tested by the object test suite or entity", 3,
             {"subject_kinds": ["entity"], "object_kinds": ["entity"], "subject_classes": ["thing"], "object_classes": ["thing"], "cardinality": "many-to-many"}),
        ]
        for name, desc, imp, constraints in predicates:
            self.add_entity(name, kind="predicate", description=desc, importance=imp,
                            properties={"constraints": constraints})

        # ── Intent types (kind=entity, is-a intent_type) ──
        intent_types = [
            # (name, description, importance, parent, slots, tool_permissions_or_None)
            ("inspect", "Intent type for read-only observation", 4, "intent_type",
             {"subject": {"classes": ["thing"], "required": True, "multiple": True}},
             [{"tool": "Read", "scope": "*"}, {"tool": "Grep", "scope": "*"}, {"tool": "Glob", "scope": "*"}]),
            ("modify", "Intent type for changing files", 4, "intent_type",
             {"files": {"classes": ["file"], "required": True, "multiple": True}},
             [{"tool": "Edit", "scope": "{files}"}, {"tool": "Write", "scope": "{files}"},
              {"tool": "Read", "scope": "*"}, {"tool": "Grep", "scope": "*"}, {"tool": "Glob", "scope": "*"}]),
            ("execute", "Intent type for running commands and scripts", 4, "intent_type",
             {"target": {"classes": ["thing"], "required": True, "multiple": True}},
             [{"tool": "Read", "scope": "*"}, {"tool": "Grep", "scope": "*"},
              {"tool": "Glob", "scope": "*"}, {"tool": "Bash", "scope": "*"}]),
            ("communicate", "Intent type for external communication — sending messages, creating issues, pushing to services", 4, "intent_type",
             {"target": {"classes": ["thing"], "required": True, "multiple": True},
              "audience": {"classes": ["person", "agent"], "required": False, "multiple": True}},
             [{"tool": "Read", "scope": "*"}, {"tool": "Grep", "scope": "*"},
              {"tool": "Glob", "scope": "*"}, {"tool": "Bash", "scope": "{target}"}]),
            # Only generic top-level types seeded here.
            # Domain-specific children (edit_file, deploy, etc.) are declared
            # by agents via kg_declare_entity — not hardcoded in the seeder.
        ]
        for name, desc, imp, parent, slots, perms in intent_types:
            props = {"rules_profile": {"slots": slots}}
            if perms is not None:
                props["rules_profile"]["tool_permissions"] = perms
            self.add_entity(name, kind="entity", description=desc, importance=imp, properties=props)
            self.add_triple(name, "is-a", parent)

    def close(self):
        """Close the database connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _entity_id(self, name: str) -> str:
        """Normalize an entity name to a canonical ID.

        Uses aggressive normalization (hyphens, underscores, CamelCase, articles
        all collapsed). Also checks the alias table for merged entities.
        """
        normalized = normalize_entity_name(name)
        # Check if this normalized name is an alias for a merged entity
        conn = self._conn()
        alias_row = conn.execute(
            "SELECT canonical_id FROM entity_aliases WHERE alias = ?", (normalized,)
        ).fetchone()
        if alias_row:
            return alias_row["canonical_id"]
        return normalized

    def _touch_entity(self, entity_id: str):
        """Update last_touched timestamp on an entity."""
        conn = self._conn()
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE entities SET last_touched = ? WHERE id = ?", (now, entity_id)
        )

    # ── Write operations ──────────────────────────────────────────────────

    def add_entity(
        self,
        name: str,
        properties: dict = None,
        description: str = "",
        importance: int = 3,
        kind: str = "entity",
    ):
        """Add or update an entity node.

        Args:
            kind: ontological role — 'entity' (concrete thing), 'predicate' (relationship type),
                  'class' (category/type), 'literal' (raw value). Fixed enum.
            description: precise text describing this entity.
            importance: 1-5 scale for decay-aware ranking.
        """
        eid = self._entity_id(name)
        props = json.dumps(properties or {})
        now = datetime.now().isoformat()
        conn = self._conn()
        with conn:
            conn.execute(
                """INSERT INTO entities (id, name, type, kind, properties, description, importance, last_touched, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
                   ON CONFLICT(id) DO UPDATE SET
                       name = excluded.name,
                       type = excluded.type,
                       kind = excluded.kind,
                       properties = excluded.properties,
                       description = CASE WHEN excluded.description != '' THEN excluded.description ELSE entities.description END,
                       importance = CASE WHEN excluded.importance != 3 THEN excluded.importance ELSE entities.importance END,
                       last_touched = excluded.last_touched
                """,
                (eid, name, kind, kind, props, description, importance, now),
            )
        return eid

    def merge_entities(self, source_name: str, target_name: str, update_description: str = None):
        """Merge source entity into target. All edges rewritten. Source becomes alias.

        Returns dict with counts of edges_moved, aliases_created.
        """
        source_id = normalize_entity_name(source_name)
        target_id = self._entity_id(target_name)  # resolves aliases
        if source_id == target_id:
            return {"error": "source and target resolve to the same entity"}

        conn = self._conn()
        with conn:
            # Rewrite triples: subject
            r1 = conn.execute(
                "UPDATE triples SET subject = ? WHERE subject = ?", (target_id, source_id)
            )
            # Rewrite triples: object
            r2 = conn.execute(
                "UPDATE triples SET object = ? WHERE object = ?", (target_id, source_id)
            )
            edges_moved = r1.rowcount + r2.rowcount

            # Register alias
            now = datetime.now().isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO entity_aliases (alias, canonical_id, merged_at) VALUES (?, ?, ?)",
                (source_id, target_id, now),
            )

            # Soft-delete source
            conn.execute(
                "UPDATE entities SET status = 'merged', merged_into = ? WHERE id = ?",
                (target_id, source_id),
            )

            # Update target description if provided
            if update_description:
                conn.execute(
                    "UPDATE entities SET description = ?, last_touched = ? WHERE id = ?",
                    (update_description, now, target_id),
                )

            # Touch target
            conn.execute(
                "UPDATE entities SET last_touched = ? WHERE id = ?", (now, target_id)
            )

        return {
            "source": source_id,
            "target": target_id,
            "edges_moved": edges_moved,
            "aliases_created": 1,
        }

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
        """
        Add a relationship triple: subject → predicate → object.

        Examples:
            add_triple("Max", "child_of", "Alice", valid_from="2015-04-01")
            add_triple("Max", "does", "swimming", valid_from="2025-01-01")
            add_triple("Alice", "worried_about", "Max injury", valid_from="2026-01", valid_to="2026-02")
        """
        sub_id = self._entity_id(subject)
        obj_id = self._entity_id(obj)
        pred = predicate.lower().replace(" ", "_")

        # Auto-create entities if they don't exist
        conn = self._conn()
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO entities (id, name) VALUES (?, ?)", (sub_id, subject)
            )
            conn.execute("INSERT OR IGNORE INTO entities (id, name) VALUES (?, ?)", (obj_id, obj))

            # Check for existing identical triple
            existing = conn.execute(
                "SELECT id FROM triples WHERE subject=? AND predicate=? AND object=? AND valid_to IS NULL",
                (sub_id, pred, obj_id),
            ).fetchone()

            if existing:
                return existing["id"]  # Already exists and still valid

            triple_id = f"t_{sub_id}_{pred}_{obj_id}_{hashlib.sha256(f'{valid_from}{datetime.now().isoformat()}'.encode()).hexdigest()[:12]}"

            conn.execute(
                """INSERT INTO triples (id, subject, predicate, object, valid_from, valid_to, confidence, source_closet, source_file)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                ),
            )
        # Touch both entities (update last_touched for decay scoring)
        self._touch_entity(sub_id)
        self._touch_entity(obj_id)
        return triple_id

    def invalidate(self, subject: str, predicate: str, obj: str, ended: str = None):
        """Mark a relationship as no longer valid (set valid_to date)."""
        sub_id = self._entity_id(subject)
        obj_id = self._entity_id(obj)
        pred = predicate.lower().replace(" ", "_")
        ended = ended or date.today().isoformat()

        conn = self._conn()
        with conn:
            conn.execute(
                "UPDATE triples SET valid_to=? WHERE subject=? AND predicate=? AND object=? AND valid_to IS NULL",
                (ended, sub_id, pred, obj_id),
            )

    def get_entity(self, name: str):
        """Get entity details by name. Returns dict or None if not found."""
        eid = self._entity_id(name)
        conn = self._conn()
        row = conn.execute("SELECT * FROM entities WHERE id = ? AND status = 'active'", (eid,)).fetchone()
        if not row:
            return None
        # kind column may not exist in very old DBs — fall back to type
        kind = "entity"
        try:
            kind = row["kind"] or "entity"
        except (IndexError, KeyError):
            pass
        return {
            "id": row["id"],
            "name": row["name"],
            "type": row["type"],
            "kind": kind,
            "description": row["description"] or "",
            "importance": row["importance"] or 3,
            "last_touched": row["last_touched"] or "",
            "status": row["status"],
            "properties": json.loads(row["properties"]) if row["properties"] else {},
        }

    def list_entities(self, status: str = "active", kind: str = None):
        """List all entities with the given status, optionally filtered by kind.

        Args:
            status: 'active', 'merged', 'deprecated' (default 'active')
            kind: 'entity', 'predicate', 'class', 'literal' (default None = all)
        """
        conn = self._conn()
        if kind:
            rows = conn.execute(
                "SELECT * FROM entities WHERE status = ? AND kind = ? ORDER BY importance DESC, last_touched DESC",
                (status, kind),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM entities WHERE status = ? ORDER BY importance DESC, last_touched DESC",
                (status,),
            ).fetchall()
        results = []
        for row in rows:
            row_kind = "entity"
            try:
                row_kind = row["kind"] or "entity"
            except (IndexError, KeyError):
                pass
            results.append({
                "id": row["id"],
                "name": row["name"],
                "type": row["type"],
                "kind": row_kind,
                "description": row["description"] or "",
                "importance": row["importance"] or 3,
                "last_touched": row["last_touched"] or "",
            })
        return results

    def update_entity_description(self, name: str, description: str, importance: int = None):
        """Update an entity's description (and optionally importance). Returns the entity."""
        eid = self._entity_id(name)
        now = datetime.now().isoformat()
        conn = self._conn()
        with conn:
            if importance is not None:
                conn.execute(
                    "UPDATE entities SET description = ?, importance = ?, last_touched = ? WHERE id = ?",
                    (description, importance, now, eid),
                )
            else:
                conn.execute(
                    "UPDATE entities SET description = ?, last_touched = ? WHERE id = ?",
                    (description, now, eid),
                )
        return self.get_entity(name)

    def entity_edge_count(self, name: str) -> int:
        """Count active edges (triples) involving an entity."""
        eid = self._entity_id(name)
        conn = self._conn()
        row = conn.execute(
            "SELECT COUNT(*) as n FROM triples WHERE (subject = ? OR object = ?) AND valid_to IS NULL",
            (eid, eid),
        ).fetchone()
        return row["n"] if row else 0

    # ── Query operations ──────────────────────────────────────────────────

    def query_entity(self, name: str, as_of: str = None, direction: str = "outgoing"):
        """
        Get all relationships for an entity.

        direction: "outgoing" (entity → ?), "incoming" (? → entity), "both"
        as_of: date string — only return facts valid at that time
        """
        eid = self._entity_id(name)
        conn = self._conn()

        results = []

        if direction in ("outgoing", "both"):
            query = "SELECT t.*, e.name as obj_name FROM triples t JOIN entities e ON t.object = e.id WHERE t.subject = ?"
            params = [eid]
            if as_of:
                query += " AND (t.valid_from IS NULL OR t.valid_from <= ?) AND (t.valid_to IS NULL OR t.valid_to >= ?)"
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
            query = "SELECT t.*, e.name as sub_name FROM triples t JOIN entities e ON t.subject = e.id WHERE t.object = ?"
            params = [eid]
            if as_of:
                query += " AND (t.valid_from IS NULL OR t.valid_from <= ?) AND (t.valid_to IS NULL OR t.valid_to >= ?)"
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

    def query_relationship(self, predicate: str, as_of: str = None):
        """Get all triples with a given relationship type."""
        pred = predicate.lower().replace(" ", "_")
        conn = self._conn()
        query = """
            SELECT t.*, s.name as sub_name, o.name as obj_name
            FROM triples t
            JOIN entities s ON t.subject = s.id
            JOIN entities o ON t.object = o.id
            WHERE t.predicate = ?
        """
        params = [pred]
        if as_of:
            query += " AND (t.valid_from IS NULL OR t.valid_from <= ?) AND (t.valid_to IS NULL OR t.valid_to >= ?)"
            params.extend([as_of, as_of])

        results = []
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

    def timeline(self, entity_name: str = None):
        """Get all facts in chronological order, optionally filtered by entity."""
        conn = self._conn()
        if entity_name:
            eid = self._entity_id(entity_name)
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
            rows = conn.execute("""
                SELECT t.*, s.name as sub_name, o.name as obj_name
                FROM triples t
                JOIN entities s ON t.subject = s.id
                JOIN entities o ON t.object = o.id
                ORDER BY t.valid_from ASC NULLS LAST
                LIMIT 100
            """).fetchall()

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

    # ── Stats ─────────────────────────────────────────────────────────────

    def stats(self):
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

    # ── Seed from known facts ─────────────────────────────────────────────

    def seed_from_entity_facts(self, entity_facts: dict):
        """
        Seed the knowledge graph from fact_checker.py ENTITY_FACTS.
        This bootstraps the graph with known ground truth.
        """
        for key, facts in entity_facts.items():
            name = facts.get("full_name", key.capitalize())
            self.add_entity(
                name,
                kind="entity",
                description=f"{name} ({facts.get('type', 'person')})",
                properties={
                    "gender": facts.get("gender", ""),
                    "birthday": facts.get("birthday", ""),
                },
            )

            # Relationships
            parent = facts.get("parent")
            if parent:
                self.add_triple(
                    name, "child_of", parent.capitalize(), valid_from=facts.get("birthday")
                )

            partner = facts.get("partner")
            if partner:
                self.add_triple(name, "married_to", partner.capitalize())

            relationship = facts.get("relationship", "")
            if relationship == "daughter":
                self.add_triple(
                    name,
                    "is_child_of",
                    facts.get("parent", "").capitalize() or name,
                    valid_from=facts.get("birthday"),
                )
            elif relationship == "husband":
                self.add_triple(name, "is_partner_of", facts.get("partner", name).capitalize())
            elif relationship == "brother":
                self.add_triple(name, "is_sibling_of", facts.get("sibling", name).capitalize())
            elif relationship == "dog":
                self.add_triple(name, "is_pet_of", facts.get("owner", name).capitalize())
                self.add_entity(name, "animal")

            # Interests
            for interest in facts.get("interests", []):
                self.add_triple(name, "loves", interest.capitalize(), valid_from="2025-01-01")
