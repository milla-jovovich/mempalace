"""
palace_graph.py — Graph traversal layer for MemPalace
======================================================

Builds a navigable graph from the palace structure:
  - Nodes = rooms (named ideas)
  - Edges = shared rooms across wings (tunnels)
  - Edge types = halls (the corridors)

Enables queries like:
  "Start at chromadb-setup in wing_code, walk to wing_myproject"
  "Find all rooms connected to riley-college-apps"
  "What topics bridge wing_hardware and wing_myproject?"

No external graph DB needed — built from ChromaDB metadata.
"""

import time
from collections import defaultdict, Counter
from .config import MempalaceConfig

# ---------------------------------------------------------------------------
# Graph cache — avoid rebuilding on every call
# ---------------------------------------------------------------------------
_graph_cache = {
    "nodes": None,
    "edges": None,
    "wing_to_rooms": None,
    "built_at": 0,
    "palace_path": None,
}
_CACHE_TTL = 60  # seconds


def _get_collection(config=None):
    config = config or MempalaceConfig()
    return config.get_collection()


def invalidate_graph_cache():
    """Call after adding/removing drawers to force a rebuild."""
    _graph_cache["built_at"] = 0


def build_graph(col=None, config=None):
    """
    Build the palace graph from ChromaDB metadata.

    Returns:
        nodes: dict of {room: {wings: set, halls: set, count: int}}
        edges: list of {room, wing_a, wing_b, hall} — one per tunnel crossing
        wing_to_rooms: dict of {wing: set(rooms)} — adjacency index for fast BFS
    """
    config = config or MempalaceConfig()
    palace_path = config.palace_path if config else None

    # Return cached graph if fresh
    now = time.monotonic()
    if (
        _graph_cache["nodes"] is not None
        and _graph_cache["palace_path"] == palace_path
        and now - _graph_cache["built_at"] < _CACHE_TTL
    ):
        return _graph_cache["nodes"], _graph_cache["edges"], _graph_cache["wing_to_rooms"]

    if col is None:
        col = _get_collection(config)
    if not col:
        return {}, [], {}

    total = col.count()
    room_data = defaultdict(lambda: {"wings": set(), "halls": set(), "count": 0, "dates": set()})

    offset = 0
    while offset < total:
        batch = col.get(limit=1000, offset=offset, include=["metadatas"])
        for meta in batch["metadatas"]:
            room = meta.get("room", "")
            wing = meta.get("wing", "")
            hall = meta.get("hall", "")
            date = meta.get("date", "")
            if room and room != "general" and wing:
                room_data[room]["wings"].add(wing)
                if hall:
                    room_data[room]["halls"].add(hall)
                if date:
                    room_data[room]["dates"].add(date)
                room_data[room]["count"] += 1
        if not batch["ids"]:
            break
        offset += len(batch["ids"])

    # Build edges from rooms that span multiple wings
    edges = []
    for room, data in room_data.items():
        wings = sorted(data["wings"])
        if len(wings) >= 2:
            for i, wa in enumerate(wings):
                for wb in wings[i + 1 :]:
                    for hall in data["halls"]:
                        edges.append(
                            {
                                "room": room,
                                "wing_a": wa,
                                "wing_b": wb,
                                "hall": hall,
                                "count": data["count"],
                            }
                        )

    # Build adjacency index: wing → set of rooms
    wing_to_rooms = defaultdict(set)
    for room, data in room_data.items():
        for wing in data["wings"]:
            wing_to_rooms[wing].add(room)

    # Convert sets to lists for JSON serialization
    nodes = {}
    for room, data in room_data.items():
        nodes[room] = {
            "wings": sorted(data["wings"]),
            "halls": sorted(data["halls"]),
            "count": data["count"],
            "dates": sorted(data["dates"])[-5:] if data["dates"] else [],
        }

    # Cache the result
    _graph_cache["nodes"] = nodes
    _graph_cache["edges"] = edges
    _graph_cache["wing_to_rooms"] = wing_to_rooms
    _graph_cache["built_at"] = now
    _graph_cache["palace_path"] = palace_path

    return nodes, edges, wing_to_rooms


