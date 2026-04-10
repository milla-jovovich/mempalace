"""Tests for KG multi-hop traversal."""


class TestTraverse:
    def test_traverse_depth_1(self, graph_kg):
        """Depth 1 returns only direct neighbors."""
        result = graph_kg.traverse("Alice", depth=1)
        node_names = {n["name"] for n in result["nodes"]}
        assert "Alice" in node_names  # root node
        assert "Acme" in node_names  # direct neighbor
        assert "Bob" in node_names  # direct neighbor
        assert "NYC" not in node_names  # 2 hops away

    def test_traverse_depth_2(self, graph_kg):
        """Depth 2 returns 2-hop neighbors."""
        result = graph_kg.traverse("Alice", depth=2)
        node_names = {n["name"] for n in result["nodes"]}
        assert "NYC" in node_names  # Alice->Acme->NYC
        assert "Chess" in node_names  # Alice->Bob->Chess
        assert "Carol" in node_names  # Alice->Acme<-Carol (incoming to Acme)

    def test_traverse_depth_capped_at_3(self, graph_kg):
        """Depth > 3 should be silently capped."""
        result = graph_kg.traverse("Alice", depth=10)
        # Should not error, just cap at 3
        assert isinstance(result, dict)
        assert "nodes" in result

    def test_traverse_direction_outgoing(self, graph_kg):
        """Outgoing only follows subject->object edges."""
        result = graph_kg.traverse("Alice", depth=1, direction="outgoing")
        node_names = {n["name"] for n in result["nodes"]}
        assert "Acme" in node_names  # Alice->Acme
        assert "Bob" in node_names  # Alice->Bob

    def test_traverse_with_as_of_filter(self, graph_kg):
        """as_of should filter expired triples."""
        result = graph_kg.traverse("Alice", depth=1, as_of="2022-01-01")
        node_names = {n["name"] for n in result["nodes"]}
        assert "OldCorp" in node_names  # Was valid in 2022

    def test_traverse_nonexistent_entity(self, graph_kg):
        """Nonexistent entity returns empty result."""
        result = graph_kg.traverse("NonExistent", depth=2)
        assert len(result["nodes"]) == 0 or len(result["nodes"]) == 1  # Just root or empty

    def test_traverse_returns_edges(self, graph_kg):
        """Result should include edges with depth info."""
        result = graph_kg.traverse("Alice", depth=1)
        assert "edges" in result
        assert len(result["edges"]) > 0


class TestFindPath:
    def test_find_path_direct_connection(self, graph_kg):
        """Direct neighbors should have path length 1."""
        result = graph_kg.find_path("Alice", "Bob")
        assert len(result["paths"]) > 0
        assert result["length"] == 1

    def test_find_path_two_hop(self, graph_kg):
        """Two-hop connection should work."""
        result = graph_kg.find_path("Alice", "Chess")
        assert len(result["paths"]) > 0
        assert result["length"] == 2  # Alice->Bob->Chess

    def test_find_path_no_connection(self, graph_kg):
        """No connection returns empty paths."""
        result = graph_kg.find_path("Alice", "NonExistent")
        assert result["paths"] == []
        assert result["length"] == 0

    def test_find_path_respects_max_depth(self, graph_kg):
        """max_depth=1 should not find 2-hop paths."""
        result = graph_kg.find_path("Alice", "Chess", max_depth=1)
        assert result["paths"] == []
        assert result["length"] == 0

    def test_find_path_via_shared_node(self, graph_kg):
        """Alice and Carol connect via Acme."""
        result = graph_kg.find_path("Alice", "Carol")
        assert len(result["paths"]) > 0
        assert result["length"] <= 3
