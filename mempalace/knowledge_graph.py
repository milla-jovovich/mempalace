"""
knowledge_graph.py — Temporal Entity-Relationship Graph for MemPalace
=====================================================================

Real knowledge graph with:
  - Entity nodes (people, projects, tools, concepts)
  - Typed relationship edges (daughter_of, does, loves, works_on, etc.)
  - Temporal validity (valid_from -> valid_to -- knows WHEN facts are true)
  - Closet references (links back to the verbatim memory)

Backends:
  - SQLite (default, local, no dependencies)
  - Elasticsearch (when graph_backend="elasticsearch" in config)

Usage:
    from mempalace.knowledge_graph import get_knowledge_graph
    kg = get_knowledge_graph()
"""

import hashlib
import json
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path


DEFAULT_KG_PATH = os.path.expanduser("~/.mempalace/knowledge_graph.sqlite3")


class KnowledgeGraph:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or DEFAULT_KG_PATH
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = self._conn()
        conn.executescript("""
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
        conn.close()

    def _conn(self):
        return sqlite3.connect(self.db_path, timeout=10)

    def _entity_id(self, name: str) -> str:
        return name.lower().replace(" ", "_").replace("'", "")

    # ── Write operations ──────────────────────────────────────────────────

    def add_entity(self, name: str, entity_type: str = "unknown", properties: dict = None):
        """Add or update an entity node."""
        eid = self._entity_id(name)
        props = json.dumps(properties or {})
        conn = self._conn()
        conn.execute(
            "INSERT OR REPLACE INTO entities (id, name, type, properties) VALUES (?, ?, ?, ?)",
            (eid, name, entity_type, props),
        )
        conn.commit()
        conn.close()
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
        conn.execute("INSERT OR IGNORE INTO entities (id, name) VALUES (?, ?)", (sub_id, subject))
        conn.execute("INSERT OR IGNORE INTO entities (id, name) VALUES (?, ?)", (obj_id, obj))

        # Check for existing identical triple
        existing = conn.execute(
            "SELECT id FROM triples WHERE subject=? AND predicate=? AND object=? AND valid_to IS NULL",
            (sub_id, pred, obj_id),
        ).fetchone()

        if existing:
            conn.close()
            return existing[0]  # Already exists and still valid

        triple_id = f"t_{sub_id}_{pred}_{obj_id}_{hashlib.md5(f'{valid_from}{datetime.now().isoformat()}'.encode()).hexdigest()[:8]}"

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
        conn.commit()
        conn.close()
        return triple_id

    def invalidate(self, subject: str, predicate: str, obj: str, ended: str = None):
        """Mark a relationship as no longer valid (set valid_to date)."""
        sub_id = self._entity_id(subject)
        obj_id = self._entity_id(obj)
        pred = predicate.lower().replace(" ", "_")
        ended = ended or date.today().isoformat()

        conn = self._conn()
        conn.execute(
            "UPDATE triples SET valid_to=? WHERE subject=? AND predicate=? AND object=? AND valid_to IS NULL",
            (ended, sub_id, pred, obj_id),
        )
        conn.commit()
        conn.close()

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
                        "predicate": row[2],
                        "object": row[10],  # obj_name
                        "valid_from": row[4],
                        "valid_to": row[5],
                        "confidence": row[6],
                        "source_closet": row[7],
                        "current": row[5] is None,
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
                        "subject": row[10],  # sub_name
                        "predicate": row[2],
                        "object": name,
                        "valid_from": row[4],
                        "valid_to": row[5],
                        "confidence": row[6],
                        "source_closet": row[7],
                        "current": row[5] is None,
                    }
                )

        conn.close()
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
                    "subject": row[10],
                    "predicate": pred,
                    "object": row[11],
                    "valid_from": row[4],
                    "valid_to": row[5],
                    "current": row[5] is None,
                }
            )
        conn.close()
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

        conn.close()
        return [
            {
                "subject": r[10],
                "predicate": r[2],
                "object": r[11],
                "valid_from": r[4],
                "valid_to": r[5],
                "current": r[5] is None,
            }
            for r in rows
        ]

    # ── Stats ─────────────────────────────────────────────────────────────

    def stats(self):
        conn = self._conn()
        entities = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        triples = conn.execute("SELECT COUNT(*) FROM triples").fetchone()[0]
        current = conn.execute("SELECT COUNT(*) FROM triples WHERE valid_to IS NULL").fetchone()[0]
        expired = triples - current
        predicates = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT predicate FROM triples ORDER BY predicate"
            ).fetchall()
        ]
        conn.close()
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
            etype = facts.get("type", "person")
            self.add_entity(
                name,
                etype,
                {
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


# =============================================================================
# Elasticsearch Knowledge Graph
# =============================================================================


class ElasticsearchKnowledgeGraph:
    """Knowledge graph stored in Elasticsearch indices.

    Uses two indices:
      - {prefix}-kg-entities: entity nodes
      - {prefix}-kg-triples: relationship triples
    """

    def __init__(self, config=None):
        from .config import MempalaceConfig

        config = config or MempalaceConfig()
        es_conf = config._file_config.get("elasticsearch", {})

        self._prefix = es_conf.get("index_prefix", "mempalace")
        self._entities_index = f"{self._prefix}-kg-entities"
        self._triples_index = f"{self._prefix}-kg-triples"

        try:
            from elasticsearch import Elasticsearch
        except ImportError:
            raise ImportError(
                "elasticsearch package required for ES graph backend. "
                "Install with: pip install 'mempalace[elasticsearch]'"
            )

        hosts = es_conf.get("hosts", ["http://localhost:9200"])
        api_key = es_conf.get("api_key")
        connect_kwargs = {"hosts": hosts, "request_timeout": 30}
        if api_key:
            connect_kwargs["api_key"] = api_key

        self._es = Elasticsearch(**connect_kwargs)
        self._ensure_indices()

    def _ensure_indices(self):
        if not self._es.indices.exists(index=self._entities_index):
            self._es.indices.create(
                index=self._entities_index,
                body={
                    "mappings": {
                        "properties": {
                            "name": {"type": "keyword"},
                            "name_text": {"type": "text"},
                            "type": {"type": "keyword"},
                            "properties": {"type": "text"},
                            "created_at": {"type": "keyword"},
                        }
                    }
                },
            )
        if not self._es.indices.exists(index=self._triples_index):
            self._es.indices.create(
                index=self._triples_index,
                body={
                    "mappings": {
                        "properties": {
                            "subject": {"type": "keyword"},
                            "predicate": {"type": "keyword"},
                            "object": {"type": "keyword"},
                            "subject_name": {"type": "text"},
                            "object_name": {"type": "text"},
                            "valid_from": {"type": "keyword"},
                            "valid_to": {"type": "keyword"},
                            "confidence": {"type": "float"},
                            "source_closet": {"type": "keyword"},
                            "source_file": {"type": "keyword"},
                            "extracted_at": {"type": "keyword"},
                        }
                    }
                },
            )

    def _entity_id(self, name: str) -> str:
        return name.lower().replace(" ", "_").replace("'", "")

    def add_entity(self, name: str, entity_type: str = "unknown", properties: dict = None):
        eid = self._entity_id(name)
        self._es.index(
            index=self._entities_index,
            id=eid,
            document={
                "name": name,
                "name_text": name,
                "type": entity_type,
                "properties": json.dumps(properties or {}),
                "created_at": datetime.now().isoformat(),
            },
            refresh="wait_for",
        )
        return eid

    def add_triple(
        self,
        subject,
        predicate,
        obj,
        valid_from=None,
        valid_to=None,
        confidence=1.0,
        source_closet=None,
        source_file=None,
    ):
        sub_id = self._entity_id(subject)
        obj_id = self._entity_id(obj)
        pred = predicate.lower().replace(" ", "_")

        # Auto-create entities
        for eid, name in [(sub_id, subject), (obj_id, obj)]:
            if not self._es.exists(index=self._entities_index, id=eid):
                self._es.index(
                    index=self._entities_index,
                    id=eid,
                    document={"name": name, "name_text": name, "type": "unknown", "properties": "{}"},
                )

        # Check for existing active triple
        existing = self._es.search(
            index=self._triples_index,
            query={
                "bool": {
                    "must": [
                        {"term": {"subject": sub_id}},
                        {"term": {"predicate": pred}},
                        {"term": {"object": obj_id}},
                    ],
                    "must_not": [{"exists": {"field": "valid_to"}}],
                }
            },
            size=1,
        )
        if existing["hits"]["hits"]:
            return existing["hits"]["hits"][0]["_id"]

        triple_id = (
            f"t_{sub_id}_{pred}_{obj_id}_"
            f"{hashlib.md5(f'{valid_from}{datetime.now().isoformat()}'.encode()).hexdigest()[:8]}"
        )
        self._es.index(
            index=self._triples_index,
            id=triple_id,
            document={
                "subject": sub_id,
                "predicate": pred,
                "object": obj_id,
                "subject_name": subject,
                "object_name": obj,
                "valid_from": valid_from,
                "valid_to": valid_to,
                "confidence": confidence,
                "source_closet": source_closet,
                "source_file": source_file,
                "extracted_at": datetime.now().isoformat(),
            },
            refresh="wait_for",
        )
        return triple_id

    def invalidate(self, subject, predicate, obj, ended=None):
        sub_id = self._entity_id(subject)
        obj_id = self._entity_id(obj)
        pred = predicate.lower().replace(" ", "_")
        ended = ended or date.today().isoformat()

        self._es.update_by_query(
            index=self._triples_index,
            body={
                "script": {"source": f"ctx._source.valid_to = '{ended}'"},
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"subject": sub_id}},
                            {"term": {"predicate": pred}},
                            {"term": {"object": obj_id}},
                        ],
                        "must_not": [{"exists": {"field": "valid_to"}}],
                    }
                },
            },
            refresh=True,
        )

    def query_entity(self, name, as_of=None, direction="outgoing"):
        eid = self._entity_id(name)
        results = []

        if direction in ("outgoing", "both"):
            results.extend(self._query_direction(name, eid, "subject", "object", as_of, "outgoing"))
        if direction in ("incoming", "both"):
            results.extend(self._query_direction(name, eid, "object", "subject", as_of, "incoming"))
        return results

    def _query_direction(self, name, eid, match_field, other_field, as_of, direction):
        must = [{"term": {match_field: eid}}]
        if as_of:
            must.append(
                {
                    "bool": {
                        "should": [
                            {"bool": {"must_not": [{"exists": {"field": "valid_from"}}]}},
                            {"range": {"valid_from": {"lte": as_of}}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )
            must.append(
                {
                    "bool": {
                        "should": [
                            {"bool": {"must_not": [{"exists": {"field": "valid_to"}}]}},
                            {"range": {"valid_to": {"gte": as_of}}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )

        resp = self._es.search(index=self._triples_index, query={"bool": {"must": must}}, size=1000)

        results = []
        for hit in resp["hits"]["hits"]:
            src = hit["_source"]
            other_name = src.get("object_name", src["object"]) if direction == "outgoing" else src.get("subject_name", src["subject"])
            results.append(
                {
                    "direction": direction,
                    "subject": name if direction == "outgoing" else other_name,
                    "predicate": src["predicate"],
                    "object": other_name if direction == "outgoing" else name,
                    "valid_from": src.get("valid_from"),
                    "valid_to": src.get("valid_to"),
                    "confidence": src.get("confidence", 1.0),
                    "source_closet": src.get("source_closet"),
                    "current": src.get("valid_to") is None,
                }
            )
        return results

    def query_relationship(self, predicate, as_of=None):
        pred = predicate.lower().replace(" ", "_")
        must = [{"term": {"predicate": pred}}]
        if as_of:
            must.append(
                {
                    "bool": {
                        "should": [
                            {"bool": {"must_not": [{"exists": {"field": "valid_from"}}]}},
                            {"range": {"valid_from": {"lte": as_of}}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )
            must.append(
                {
                    "bool": {
                        "should": [
                            {"bool": {"must_not": [{"exists": {"field": "valid_to"}}]}},
                            {"range": {"valid_to": {"gte": as_of}}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )

        resp = self._es.search(index=self._triples_index, query={"bool": {"must": must}}, size=1000)
        return [
            {
                "subject": h["_source"].get("subject_name", h["_source"]["subject"]),
                "predicate": pred,
                "object": h["_source"].get("object_name", h["_source"]["object"]),
                "valid_from": h["_source"].get("valid_from"),
                "valid_to": h["_source"].get("valid_to"),
                "current": h["_source"].get("valid_to") is None,
            }
            for h in resp["hits"]["hits"]
        ]

    def timeline(self, entity_name=None):
        if entity_name:
            eid = self._entity_id(entity_name)
            query = {
                "bool": {
                    "should": [{"term": {"subject": eid}}, {"term": {"object": eid}}],
                    "minimum_should_match": 1,
                }
            }
        else:
            query = {"match_all": {}}

        resp = self._es.search(
            index=self._triples_index,
            query=query,
            sort=[{"valid_from": {"order": "asc", "missing": "_last"}}],
            size=100,
        )
        return [
            {
                "subject": h["_source"].get("subject_name", h["_source"]["subject"]),
                "predicate": h["_source"]["predicate"],
                "object": h["_source"].get("object_name", h["_source"]["object"]),
                "valid_from": h["_source"].get("valid_from"),
                "valid_to": h["_source"].get("valid_to"),
                "current": h["_source"].get("valid_to") is None,
            }
            for h in resp["hits"]["hits"]
        ]

    def stats(self):
        entities = self._es.count(index=self._entities_index)["count"]
        triples = self._es.count(index=self._triples_index)["count"]
        current = self._es.count(
            index=self._triples_index,
            query={"bool": {"must_not": [{"exists": {"field": "valid_to"}}]}},
        )["count"]

        preds_resp = self._es.search(
            index=self._triples_index,
            size=0,
            aggs={"predicates": {"terms": {"field": "predicate", "size": 100}}},
        )
        predicates = [
            b["key"] for b in preds_resp["aggregations"]["predicates"]["buckets"]
        ]

        return {
            "entities": entities,
            "triples": triples,
            "current_facts": current,
            "expired_facts": triples - current,
            "relationship_types": sorted(predicates),
        }

    def seed_from_entity_facts(self, entity_facts):
        for key, facts in entity_facts.items():
            name = facts.get("full_name", key.capitalize())
            etype = facts.get("type", "person")
            self.add_entity(
                name,
                etype,
                {"gender": facts.get("gender", ""), "birthday": facts.get("birthday", "")},
            )
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


# =============================================================================
# Factory
# =============================================================================


def get_knowledge_graph(config=None):
    """Return the appropriate KnowledgeGraph backend based on configuration."""
    from .config import MempalaceConfig

    config = config or MempalaceConfig()
    if config.graph_backend == "elasticsearch":
        return ElasticsearchKnowledgeGraph(config)
    return KnowledgeGraph()
