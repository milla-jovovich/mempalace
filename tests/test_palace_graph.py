"""
Tests for palace_graph.py — Graph traversal layer for MemPalace.

Covers:
  - Graph building from ChromaDB metadata (nodes, edges, tunnels)
  - Room filtering (skips 'general' rooms and entries without wing)
  - BFS traversal with hop limits and shared-wing connections
  - Tunnel discovery across wings with optional wing filtering
  - Graph statistics computation
  - Fuzzy room name matching for error suggestions

All tests use a real ChromaDB collection in a temp directory
to avoid mocking internal ChromaDB APIs.
"""

import os
import tempfile
import shutil

import chromadb

from mempalace.palace_graph import build_graph, traverse, find_tunnels, graph_stats, _fuzzy_match


def _make_collection(entries):
    """Create a ChromaDB collection populated with test metadata.

    Args:
        entries: list of dicts with keys: id, wing, room, hall, date, doc.

    Returns:
        (collection, tmpdir) — collection is ready for graph functions.
    """
    tmpdir = tempfile.mkdtemp()
    client = chromadb.PersistentClient(path=os.path.join(tmpdir, "palace"))
    col = client.get_or_create_collection("mempalace_drawers")

    if entries:
        col.add(
            ids=[e["id"] for e in entries],
            documents=[e.get("doc", "test content") for e in entries],
            metadatas=[
                {
                    "wing": e.get("wing", ""),
                    "room": e.get("room", ""),
                    "hall": e.get("hall", ""),
                    "date": e.get("date", ""),
                }
                for e in entries
            ],
        )

    return col, tmpdir


# ── build_graph ───────────────────────────────────────────────────────


def test_build_graph_basic():
    """Single wing with multiple rooms creates nodes without tunnel edges."""
    col, tmpdir = _make_collection(
        [
            {"id": "d1", "wing": "wing_project", "room": "auth", "hall": "hall_facts"},
            {"id": "d2", "wing": "wing_project", "room": "billing", "hall": "hall_events"},
            {"id": "d3", "wing": "wing_project", "room": "auth", "hall": "hall_facts"},
        ]
    )
    try:
        nodes, edges = build_graph(col=col)

        assert "auth" in nodes
        assert "billing" in nodes
        assert nodes["auth"]["count"] == 2
        assert nodes["billing"]["count"] == 1
        # No tunnels — all rooms in same wing
        assert len(edges) == 0
    finally:
        shutil.rmtree(tmpdir)


def test_build_graph_tunnels():
    """Same room name in different wings creates tunnel edges."""
    col, tmpdir = _make_collection(
        [
            {"id": "d1", "wing": "wing_kai", "room": "auth-migration", "hall": "hall_facts"},
            {"id": "d2", "wing": "wing_driftwood", "room": "auth-migration", "hall": "hall_facts"},
        ]
    )
    try:
        nodes, edges = build_graph(col=col)

        assert "auth-migration" in nodes
        assert len(nodes["auth-migration"]["wings"]) == 2
        assert len(edges) >= 1
        assert edges[0]["room"] == "auth-migration"
    finally:
        shutil.rmtree(tmpdir)


def test_build_graph_skips_general_room():
    """Rooms named 'general' are excluded from the graph."""
    col, tmpdir = _make_collection(
        [
            {"id": "d1", "wing": "wing_project", "room": "general", "hall": "hall_facts"},
            {"id": "d2", "wing": "wing_project", "room": "auth", "hall": "hall_facts"},
        ]
    )
    try:
        nodes, edges = build_graph(col=col)

        assert "general" not in nodes
        assert "auth" in nodes
    finally:
        shutil.rmtree(tmpdir)


def test_build_graph_skips_entries_without_wing():
    """Entries without a wing value are excluded from the graph."""
    col, tmpdir = _make_collection(
        [
            {"id": "d1", "wing": "", "room": "orphan-room", "hall": "hall_facts"},
            {"id": "d2", "wing": "wing_project", "room": "auth", "hall": "hall_facts"},
        ]
    )
    try:
        nodes, edges = build_graph(col=col)

        assert "orphan-room" not in nodes
        assert "auth" in nodes
    finally:
        shutil.rmtree(tmpdir)


def test_build_graph_empty_collection():
    """Empty collection returns empty nodes and edges."""
    col, tmpdir = _make_collection([])
    try:
        nodes, edges = build_graph(col=col)

        assert nodes == {}
        assert edges == []
    finally:
        shutil.rmtree(tmpdir)


def test_build_graph_tracks_halls():
    """Nodes record which halls they appear in."""
    col, tmpdir = _make_collection(
        [
            {"id": "d1", "wing": "wing_a", "room": "auth", "hall": "hall_facts"},
            {"id": "d2", "wing": "wing_a", "room": "auth", "hall": "hall_events"},
        ]
    )
    try:
        nodes, edges = build_graph(col=col)

        assert "hall_facts" in nodes["auth"]["halls"]
        assert "hall_events" in nodes["auth"]["halls"]
    finally:
        shutil.rmtree(tmpdir)


# ── traverse ──────────────────────────────────────────────────────────


def test_traverse_finds_connected_rooms():
    """Traversal from a room finds other rooms in the same wing."""
    col, tmpdir = _make_collection(
        [
            {"id": "d1", "wing": "wing_project", "room": "auth", "hall": "hall_facts"},
            {"id": "d2", "wing": "wing_project", "room": "billing", "hall": "hall_facts"},
            {"id": "d3", "wing": "wing_other", "room": "unrelated", "hall": "hall_facts"},
        ]
    )
    try:
        results = traverse("auth", col=col)

        room_names = {r["room"] for r in results}
        assert "auth" in room_names  # start room at hop 0
        assert "billing" in room_names  # same wing, hop 1
        assert "unrelated" not in room_names  # different wing
    finally:
        shutil.rmtree(tmpdir)


