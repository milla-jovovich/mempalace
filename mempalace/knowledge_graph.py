"""knowledge_graph.py — Backwards-compatible shim.

The real implementation moved to :mod:`mempalace.kg` so we can support
multiple backends (sqlite, postgres). This shim re-exports the historical
public surface so existing callers do not need to change imports.

Historical API preserved:

    from mempalace.knowledge_graph import KnowledgeGraph, DEFAULT_KG_PATH

    kg = KnowledgeGraph()                          # sqlite, default path
    kg = KnowledgeGraph(db_path="/tmp/x.sqlite3")  # sqlite, explicit path

New (3.3.4+stateless.1):

    kg = KnowledgeGraph(url="postgresql+psycopg://user:pw@host/db")

Or set ``MEMPALACE_DATABASE_URL`` and call ``KnowledgeGraph()`` — the
factory picks Postgres automatically.
"""

from .kg import DEFAULT_KG_PATH, KnowledgeGraph

__all__ = ["KnowledgeGraph", "DEFAULT_KG_PATH"]
