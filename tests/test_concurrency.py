"""Concurrency tests — verify thread safety of core operations.

These tests exercise concurrent access to shared state:
  - search_memories with parallel readers
  - MCP tool dispatch under contention
  - KnowledgeGraph concurrent writes (unit level)
"""

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import MagicMock, patch

import chromadb
import pytest

from mempalace.knowledge_graph import KnowledgeGraph
from mempalace.searcher import search_memories


# ── Concurrent Search ──────────────────────────────────────────────────


class TestConcurrentSearch:
    """Multiple threads issuing search_memories simultaneously."""

    @pytest.fixture
    def populated_palace(self, tmp_path):
        palace_path = str(tmp_path / "palace")
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_or_create_collection("mempalace_drawers")
        docs = [f"Document about topic {i} with enough content to be meaningful." for i in range(50)]
        col.add(
            ids=[f"d_{i}" for i in range(50)],
            documents=docs,
            metadatas=[{"wing": "test", "room": "room", "source_file": f"f{i}.py", "chunk_index": 0} for i in range(50)],
        )
        del client
        return palace_path

    def test_parallel_reads_no_errors(self, populated_palace):
        """4 concurrent readers should all succeed without errors."""
        errors = []

        def search_task(query):
            result = search_memories(query, palace_path=populated_palace, n_results=5)
            if "error" in result:
                errors.append(result["error"])
            return result

        queries = ["topic 1", "topic 10", "topic 20", "topic 30"] * 3
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(search_task, q) for q in queries]
            results = [f.result() for f in as_completed(futures)]

        assert len(errors) == 0, f"Concurrent search errors: {errors}"
        assert all("results" in r for r in results)

    def test_parallel_reads_return_valid_data(self, populated_palace):
        """Results from concurrent searches should have consistent structure."""
        def search_task(query):
            return search_memories(query, palace_path=populated_palace, n_results=3)

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(search_task, f"topic {i}") for i in range(8)]
            results = [f.result() for f in as_completed(futures)]

        for result in results:
            assert "results" in result
            for hit in result["results"]:
                assert "text" in hit
                assert "similarity" in hit


# ── Concurrent KnowledgeGraph writes ───────────────────────────────────


class TestConcurrentKGWrites:
    """Verify KnowledgeGraph handles concurrent entity/relation adds safely."""

    def test_concurrent_add_entity(self, tmp_path):
        """Multiple threads adding entities should not corrupt the DB."""
        kg = KnowledgeGraph(db_path=str(tmp_path / "kg.sqlite3"))
        errors = []
        n_threads = 4
        entities_per_thread = 20

        def add_entities(thread_id):
            for i in range(entities_per_thread):
                try:
                    kg.add_entity(f"entity_t{thread_id}_{i}", entity_type="test")
                except Exception as e:
                    errors.append(str(e))

        threads = [
            threading.Thread(target=add_entities, args=(t,))
            for t in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Some may fail due to locking, but no corruption
        assert len(errors) < n_threads * entities_per_thread, "All writes failed"
        # At least some entities should exist
        stats = kg.stats()
        assert stats["entities"] > 0

    def test_concurrent_add_relation(self, tmp_path):
        """Multiple threads adding relations should not corrupt the DB."""
        kg = KnowledgeGraph(db_path=str(tmp_path / "kg.sqlite3"))
        # Pre-create entities
        for i in range(10):
            kg.add_entity(f"person_{i}", entity_type="person")

        errors = []

        def add_relations(thread_id):
            for i in range(10):
                try:
                    kg.add_triple(
                        f"person_{thread_id}",
                        "knows",
                        f"person_{(thread_id + i + 1) % 10}",
                    )
                except Exception as e:
                    errors.append(str(e))

        threads = [
            threading.Thread(target=add_relations, args=(t,))
            for t in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # DB should still be queryable
        stats = kg.stats()
        assert stats["entities"] == 10
        assert stats["triples"] > 0

    def test_concurrent_read_write(self, tmp_path):
        """Readers and writers at the same time should not deadlock."""
        kg = KnowledgeGraph(db_path=str(tmp_path / "kg.sqlite3"))
        for i in range(5):
            kg.add_entity(f"base_{i}", entity_type="test")

        read_results = []
        write_errors = []

        def writer():
            for i in range(10):
                try:
                    kg.add_entity(f"new_{i}", entity_type="test")
                except Exception as e:
                    write_errors.append(str(e))

        def reader():
            for _ in range(10):
                try:
                    stats = kg.stats()
                    read_results.append(stats["entities"])
                except Exception:
                    read_results.append(-1)

        t_write = threading.Thread(target=writer)
        t_read = threading.Thread(target=reader)
        t_write.start()
        t_read.start()
        t_write.join()
        t_read.join()

        assert len(read_results) == 10
        # All reads should return a valid positive count (no corruption)
        assert all(r > 0 for r in read_results), f"Some reads failed: {read_results}"


# ── Concurrent MCP tool calls ─────────────────────────────────────────


class TestConcurrentMCPCalls:
    """Simulate parallel MCP tool invocations."""

    def test_concurrent_status_calls(self, monkeypatch, tmp_path):
        """Multiple concurrent tool_status calls should not crash."""
        palace_path = str(tmp_path / "palace")
        client = chromadb.PersistentClient(path=palace_path)
        client.get_or_create_collection("mempalace_drawers")
        del client

        from mempalace.config import MempalaceConfig
        from mempalace.knowledge_graph import KnowledgeGraph
        import mempalace.mcp_server as mcp_mod

        cfg = MempalaceConfig(config_dir=str(tmp_path / "cfg"))
        monkeypatch.setattr(cfg, "_file_config", {"palace_path": palace_path})
        monkeypatch.setattr(mcp_mod, "_config", cfg)
        monkeypatch.setattr(mcp_mod, "_kg", KnowledgeGraph(db_path=str(tmp_path / "kg.sqlite3")))

        from mempalace.mcp_server import tool_status

        errors = []

        def call_status():
            try:
                result = tool_status()
                assert "total_drawers" in result
            except Exception as e:
                errors.append(str(e))

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(call_status) for _ in range(12)]
            for f in as_completed(futures):
                f.result()

        assert len(errors) == 0, f"Concurrent tool_status errors: {errors}"
