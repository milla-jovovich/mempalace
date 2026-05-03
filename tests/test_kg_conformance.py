"""Backend conformance tests for the knowledge graph.

Runs the same behavioral test set against every available backend so
sqlite and postgres stay byte-for-byte interchangeable.

Tiers:

* ``sqlite`` — the canonical :class:`SqliteKnowledgeGraph` against a temp
  file. Always runs.
* ``sqlalchemy_sqlite`` — :class:`PostgresKnowledgeGraph` driving sqlite
  via SQLAlchemy. Catches SQLAlchemy-layer bugs without needing docker.
  Modern sqlite (≥3.24) accepts the same ``ON CONFLICT`` syntax we emit
  for Postgres, so this is a useful substitute. Always runs.
* ``postgres`` — :class:`PostgresKnowledgeGraph` against a real Postgres
  via ``testcontainers``. Skipped when ``POSTGRES_TEST_URL`` is not set
  and ``testcontainers`` cannot launch one (no docker socket available).
  Tagged ``@pytest.mark.postgres``.
"""

from __future__ import annotations

import os

import pytest

from mempalace.kg.sqlite import SqliteKnowledgeGraph

try:
    from mempalace.kg.postgres import PostgresKnowledgeGraph

    HAVE_SQLALCHEMY = True
except ImportError:
    HAVE_SQLALCHEMY = False


# ── Backend factories ────────────────────────────────────────────────────


def _factory_sqlite(tmp_path):
    return SqliteKnowledgeGraph(db_path=str(tmp_path / "kg.sqlite3"))


def _factory_sqlalchemy_sqlite(tmp_path):
    return PostgresKnowledgeGraph(
        f"sqlite+pysqlite:///{tmp_path / 'kg_alchemy.sqlite3'}"
    )


def _factory_postgres(tmp_path):  # pragma: no cover - exercised via mark
    url = os.environ.get("POSTGRES_TEST_URL")
    if url:
        return PostgresKnowledgeGraph(url)
    pytest.importorskip("testcontainers.postgres")
    from testcontainers.postgres import PostgresContainer

    container = PostgresContainer("postgres:16-alpine").start()
    pytest.skip_if_xdist = True  # noqa: S101 - one-shot
    url = container.get_connection_url().replace("postgresql://", "postgresql+psycopg://")
    kg = PostgresKnowledgeGraph(url)
    # Stash the container on the kg so the fixture can stop it.
    kg._test_container = container  # type: ignore[attr-defined]
    return kg


_BACKENDS = []
_BACKENDS.append(("sqlite", _factory_sqlite, []))
if HAVE_SQLALCHEMY:
    _BACKENDS.append(("sqlalchemy_sqlite", _factory_sqlalchemy_sqlite, []))
    _BACKENDS.append(("postgres", _factory_postgres, [pytest.mark.postgres]))


@pytest.fixture(
    params=[
        pytest.param(factory, id=name, marks=marks)
        for name, factory, marks in _BACKENDS
    ]
)
def conformant_kg(request, tmp_path):
    factory = request.param
    kg = factory(tmp_path)
    yield kg
    kg.close()
    container = getattr(kg, "_test_container", None)
    if container is not None:
        container.stop()


# ── Tests ────────────────────────────────────────────────────────────────


def test_add_entity_returns_canonical_id(conformant_kg):
    assert conformant_kg.add_entity("Dr. Chen", "person") == "dr._chen"


def test_add_entity_upserts(conformant_kg):
    conformant_kg.add_entity("Alice", "person", {"age": 1})
    conformant_kg.add_entity("Alice", "engineer", {"age": 2})
    assert conformant_kg.stats()["entities"] == 1


def test_add_triple_creates_entities(conformant_kg):
    conformant_kg.add_triple("Alice", "knows", "Bob")
    s = conformant_kg.stats()
    assert s["entities"] == 2
    assert s["triples"] == 1


