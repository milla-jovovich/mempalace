"""TDD: KnowledgeGraph.close() must hold self._lock."""

import inspect
from mempalace.knowledge_graph import KnowledgeGraph


class TestKGCloseLock:
    def test_close_holds_lock(self):
        src = inspect.getsource(KnowledgeGraph.close)
        assert "self._write_lock" in src, (
            "close() does not acquire self._write_lock. "
            "Closing while a read/write is in progress can corrupt data."
        )
