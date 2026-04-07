import chromadb
from mempalace.palace_graph import build_graph, traverse, find_tunnels, graph_stats, _fuzzy_match


def _make_collection(palace_path, ids, documents, metadatas):
    """Create a ChromaDB collection with test data."""
    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_or_create_collection("mempalace_drawers")
    col.add(ids=ids, documents=documents, metadatas=metadatas)
    return col


def test_build_graph_creates_nodes(populated_palace):
    palace_path, col = populated_palace
    nodes, edges = build_graph(col=col)
    assert "hobbies" in nodes
    assert "backend" in nodes
    assert "decisions" in nodes
    assert "sports" in nodes


def test_build_graph_skips_general(palace_path):
    col = _make_collection(
        palace_path,
        ids=["g1"],
        documents=["generic content"],
        metadatas=[{"wing": "misc", "room": "general", "hall": ""}],
    )
    nodes, edges = build_graph(col=col)
    assert "general" not in nodes


def test_build_graph_detects_tunnels(palace_path):
    col = _make_collection(
        palace_path,
        ids=["t1", "t2"],
        documents=["content a", "content b"],
        metadatas=[
            {"wing": "wing_a", "room": "shared-topic", "hall": "hall_facts"},
            {"wing": "wing_b", "room": "shared-topic", "hall": "hall_facts"},
        ],
    )
    nodes, edges = build_graph(col=col)
    assert len(edges) >= 1
    assert edges[0]["room"] == "shared-topic"


def test_traverse_unknown_room(populated_palace):
    palace_path, col = populated_palace
    result = traverse("nonexistent-room", col=col)
    assert isinstance(result, dict)
    assert "error" in result


def test_traverse_hop_distance(palace_path):
    col = _make_collection(
        palace_path,
        ids=["a1", "a2", "b1"],
        documents=["x", "y", "z"],
        metadatas=[
            {"wing": "w1", "room": "start", "hall": "h"},
            {"wing": "w1", "room": "neighbor", "hall": "h"},
            {"wing": "w2", "room": "neighbor", "hall": "h"},
        ],
    )
    results = traverse("start", col=col, max_hops=1)
    rooms = {r["room"] for r in results}
    assert "start" in rooms
    assert "neighbor" in rooms


def test_find_tunnels_filters_by_wing(palace_path):
    col = _make_collection(
        palace_path,
        ids=["f1", "f2", "f3"],
        documents=["a", "b", "c"],
        metadatas=[
            {"wing": "alpha", "room": "bridge", "hall": "h"},
            {"wing": "beta", "room": "bridge", "hall": "h"},
            {"wing": "gamma", "room": "other-bridge", "hall": "h"},
        ],
    )
    tunnels = find_tunnels(wing_a="alpha", col=col)
    rooms = [t["room"] for t in tunnels]
    assert "bridge" in rooms


def test_graph_stats(populated_palace):
    palace_path, col = populated_palace
    stats = graph_stats(col=col)
    assert "total_rooms" in stats
    assert "tunnel_rooms" in stats
    assert stats["total_rooms"] >= 1


def test_fuzzy_match():
    nodes = {"chromadb-setup": {}, "riley-school": {}, "gpu-pricing": {}}
    assert "chromadb-setup" in _fuzzy_match("chromadb", nodes)
    assert "riley-school" in _fuzzy_match("riley", nodes)
    assert _fuzzy_match("nonexistent", nodes) == []
