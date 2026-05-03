"""Factory selecting the right KG backend at construction time.

Priority (first non-empty wins):

1. Explicit ``url=`` keyword argument → Postgres backend.
2. ``MEMPALACE_DATABASE_URL`` env var → Postgres backend.
3. Explicit ``db_path=`` keyword argument → SQLite backend.
4. ``MEMPALACE_KG_PATH`` env var → SQLite backend at that path.
5. Default → SQLite at ``~/.mempalace/knowledge_graph.sqlite3``.

The returned object is a :class:`BaseKnowledgeGraph` so callers can ignore
which backend they got. For backwards compatibility, ``KnowledgeGraph(...)``
remains the canonical constructor — existing imports keep working.
"""

from __future__ import annotations

import os
from typing import Optional

from .base import BaseKnowledgeGraph
from .sqlite import DEFAULT_KG_PATH, SqliteKnowledgeGraph

_POSTGRES_URL_ENV = "MEMPALACE_DATABASE_URL"
_SQLITE_PATH_ENV = "MEMPALACE_KG_PATH"


def _resolve_url(url: Optional[str]) -> Optional[str]:
    if url:
        return url
    env = os.environ.get(_POSTGRES_URL_ENV)
    return env or None


def _resolve_path(db_path: Optional[str]) -> str:
    if db_path:
        return db_path
    env = os.environ.get(_SQLITE_PATH_ENV)
    return env or DEFAULT_KG_PATH


def KnowledgeGraph(
    db_path: Optional[str] = None,
    *,
    url: Optional[str] = None,
) -> BaseKnowledgeGraph:
    """Open a knowledge graph using the appropriate backend.

    Backwards-compatible with ``KnowledgeGraph(db_path=...)`` and
    ``KnowledgeGraph()`` (defaults). Add ``url=`` (or set
    ``MEMPALACE_DATABASE_URL``) to use Postgres instead.
    """
    resolved_url = _resolve_url(url)
    if resolved_url:
        from .postgres import PostgresKnowledgeGraph

        return PostgresKnowledgeGraph(resolved_url)
    return SqliteKnowledgeGraph(_resolve_path(db_path))


__all__ = ["KnowledgeGraph", "DEFAULT_KG_PATH"]