def test_duplicate_triple_returns_existing(conformant_kg):
    t1 = conformant_kg.add_triple("Alice", "knows", "Bob")
    t2 = conformant_kg.add_triple("Alice", "knows", "Bob")
    assert t1 == t2


def test_invalidate_then_re_add(conformant_kg):
    t1 = conformant_kg.add_triple("Alice", "works_at", "Acme")
    conformant_kg.invalidate("Alice", "works_at", "Acme", ended="2025-01-01")
    t2 = conformant_kg.add_triple("Alice", "works_at", "Acme")
    assert t1 != t2
    s = conformant_kg.stats()
    assert s["current_facts"] == 1
    assert s["expired_facts"] == 1


def test_query_outgoing(conformant_kg):
    conformant_kg.add_triple("Alice", "parent_of", "Max", valid_from="2015-04-01")
    out = conformant_kg.query_entity("Alice", direction="outgoing")
    assert any(r["object"] == "Max" and r["predicate"] == "parent_of" for r in out)


def test_query_incoming(conformant_kg):
    conformant_kg.add_triple("Alice", "parent_of", "Max", valid_from="2015-04-01")
    inc = conformant_kg.query_entity("Max", direction="incoming")
    assert any(r["subject"] == "Alice" for r in inc)


def test_query_both(conformant_kg):
    conformant_kg.add_triple("Alice", "parent_of", "Max", valid_from="2015-04-01")
    conformant_kg.add_triple("Max", "loves", "swimming", valid_from="2025-01-01")
    both = conformant_kg.query_entity("Max", direction="both")
    directions = {r["direction"] for r in both}
    assert directions == {"outgoing", "incoming"}


def test_query_as_of_filters(conformant_kg):
    conformant_kg.add_triple(
        "Alice", "works_at", "Acme", valid_from="2020-01-01", valid_to="2024-12-31"
    )
    conformant_kg.add_triple("Alice", "works_at", "NewCo", valid_from="2025-01-01")
    past = conformant_kg.query_entity("Alice", as_of="2023-06-01", direction="outgoing")
    employers = {r["object"] for r in past if r["predicate"] == "works_at"}
    assert "Acme" in employers and "NewCo" not in employers
    now = conformant_kg.query_entity("Alice", as_of="2025-06-01", direction="outgoing")
    employers = {r["object"] for r in now if r["predicate"] == "works_at"}
    assert "NewCo" in employers and "Acme" not in employers


def test_query_relationship(conformant_kg):
    conformant_kg.add_triple("Max", "loves", "swimming", valid_from="2025-01-01")
    conformant_kg.add_triple("Alice", "loves", "tea", valid_from="2024-01-01")
    rs = conformant_kg.query_relationship("loves")
    objects = {r["object"] for r in rs}
    assert objects == {"swimming", "tea"}


def test_timeline_orders_chronologically_nulls_last(conformant_kg):
    conformant_kg.add_triple("Alice", "did", "thingA", valid_from="2024-01-01")
    conformant_kg.add_triple("Alice", "did", "thingB")  # no valid_from -> last
    conformant_kg.add_triple("Alice", "did", "thingC", valid_from="2023-01-01")
    tl = conformant_kg.timeline("Alice")
    objs = [r["object"] for r in tl]
    assert objs[0] == "thingC"
    assert objs[1] == "thingA"
    assert objs[2] == "thingB"


def test_stats_shape(conformant_kg):
    conformant_kg.add_triple("Alice", "knows", "Bob")
    s = conformant_kg.stats()
    assert set(s.keys()) == {
        "entities",
        "triples",
        "current_facts",
        "expired_facts",
        "relationship_types",
    }


def test_seed_from_entity_facts(conformant_kg):
    conformant_kg.seed_from_entity_facts(
        {
            "alice": {
                "full_name": "Alice",
                "type": "person",
                "interests": ["chess"],
            }
        }
    )
    out = conformant_kg.query_entity("Alice", direction="outgoing")
    assert any(r["predicate"] == "loves" and r["object"] == "Chess" for r in out)