def test_traverse_respects_max_hops():
    """Traversal stops at max_hops depth."""
    col, tmpdir = _make_collection(
        [
            {"id": "d1", "wing": "wing_a", "room": "room-start", "hall": "hall_facts"},
            {"id": "d2", "wing": "wing_a", "room": "room-mid", "hall": "hall_facts"},
            {"id": "d3", "wing": "wing_a", "room": "room-far", "hall": "hall_facts"},
        ]
    )
    try:
        results = traverse("room-start", col=col, max_hops=1)

        hops = {r["hop"] for r in results}
        assert max(hops) <= 1
    finally:
        shutil.rmtree(tmpdir)


def test_traverse_nonexistent_room():
    """Traversal from a nonexistent room returns error with suggestions."""
    col, tmpdir = _make_collection(
        [
            {"id": "d1", "wing": "wing_a", "room": "auth-migration", "hall": "hall_facts"},
        ]
    )
    try:
        result = traverse("auth-migr", col=col)

        assert isinstance(result, dict)
        assert "error" in result
        assert "suggestions" in result
    finally:
        shutil.rmtree(tmpdir)


def test_traverse_start_room_at_hop_zero():
    """The starting room always appears at hop 0 in traversal results."""
    col, tmpdir = _make_collection(
        [
            {"id": "d1", "wing": "wing_a", "room": "auth", "hall": "hall_facts"},
            {"id": "d2", "wing": "wing_a", "room": "billing", "hall": "hall_facts"},
        ]
    )
    try:
        results = traverse("auth", col=col)

        start_entry = [r for r in results if r["room"] == "auth"]
        assert len(start_entry) == 1
        assert start_entry[0]["hop"] == 0
    finally:
        shutil.rmtree(tmpdir)


# ── find_tunnels ──────────────────────────────────────────────────────


def test_find_tunnels_returns_multi_wing_rooms():
    """find_tunnels returns rooms that span multiple wings."""
    col, tmpdir = _make_collection(
        [
            {"id": "d1", "wing": "wing_kai", "room": "auth", "hall": "hall_facts"},
            {"id": "d2", "wing": "wing_maya", "room": "auth", "hall": "hall_facts"},
            {"id": "d3", "wing": "wing_kai", "room": "billing", "hall": "hall_events"},
        ]
    )
    try:
        tunnels = find_tunnels(col=col)

        tunnel_rooms = {t["room"] for t in tunnels}
        assert "auth" in tunnel_rooms
        assert "billing" not in tunnel_rooms  # only in one wing
    finally:
        shutil.rmtree(tmpdir)


def test_find_tunnels_with_wing_filter():
    """find_tunnels can filter by specific wings."""
    col, tmpdir = _make_collection(
        [
            {"id": "d1", "wing": "wing_kai", "room": "auth", "hall": "hall_facts"},
            {"id": "d2", "wing": "wing_maya", "room": "auth", "hall": "hall_facts"},
            {"id": "d3", "wing": "wing_kai", "room": "deploy", "hall": "hall_facts"},
            {"id": "d4", "wing": "wing_leo", "room": "deploy", "hall": "hall_facts"},
        ]
    )
    try:
        tunnels = find_tunnels(wing_a="wing_kai", wing_b="wing_maya", col=col)

        tunnel_rooms = {t["room"] for t in tunnels}
        assert "auth" in tunnel_rooms
        # deploy bridges kai<->leo, not kai<->maya
        assert "deploy" not in tunnel_rooms
    finally:
        shutil.rmtree(tmpdir)


# ── graph_stats ───────────────────────────────────────────────────────


def test_graph_stats_counts():
    """graph_stats returns correct room, tunnel, and edge counts."""
    col, tmpdir = _make_collection(
        [
            {"id": "d1", "wing": "wing_a", "room": "room1", "hall": "hall_facts"},
            {"id": "d2", "wing": "wing_a", "room": "room2", "hall": "hall_facts"},
            {"id": "d3", "wing": "wing_b", "room": "room1", "hall": "hall_facts"},
        ]
    )
    try:
        stats = graph_stats(col=col)

        assert stats["total_rooms"] == 2  # room1, room2
        assert stats["tunnel_rooms"] == 1  # room1 spans both wings
        assert stats["total_edges"] >= 1
        assert "wing_a" in stats["rooms_per_wing"]
    finally:
        shutil.rmtree(tmpdir)


# ── _fuzzy_match ──────────────────────────────────────────────────────


def test_fuzzy_match_exact_substring():
    """Exact substring match returns score 1.0 (highest)."""
    nodes = {"auth-migration": {}, "billing-setup": {}, "ci-pipeline": {}}
    results = _fuzzy_match("auth-migration", nodes)
    assert results[0] == "auth-migration"


def test_fuzzy_match_partial():
    """Partial word match (from hyphen-split) returns results."""
    nodes = {"auth-migration": {}, "billing-setup": {}, "auth-tokens": {}}
    results = _fuzzy_match("auth", nodes)
    # Both auth-containing rooms should appear
    assert len(results) >= 2
    assert all("auth" in r for r in results)


def test_fuzzy_match_no_match():
    """No matching rooms returns empty list."""
    nodes = {"auth-migration": {}, "billing-setup": {}}
    results = _fuzzy_match("kubernetes", nodes)
    assert results == []
