"""Postgres-backed knowledge graph (SQLAlchemy 2.x Core).

Selected when ``MEMPALACE_DATABASE_URL`` is set or when the application
explicitly passes ``url=`` to :class:`KnowledgeGraph`.

Design notes:

* SQLAlchemy 2.x Core, no ORM.
* Schema lives in :mod:`mempalace.kg._schema` and is shared with Alembic.
* Upserts use the dialect-native ``INSERT ... ON CONFLICT`` form so they
  collapse to one round-trip per write.
* ``valid_from`` / ``valid_to`` stay as ISO date strings (TEXT) for a
  bit-for-bit compatible result shape with the sqlite backend; the rest
  of the codebase treats them as opaque ISO strings already.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Optional

try:
    from sqlalchemy import URL, and_, create_engine, func, or_, select
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.engine import Engine
except ImportError as e:  # pragma: no cover - import guard
    raise ImportError(
        "PostgresKnowledgeGraph requires SQLAlchemy. Install with: "
        "pip install 'mempalace[postgres]'"
    ) from e

from ._schema import entities, metadata, triples
from .base import BaseKnowledgeGraph


class PostgresKnowledgeGraph(BaseKnowledgeGraph):
    """SQLAlchemy-backed KG. Pool-managed connections, dialect-native upserts."""

    def __init__(
        self,
        url: str | URL,
        *,
        echo: bool = False,
        pool_size: int = 5,
        pool_pre_ping: bool = True,
        engine: Optional[Engine] = None,
    ):
        self.url = url
        if engine is not None:
            self._engine = engine
            self._owns_engine = False
        else:
            self._engine = create_engine(
                url,
                echo=echo,
                pool_size=pool_size,
                pool_pre_ping=pool_pre_ping,
                future=True,
            )
            self._owns_engine = True
        self._init_schema()

    def _init_schema(self) -> None:
        """Create tables if missing. Safe to call repeatedly."""
        metadata.create_all(self._engine)

    def close(self) -> None:
        if self._owns_engine and self._engine is not None:
            self._engine.dispose()

    # ── Writes ───────────────────────────────────────────────────────────

    def add_entity(
        self,
        name: str,
        entity_type: str = "unknown",
        properties: Optional[dict] = None,
    ) -> str:
        eid = self.entity_id(name)
        props = properties or {}
        stmt = pg_insert(entities).values(
            id=eid, name=name, type=entity_type, properties=props
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[entities.c.id],
            set_={
                "name": stmt.excluded.name,
                "type": stmt.excluded.type,
                "properties": stmt.excluded.properties,
            },
        )
        with self._engine.begin() as conn:
            conn.execute(stmt)
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

        with self._engine.begin() as conn:
            # Auto-create entities if missing (no-op when present).
            for eid, ename in ((sub_id, subject), (obj_id, obj)):
                stmt = (
                    pg_insert(entities)
                    .values(id=eid, name=ename)
                    .on_conflict_do_nothing(index_elements=[entities.c.id])
                )
                conn.execute(stmt)

            existing = conn.execute(
                select(triples.c.id).where(
                    and_(
                        triples.c.subject == sub_id,
                        triples.c.predicate == pred,
                        triples.c.object == obj_id,
                        triples.c.valid_to.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing

            triple_id = (
                f"t_{sub_id}_{pred}_{obj_id}_"
                + hashlib.sha256(
                    f"{valid_from}{datetime.now().isoformat()}".encode()
                ).hexdigest()[:12]
            )
            conn.execute(
                triples.insert().values(
                    id=triple_id,
                    subject=sub_id,
                    predicate=pred,
                    object=obj_id,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    confidence=confidence,
                    source_closet=source_closet,
                    source_file=source_file,
                    source_drawer_id=source_drawer_id,
                    adapter_name=adapter_name,
                )
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

        with self._engine.begin() as conn:
            conn.execute(
                triples.update()
                .where(
                    and_(
                        triples.c.subject == sub_id,
                        triples.c.predicate == pred,
                        triples.c.object == obj_id,
                        triples.c.valid_to.is_(None),
                    )
                )
                .values(valid_to=ended)
            )

    # ── Reads ────────────────────────────────────────────────────────────

    @staticmethod
    def _temporal_filter(as_of: Optional[str]):
        if not as_of:
            return None
        return and_(
            or_(triples.c.valid_from.is_(None), triples.c.valid_from <= as_of),
            or_(triples.c.valid_to.is_(None), triples.c.valid_to >= as_of),
        )

    def query_entity(
        self,
        name: str,
        as_of: Optional[str] = None,
        direction: str = "outgoing",
    ) -> list[dict]:
        eid = self.entity_id(name)
        results: list[dict] = []

        with self._engine.connect() as conn:
            if direction in ("outgoing", "both"):
                obj_e = entities.alias("obj_e")
                stmt = (
                    select(
                        triples.c.predicate,
                        obj_e.c.name.label("obj_name"),
                        triples.c.valid_from,
                        triples.c.valid_to,
                        triples.c.confidence,
                        triples.c.source_closet,
                    )
                    .select_from(triples.join(obj_e, triples.c.object == obj_e.c.id))
                    .where(triples.c.subject == eid)
                )
                tf = self._temporal_filter(as_of)
                if tf is not None:
                    stmt = stmt.where(tf)
                for row in conn.execute(stmt):
                    results.append(
                        {
                            "direction": "outgoing",
                            "subject": name,
                            "predicate": row.predicate,
                            "object": row.obj_name,
                            "valid_from": row.valid_from,
                            "valid_to": row.valid_to,
                            "confidence": row.confidence,
                            "source_closet": row.source_closet,
                            "current": row.valid_to is None,
                        }
                    )

            if direction in ("incoming", "both"):
                sub_e = entities.alias("sub_e")
                stmt = (
                    select(
                        triples.c.predicate,
                        sub_e.c.name.label("sub_name"),
                        triples.c.valid_from,
                        triples.c.valid_to,
                        triples.c.confidence,
                        triples.c.source_closet,
                    )
                    .select_from(triples.join(sub_e, triples.c.subject == sub_e.c.id))
                    .where(triples.c.object == eid)
                )
                tf = self._temporal_filter(as_of)
                if tf is not None:
                    stmt = stmt.where(tf)
                for row in conn.execute(stmt):
                    results.append(
                        {
                            "direction": "incoming",
                            "subject": row.sub_name,
                            "predicate": row.predicate,
                            "object": name,
                            "valid_from": row.valid_from,
                            "valid_to": row.valid_to,
                            "confidence": row.confidence,
                            "source_closet": row.source_closet,
                            "current": row.valid_to is None,
                        }
                    )
        return results

    def query_relationship(
        self, predicate: str, as_of: Optional[str] = None
    ) -> list[dict]:
        pred = predicate.lower().replace(" ", "_")
        sub_e = entities.alias("sub_e")
        obj_e = entities.alias("obj_e")
        stmt = (
            select(
                sub_e.c.name.label("sub_name"),
                obj_e.c.name.label("obj_name"),
                triples.c.valid_from,
                triples.c.valid_to,
            )
            .select_from(
                triples.join(sub_e, triples.c.subject == sub_e.c.id).join(
                    obj_e, triples.c.object == obj_e.c.id
                )
            )
            .where(triples.c.predicate == pred)
        )
        tf = self._temporal_filter(as_of)
        if tf is not None:
            stmt = stmt.where(tf)

        results: list[dict] = []
        with self._engine.connect() as conn:
            for row in conn.execute(stmt):
                results.append(
                    {
                        "subject": row.sub_name,
                        "predicate": pred,
                        "object": row.obj_name,
                        "valid_from": row.valid_from,
                        "valid_to": row.valid_to,
                        "current": row.valid_to is None,
                    }
                )
        return results

    def timeline(self, entity_name: Optional[str] = None) -> list[dict]:
        sub_e = entities.alias("sub_e")
        obj_e = entities.alias("obj_e")
        stmt = (
            select(
                sub_e.c.name.label("sub_name"),
                triples.c.predicate,
                obj_e.c.name.label("obj_name"),
                triples.c.valid_from,
                triples.c.valid_to,
            )
            .select_from(
                triples.join(sub_e, triples.c.subject == sub_e.c.id).join(
                    obj_e, triples.c.object == obj_e.c.id
                )
            )
            .order_by(triples.c.valid_from.asc().nulls_last())
            .limit(100)
        )
        if entity_name:
            eid = self.entity_id(entity_name)
            stmt = stmt.where(or_(triples.c.subject == eid, triples.c.object == eid))

        with self._engine.connect() as conn:
            rows = conn.execute(stmt).all()
        return [
            {
                "subject": r.sub_name,
                "predicate": r.predicate,
                "object": r.obj_name,
                "valid_from": r.valid_from,
                "valid_to": r.valid_to,
                "current": r.valid_to is None,
            }
            for r in rows
        ]

    def stats(self) -> dict:
        with self._engine.connect() as conn:
            ents = conn.execute(select(func.count()).select_from(entities)).scalar_one()
            tris = conn.execute(select(func.count()).select_from(triples)).scalar_one()
            current = conn.execute(
                select(func.count())
                .select_from(triples)
                .where(triples.c.valid_to.is_(None))
            ).scalar_one()
            expired = tris - current
            preds = [
                r[0]
                for r in conn.execute(
                    select(triples.c.predicate)
                    .distinct()
                    .order_by(triples.c.predicate)
                ).all()
            ]
        return {
            "entities": ents,
            "triples": tris,
            "current_facts": current,
            "expired_facts": expired,
            "relationship_types": preds,
        }
