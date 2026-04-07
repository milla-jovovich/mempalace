"""Tests for mempalace.palace_graph — graph traversal and tunnels."""

import os

import chromadb
import pytest

from mempalace.palace_graph import (
    _fuzzy_match,
    build_graph,
    find_tunnels,
    graph_stats,
    traverse,
)


@pytest.fixture()
def graph_palace(tmp_path):
    """Palace with cross-wing room data for graph tests."""
    path = str(tmp_path / "graph_palace")
    os.makedirs(path, exist_ok=True)
    client = chromadb.PersistentClient(path=path)
    col = client.get_or_create_collection("mempalace_drawers")
    col.add(
        documents=[
            "Auth logic for app",
            "Auth logic for backend",
            "UI components",
            "Database schema",
            "Shared auth library",
        ],
        ids=["d1", "d2", "d3", "d4", "d5"],
        metadatas=[
            {"wing": "frontend", "room": "auth", "date": "2026-01-01"},
            {"wing": "backend", "room": "auth", "date": "2026-01-15"},
            {"wing": "frontend", "room": "components", "date": "2026-02-01"},
            {"wing": "backend", "room": "database", "date": "2026-02-15"},
            {"wing": "shared", "room": "auth", "date": "2026-03-01"},
        ],
    )
    return col


class TestBuildGraph:
    @pytest.mark.integration
    def test_builds_nodes_and_edges(self, graph_palace):
        nodes, edges = build_graph(col=graph_palace)
        assert "auth" in nodes
        assert nodes["auth"]["count"] >= 3
        assert len(nodes["auth"]["wings"]) >= 2

    @pytest.mark.integration
    def test_edges_for_shared_rooms(self, graph_palace):
        nodes, edges = build_graph(col=graph_palace)
        auth_edges = [e for e in edges if e["room"] == "auth"]
        assert len(auth_edges) >= 1

    @pytest.mark.integration
    def test_excludes_general_rooms(self, graph_palace):
        nodes, _ = build_graph(col=graph_palace)
        assert "general" not in nodes

    def test_empty_collection(self, tmp_path):
        path = str(tmp_path / "empty_palace")
        os.makedirs(path, exist_ok=True)
        client = chromadb.PersistentClient(path=path)
        col = client.get_or_create_collection("mempalace_drawers")
        nodes, edges = build_graph(col=col)
        assert nodes == {}
        assert edges == []


class TestTraverse:
    @pytest.mark.integration
    def test_traverses_from_auth(self, graph_palace):
        results = traverse("auth", col=graph_palace)
        assert isinstance(results, list)
        rooms = [r["room"] for r in results]
        assert "auth" in rooms

    @pytest.mark.integration
    def test_unknown_room_returns_error(self, graph_palace):
        result = traverse("nonexistent_room_xyz", col=graph_palace)
        assert isinstance(result, dict)
        assert "error" in result

    @pytest.mark.integration
    def test_max_hops(self, graph_palace):
        results = traverse("auth", col=graph_palace, max_hops=1)
        assert all(r["hop"] <= 1 for r in results)


class TestFindTunnels:
    @pytest.mark.integration
    def test_finds_cross_wing_rooms(self, graph_palace):
        tunnels = find_tunnels(col=graph_palace)
        assert len(tunnels) >= 1
        assert tunnels[0]["room"] == "auth"

    @pytest.mark.integration
    def test_filter_by_wings(self, graph_palace):
        tunnels = find_tunnels(wing_a="frontend", wing_b="backend", col=graph_palace)
        for t in tunnels:
            assert "frontend" in t["wings"]
            assert "backend" in t["wings"]


class TestGraphStats:
    @pytest.mark.integration
    def test_returns_stats(self, graph_palace):
        stats = graph_stats(col=graph_palace)
        assert stats["total_rooms"] >= 1
        assert stats["tunnel_rooms"] >= 1
        assert "rooms_per_wing" in stats


class TestFuzzyMatch:
    def test_substring_match(self):
        nodes = {"authentication": {}, "database": {}, "auth-service": {}}
        matches = _fuzzy_match("auth", nodes)
        assert "authentication" in matches
        assert "auth-service" in matches

    def test_no_match(self):
        nodes = {"database": {}, "frontend": {}}
        assert _fuzzy_match("zzz", nodes) == []