def traverse(start_room: str, col=None, config=None, max_hops: int = 2):
    """
    Walk the graph from a starting room. Find connected rooms
    through shared wings.

    Returns list of paths: [{room, wing, hall, hop_distance}]
    """
    nodes, edges, wing_to_rooms = build_graph(col, config)

    if start_room not in nodes:
        return {
            "error": f"Room '{start_room}' not found",
            "suggestions": _fuzzy_match(start_room, nodes),
        }

    start = nodes[start_room]
    visited = {start_room}
    results = [
        {
            "room": start_room,
            "wings": start["wings"],
            "halls": start["halls"],
            "count": start["count"],
            "hop": 0,
        }
    ]

    # BFS traversal using adjacency index — O(V+E) instead of O(V²)
    frontier = [(start_room, 0)]
    while frontier:
        current_room, depth = frontier.pop(0)
        if depth >= max_hops:
            continue

        current = nodes.get(current_room, {})
        current_wings = current.get("wings", [])

        # Use adjacency index: for each wing the current room belongs to,
        # find all other rooms in that wing — O(degree) per frontier node
        for wing in current_wings:
            for room in wing_to_rooms.get(wing, set()):
                if room in visited:
                    continue
                data = nodes[room]
                shared_wings = set(current_wings) & set(data["wings"])
                visited.add(room)
                results.append(
                    {
                        "room": room,
                        "wings": data["wings"],
                        "halls": data["halls"],
                        "count": data["count"],
                        "hop": depth + 1,
                        "connected_via": sorted(shared_wings),
                    }
                )
                if depth + 1 < max_hops:
                    frontier.append((room, depth + 1))

    # Sort by relevance (hop distance, then count)
    results.sort(key=lambda x: (x["hop"], -x["count"]))
    return results[:50]  # cap results


def find_tunnels(wing_a: str = None, wing_b: str = None, col=None, config=None):
    """
    Find rooms that connect two wings (or all tunnel rooms if no wings specified).
    These are the "hallways" — same named idea appearing in multiple domains.
    """
    nodes, edges, wing_to_rooms = build_graph(col, config)

    tunnels = []
    for room, data in nodes.items():
        wings = data["wings"]
        if len(wings) < 2:
            continue

        if wing_a and wing_a not in wings:
            continue
        if wing_b and wing_b not in wings:
            continue

        tunnels.append(
            {
                "room": room,
                "wings": wings,
                "halls": data["halls"],
                "count": data["count"],
                "recent": data["dates"][-1] if data["dates"] else "",
            }
        )

    tunnels.sort(key=lambda x: -x["count"])
    return tunnels[:50]


def graph_stats(col=None, config=None):
    """Summary statistics about the palace graph."""
    nodes, edges, wing_to_rooms = build_graph(col, config)

    tunnel_rooms = sum(1 for n in nodes.values() if len(n["wings"]) >= 2)
    wing_counts = Counter()
    for data in nodes.values():
        for w in data["wings"]:
            wing_counts[w] += 1

    return {
        "total_rooms": len(nodes),
        "tunnel_rooms": tunnel_rooms,
        "total_edges": len(edges),
        "rooms_per_wing": dict(wing_counts.most_common()),
        "top_tunnels": [
            {"room": r, "wings": d["wings"], "count": d["count"]}
            for r, d in sorted(nodes.items(), key=lambda x: -len(x[1]["wings"]))[:10]
            if len(d["wings"]) >= 2
        ],
    }


def _fuzzy_match(query: str, nodes: dict, n: int = 5):
    """Find rooms that approximately match a query string."""
    query_lower = query.lower()
    scored = []
    for room in nodes:
        # Simple substring matching
        if query_lower in room:
            scored.append((room, 1.0))
        elif any(word in room for word in query_lower.split("-")):
            scored.append((room, 0.5))
    scored.sort(key=lambda x: -x[1])
    return [r for r, _ in scored[:n]]
