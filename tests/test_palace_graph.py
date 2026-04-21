"""
test_palace_graph.py — Tests for the palace graph traversal layer.

Covers: build_graph, traverse, find_tunnels, graph_stats, _fuzzy_match.

Each test uses an isolated ChromaDB collection seeded with known metadata
so assertions are deterministic. Clients are explicitly closed before
fixture teardown to avoid PermissionError on Windows.
"""

import pytest
import chromadb

from mempalace.palace_graph import (
    _fuzzy_match,
    build_graph,
    find_tunnels,
    graph_stats,
    traverse,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _seed(palace_path, drawers):
    """
    Create a ChromaDB collection seeded with *drawers*.

    Each drawer dict needs: id, wing, room. Optional: hall, document.
    Returns (client, collection) — caller must stop the client before cleanup.
    """
    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_or_create_collection("mempalace_drawers")
    col.add(
        ids=[d["id"] for d in drawers],
        documents=[d.get("document", "placeholder") for d in drawers],
        metadatas=[
            {
                "wing": d["wing"],
                "room": d["room"],
                "hall": d.get("hall", ""),
                "source_file": d.get("source_file", ""),
                "chunk_index": 0,
                "added_by": "test",
                "filed_at": "2026-01-01T00:00:00",
            }
            for d in drawers
        ],
    )
    return client, col


def _close_client(client):
    close = getattr(client, "close", None)
    if callable(close):
        close()
        return

    system = getattr(client, "_system", None)
    stop = getattr(system, "stop", None)
    if callable(stop):
        stop()


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def empty_col(palace_path):
    """Empty collection — no drawers at all."""
    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_or_create_collection("mempalace_drawers")
    yield col
    _close_client(client)


@pytest.fixture
def single_wing_col(palace_path):
    """
    Rooms spread across two wings with no overlap — no tunnel rooms.

      project / backend   (2 drawers, hall=facts)
      project / frontend  (1 drawer,  hall=events)
      notes   / planning  (1 drawer,  hall=advice)
    """
    client, col = _seed(
        palace_path,
        [
            {"id": "sw1", "wing": "project", "room": "backend", "hall": "facts"},
            {"id": "sw2", "wing": "project", "room": "backend", "hall": "facts"},
            {"id": "sw3", "wing": "project", "room": "frontend", "hall": "events"},
            {"id": "sw4", "wing": "notes", "room": "planning", "hall": "advice"},
        ],
    )
    yield col
    _close_client(client)


@pytest.fixture
def tunnel_col(palace_path):
    """
    'auth' appears in both 'project' and 'notes' wings — it is a tunnel room.

      project / auth      (hall=facts)
      notes   / auth      (hall=events)
      project / backend
      notes   / planning
    """
    client, col = _seed(
        palace_path,
        [
            {"id": "tc1", "wing": "project", "room": "auth", "hall": "facts"},
            {"id": "tc2", "wing": "notes", "room": "auth", "hall": "events"},
            {"id": "tc3", "wing": "project", "room": "backend"},
            {"id": "tc4", "wing": "notes", "room": "planning"},
        ],
    )
    yield col
    _close_client(client)


# ── build_graph ───────────────────────────────────────────────────────────────


class TestBuildGraph:
    def test_empty_collection_returns_empty(self, empty_col):
        nodes, edges = build_graph(col=empty_col)
        assert nodes == {}
        assert edges == []

    def test_nodes_contain_expected_rooms(self, single_wing_col):
        nodes, _ = build_graph(col=single_wing_col)
        assert "backend" in nodes
        assert "frontend" in nodes
        assert "planning" in nodes

    def test_node_tracks_wing(self, single_wing_col):
        nodes, _ = build_graph(col=single_wing_col)
        assert nodes["backend"]["wings"] == ["project"]
        assert nodes["planning"]["wings"] == ["notes"]

    def test_node_aggregates_drawer_count(self, single_wing_col):
        nodes, _ = build_graph(col=single_wing_col)
        assert nodes["backend"]["count"] == 2
        assert nodes["frontend"]["count"] == 1

    def test_no_edges_when_no_tunnel_rooms(self, single_wing_col):
        _, edges = build_graph(col=single_wing_col)
        assert edges == []

    def test_tunnel_room_appears_in_both_wings(self, tunnel_col):
        nodes, _ = build_graph(col=tunnel_col)
        assert "auth" in nodes
        assert set(nodes["auth"]["wings"]) == {"project", "notes"}

    def test_tunnel_room_creates_edges(self, tunnel_col):
        _, edges = build_graph(col=tunnel_col)
        assert len(edges) >= 1
        tunnel_edge = edges[0]
        assert tunnel_edge["room"] == "auth"
        assert set([tunnel_edge["wing_a"], tunnel_edge["wing_b"]]) == {"project", "notes"}

    def test_general_room_excluded(self, palace_path):
        client, col = _seed(
            palace_path,
            [
                {"id": "g1", "wing": "project", "room": "general"},
                {"id": "g2", "wing": "project", "room": "backend"},
            ],
        )
        try:
            nodes, _ = build_graph(col=col)
        finally:
            _close_client(client)
        assert "general" not in nodes
        assert "backend" in nodes

    def test_dates_empty_when_date_field_absent(self, palace_path):
        client, col = _seed(
            palace_path,
            [
                {"id": f"d{i}", "wing": "project", "room": "backend", "document": f"doc {i}"}
                for i in range(10)
            ],
        )
        # patch dates into metadata so build_graph sees them
        # (since _seed doesn't set date field, dates list should be empty — verify it is)
        try:
            nodes, _ = build_graph(col=col)
        finally:
            _close_client(client)
        assert nodes["backend"]["dates"] == []


# ── traverse ──────────────────────────────────────────────────────────────────


class TestTraverse:
    def test_missing_room_returns_error_dict(self, single_wing_col):
        result = traverse("nonexistent-room", col=single_wing_col)
        assert isinstance(result, dict)
        assert "error" in result
        assert "suggestions" in result

    def test_start_room_present_at_hop_zero(self, single_wing_col):
        result = traverse("backend", col=single_wing_col)
        assert isinstance(result, list)
        start = next((r for r in result if r["room"] == "backend"), None)
        assert start is not None
        assert start["hop"] == 0

    def test_same_wing_room_reached_at_hop_one(self, single_wing_col):
        result = traverse("backend", col=single_wing_col)
        hops = {r["room"]: r["hop"] for r in result}
        # frontend shares 'project' wing with backend
        assert "frontend" in hops
        assert hops["frontend"] == 1

    def test_different_wing_room_not_reachable(self, single_wing_col):
        # 'planning' is in 'notes' only — no overlap with 'project'
        result = traverse("backend", col=single_wing_col)
        rooms = {r["room"] for r in result}
        assert "planning" not in rooms

    def test_max_hops_zero_returns_only_start(self, single_wing_col):
        result = traverse("backend", col=single_wing_col, max_hops=0)
        assert len(result) == 1
        assert result[0]["room"] == "backend"
        assert result[0]["hop"] == 0

    def test_fuzzy_suggestions_on_near_miss(self, single_wing_col):
        # 'back' is a substring of 'backend'
        result = traverse("back", col=single_wing_col)
        assert "error" in result
        assert "backend" in result["suggestions"]

    def test_tunnel_allows_cross_wing_traversal(self, tunnel_col):
        # 'backend' (project) → 'auth' (project+notes) → 'planning' (notes)
        result = traverse("backend", col=tunnel_col, max_hops=2)
        rooms = {r["room"] for r in result}
        # auth is reachable at hop 1 via shared 'project' wing
        assert "auth" in rooms
        # planning is reachable at hop 2 via auth's 'notes' wing
        assert "planning" in rooms

    def test_results_sorted_by_hop_then_count(self, single_wing_col):
        result = traverse("backend", col=single_wing_col)
        hops = [r["hop"] for r in result]
        assert hops == sorted(hops)


# ── find_tunnels ──────────────────────────────────────────────────────────────


class TestFindTunnels:
    def test_no_tunnels_when_all_rooms_single_wing(self, single_wing_col):
        tunnels = find_tunnels(col=single_wing_col)
        assert tunnels == []

    def test_finds_cross_wing_room(self, tunnel_col):
        tunnels = find_tunnels(col=tunnel_col)
        rooms = [t["room"] for t in tunnels]
        assert "auth" in rooms

    def test_tunnel_entry_has_required_keys(self, tunnel_col):
        tunnels = find_tunnels(col=tunnel_col)
        entry = tunnels[0]
        assert "room" in entry
        assert "wings" in entry
        assert "recent" in entry
        assert "count" in entry

    def test_filter_by_wing_a(self, tunnel_col):
        tunnels = find_tunnels(wing_a="project", col=tunnel_col)
        assert all("project" in t["wings"] for t in tunnels)

    def test_filter_by_both_wings(self, tunnel_col):
        tunnels = find_tunnels(wing_a="project", wing_b="notes", col=tunnel_col)
        assert len(tunnels) >= 1
        assert tunnels[0]["room"] == "auth"

    def test_nonexistent_wing_filter_returns_empty(self, tunnel_col):
        tunnels = find_tunnels(wing_a="does-not-exist", col=tunnel_col)
        assert tunnels == []

    def test_empty_collection_returns_empty(self, empty_col):
        tunnels = find_tunnels(col=empty_col)
        assert tunnels == []


# ── graph_stats ───────────────────────────────────────────────────────────────


class TestGraphStats:
    def test_empty_collection_all_zeros(self, empty_col):
        stats = graph_stats(col=empty_col)
        assert stats["total_rooms"] == 0
        assert stats["tunnel_rooms"] == 0
        assert stats["total_edges"] == 0

    def test_counts_distinct_rooms(self, single_wing_col):
        stats = graph_stats(col=single_wing_col)
        assert stats["total_rooms"] == 3  # backend, frontend, planning

    def test_no_tunnel_rooms_in_single_wing_data(self, single_wing_col):
        stats = graph_stats(col=single_wing_col)
        assert stats["tunnel_rooms"] == 0

    def test_counts_tunnel_rooms(self, tunnel_col):
        stats = graph_stats(col=tunnel_col)
        assert stats["tunnel_rooms"] >= 1

    def test_rooms_per_wing_counts_rooms_not_drawers(self, single_wing_col):
        stats = graph_stats(col=single_wing_col)
        # 'project' wing has backend + frontend = 2 rooms
        assert stats["rooms_per_wing"]["project"] == 2
        # 'notes' wing has planning = 1 room
        assert stats["rooms_per_wing"]["notes"] == 1

    def test_stats_has_required_keys(self, single_wing_col):
        stats = graph_stats(col=single_wing_col)
        for key in ("total_rooms", "tunnel_rooms", "total_edges", "rooms_per_wing", "top_tunnels"):
            assert key in stats


# ── _fuzzy_match ──────────────────────────────────────────────────────────────

SAMPLE_NODES = {
    "chromadb-setup": {},
    "auth-flow": {},
    "backend-api": {},
    "riley-college-apps": {},
    "deployment-pipeline": {},
}


class TestFuzzyMatch:
    def test_exact_substring_returns_match(self):
        result = _fuzzy_match("auth", SAMPLE_NODES)
        assert "auth-flow" in result

    def test_full_room_name_matches(self):
        result = _fuzzy_match("auth-flow", SAMPLE_NODES)
        assert "auth-flow" in result

    def test_hyphen_split_word_matches(self):
        # "auth-zz" is not a direct substring of any room, but "auth" is in "auth-flow"
        result = _fuzzy_match("auth-zz", SAMPLE_NODES)
        assert "auth-flow" in result

    def test_no_match_returns_empty(self):
        result = _fuzzy_match("zzzzz", SAMPLE_NODES)
        assert result == []

    def test_respects_n_limit(self):
        # "a" is a substring of several rooms — cap at n=2
        result = _fuzzy_match("a", SAMPLE_NODES, n=2)
        assert len(result) <= 2

    def test_empty_nodes_returns_empty(self):
        result = _fuzzy_match("auth", {})
        assert result == []

    def test_default_returns_at_most_five(self):
        many_nodes = {f"room-{i}-auth": {} for i in range(20)}
        result = _fuzzy_match("auth", many_nodes)
        assert len(result) <= 5
