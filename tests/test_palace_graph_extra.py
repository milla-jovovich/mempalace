"""Additional graph tests that hit defensive collection-loading branches."""

from unittest.mock import MagicMock, patch

from mempalace.palace_graph import _get_collection, build_graph, find_tunnels


def test_get_collection_returns_none_when_backend_raises():
    with patch("mempalace.palace_graph._get_palace_collection", side_effect=RuntimeError("boom")):
        assert _get_collection() is None


def test_build_graph_breaks_cleanly_when_batch_ids_are_empty():
    col = MagicMock()
    col.count.return_value = 5
    col.get.return_value = {"ids": [], "metadatas": []}

    nodes, edges = build_graph(col=col)

    assert nodes == {}
    assert edges == []


def test_find_tunnels_respects_second_wing_filter():
    col = MagicMock()
    col.count.return_value = 2
    col.get.side_effect = lambda limit=1000, offset=0, include=None: {
        "ids": ["a", "b"][offset : offset + limit],
        "metadatas": [
            {"room": "shared", "wing": "wing_code", "hall": "hall_bridge", "date": "2026-01-01"},
            {
                "room": "shared",
                "wing": "wing_project",
                "hall": "hall_bridge",
                "date": "2026-01-02",
            },
        ][offset : offset + limit],
    }

    tunnels = find_tunnels(wing_a="wing_code", wing_b="wing_ops", col=col)

    assert tunnels == []
