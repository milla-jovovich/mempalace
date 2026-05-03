"""TDD: SqliteKnowledgeGraph.close() must hold self._lock.

The historical ``KnowledgeGraph`` class became a factory in 3.3.4+stateless.1
(``mempalace.kg.factory.KnowledgeGraph``) so the lock-acquisition assertion
moved down to the concrete sqlite backend, which is where the lock lives.
Postgres uses a SQLAlchemy connection pool and does not need an explicit
lock around ``close``.
"""

import inspect

from mempalace.kg.sqlite import SqliteKnowledgeGraph


class TestKGCloseLock:
    def test_close_holds_lock(self):
        src = inspect.getsource(SqliteKnowledgeGraph.close)
        assert "self._lock" in src, (
            "close() does not acquire self._lock. "
            "Closing while a read/write is in progress can corrupt data."
        )
