"""
crystallize.py — Intra-room PageRank for finding the most important notes.
"""

from typing import List, Tuple, Any
from mempalace.topology import calculate_pagerank


def find_room_diamonds(
    col: Any, room_name: str, top_k: int | float = 5
) -> Tuple[List[str], List[str]]:
    """
    Find the most important notes (diamonds) and the rest (noise) in a room using PageRank.
    """
    res = col.get(where={"room": room_name}, include=["documents", "metadatas"])
    ids = res.get("ids", [])
    docs = res.get("documents", [])

    if not ids:
        return [], []

    if isinstance(top_k, float) and 0.0 < top_k < 1.0:
        k = max(1, int(len(ids) * top_k))
    else:
        k = int(top_k)

    if len(ids) <= k:
        return ids, []

    n_res = min(4, len(ids))
    query_res = col.query(
        query_texts=docs,
        where={"room": room_name},
        n_results=n_res,
        include=["distances"],
    )

    match_ids_list = query_res.get("ids", [])
    distances_list = query_res.get("distances", [])

    edges = []
    for i, source_id in enumerate(ids):
        match_ids = match_ids_list[i]
        distances = distances_list[i]

        for match_id, dist in zip(match_ids, distances):
            if dist < 0.3 and match_id != source_id:
                edges.append((source_id, match_id))

    pr_scores = calculate_pagerank(ids, edges)

    sorted_ids = sorted(ids, key=lambda x: pr_scores.get(x, 0.0), reverse=True)

    diamonds = sorted_ids[:k]
    noise = sorted_ids[k:]

    return diamonds, noise
