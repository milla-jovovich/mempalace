"""Knowledge graph backend package.

The ``KnowledgeGraph`` class re-exported here is a *factory* that picks the
right backend based on its arguments and the runtime config. Existing callers
that import ``from mempalace.knowledge_graph import KnowledgeGraph`` keep
working unchanged thanks to the shim in ``mempalace/knowledge_graph.py``.

Two backends ship in-tree:

* ``SqliteKnowledgeGraph`` — the original implementation, file-backed sqlite3.
  Default when no Postgres URL is configured.
* ``PostgresKnowledgeGraph`` — SQLAlchemy 2.x Core against Postgres. Selected
  when ``url`` (or ``MEMPALACE_DATABASE_URL``) is provided.

Both implement the :class:`BaseKnowledgeGraph` contract so callers can treat
them interchangeably.
"""

from .base import BaseKnowledgeGraph
from .factory import DEFAULT_KG_PATH, KnowledgeGraph

__all__ = [
    "BaseKnowledgeGraph",
    "DEFAULT_KG_PATH",
    "KnowledgeGraph",
]
