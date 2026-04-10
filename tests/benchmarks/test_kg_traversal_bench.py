"""Benchmark tests for KG traversal performance."""

import time

import pytest


@pytest.fixture(scope="module")
def large_kg(tmp_path_factory):
    """KG with 10K triples for performance testing."""
    from mempalace.knowledge_graph import KnowledgeGraph

    tmp_path = tmp_path_factory.mktemp("bench")
    kg = KnowledgeGraph(db_path=str(tmp_path / "bench.sqlite3"))
    # Create a graph with ~10K triples
    # 1000 entities, each connected to ~10 others
    for i in range(1000):
        for j in range(10):
            target = (i + j + 1) % 1000
            kg.add_triple(f"entity_{i}", f"rel_{j}", f"entity_{target}")
    return kg


@pytest.mark.benchmark
class TestTraversalPerformance:
    def test_traverse_10k_under_500ms(self, large_kg):
        start = time.perf_counter()
        result = large_kg.traverse("entity_0", depth=2)
        elapsed = time.perf_counter() - start
        assert elapsed < 0.5, f"traverse took {elapsed:.3f}s, expected <0.5s"
        assert len(result["nodes"]) > 0

    def test_find_path_10k_under_500ms(self, large_kg):
        start = time.perf_counter()
        large_kg.find_path("entity_0", "entity_500")
        elapsed = time.perf_counter() - start
        assert elapsed < 0.5, f"find_path took {elapsed:.3f}s, expected <0.5s"
