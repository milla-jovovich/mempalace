"""SQLAlchemy 2.x Core table definitions for the KG.

Used by:

* ``PostgresKnowledgeGraph._init_schema()`` for in-process ``create_all`` —
  the simplest path for fresh palaces. Idempotent.
* ``mempalace/migrations/`` (Alembic) — for production deployments that
  need auditable, reversible schema changes.

The same ``MetaData`` object underpins both so the canonical schema lives
in exactly one place.
"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    MetaData,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON, TypeDecorator


class JSONOrJSONB(TypeDecorator):
    """JSONB on Postgres, plain JSON elsewhere (sqlite TEXT-encoded)."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


metadata = MetaData()

entities = Table(
    "kg_entities",
    metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("type", Text, nullable=False, server_default="unknown"),
    Column("properties", JSONOrJSONB, nullable=False, server_default="{}"),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
)

triples = Table(
    "kg_triples",
    metadata,
    Column("id", Text, primary_key=True),
    Column(
        "subject",
        Text,
        ForeignKey("kg_entities.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("predicate", Text, nullable=False),
    Column(
        "object",
        Text,
        ForeignKey("kg_entities.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("valid_from", Text),
    Column("valid_to", Text),
    Column("confidence", Float, nullable=False, server_default="1.0"),
    Column("source_closet", Text),
    Column("source_file", Text),
    Column("source_drawer_id", Text),
    Column("adapter_name", Text),
    Column(
        "extracted_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Index("idx_kg_triples_subject", "subject"),
    Index("idx_kg_triples_object", "object"),
    Index("idx_kg_triples_predicate", "predicate"),
    Index("idx_kg_triples_valid", "valid_from", "valid_to"),
    Index("idx_kg_triples_active", "subject", "predicate", "object"),
)

__all__ = ["metadata", "entities", "triples", "JSONOrJSONB"]
