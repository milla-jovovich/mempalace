#!/usr/bin/env python3
"""
searcher.py — Find anything. Exact words.

Semantic search against the palace.
Returns verbatim text — the actual words, never summaries.
"""

import logging
from pathlib import Path

from .palace import get_collection

logger = logging.getLogger("mempalace_mcp")


class SearchError(Exception):
    """Raised when search cannot proceed (e.g. no palace found)."""


def build_where_filter(wing: str = None, room: str = None, where: dict = None) -> dict:
    """Build ChromaDB where filter for wing/room filtering.

    Args:
        wing: Optional wing filter.
        room: Optional room filter.
        where: Optional additional ChromaDB where conditions to merge.
            Supports any ChromaDB where operators ($eq, $ne, $gt, $gte,
            $lt, $lte, $in, $nin, $and, $or). These are combined with
            wing/room filters via $and.
    """
    conditions = []
    if wing:
        conditions.append({"wing": wing})
    if room:
        conditions.append({"room": room})
    if where:
        conditions.append(where)

    if len(conditions) == 0:
        return {}
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def search(query: str, palace_path: str, wing: str = None, room: str = None,
           n_results: int = 5, where: dict = None, sort_by: str = "relevance"):
    """
    Search the palace. Returns verbatim drawer content.
    Optionally filter by wing (project), room (aspect), or metadata conditions.

    Args:
        sort_by: "relevance" (default, similarity ranking) or "recency" (filed_at descending).
    """
    try:
        col = get_collection(palace_path, create=False)
    except Exception:
        print(f"\n  No palace found at {palace_path}")
        print("  Run: mempalace init <dir> then mempalace mine <dir>")
        raise SearchError(f"No palace found at {palace_path}")

    where_filter = build_where_filter(wing, room, where)

    try:
        kwargs = {
            "query_texts": [query],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        if where_filter:
            kwargs["where"] = where_filter

        results = col.query(**kwargs)

    except Exception as e:
        print(f"\n  Search error: {e}")
        raise SearchError(f"Search error: {e}") from e

    docs = results["documents"][0]
    metas = results["metadatas"][0]
    dists = results["distances"][0]

    if not docs:
        print(f'\n  No results found for: "{query}"')
        return

    # Sort by recency if requested (ChromaDB returns by similarity by default)
    items = list(zip(docs, metas, dists))
    if sort_by == "recency":
        items.sort(key=lambda x: x[1].get("filed_at", ""), reverse=True)

    print(f"\n{'=' * 60}")
    print(f'  Results for: "{query}"')
    if wing:
        print(f"  Wing: {wing}")
    if room:
        print(f"  Room: {room}")
    print(f"{'=' * 60}\n")

    for i, (doc, meta, dist) in enumerate(items, 1):
        similarity = round(max(0.0, 1 - dist), 3)
        source = Path(meta.get("source_file", "?")).name
        wing_name = meta.get("wing", "?")
        room_name = meta.get("room", "?")

        print(f"  [{i}] {wing_name} / {room_name}")
        print(f"      Source: {source}")
        print(f"      Match:  {similarity}")
        if sort_by == "recency":
            print(f"      Filed:  {meta.get('filed_at', '?')}")
        print()
        # Print the verbatim text, indented
        for line in doc.strip().split("\n"):
            print(f"      {line}")
        print()
        print(f"  {'─' * 56}")

    print()


def search_memories(
    query: str,
    palace_path: str,
    wing: str = None,
    room: str = None,
    n_results: int = 5,
    max_distance: float = 0.0,
    where: dict = None,
    sort_by: str = "relevance",
) -> dict:
    """Programmatic search — returns a dict instead of printing.

    Used by the MCP server and other callers that need data.

    Args:
        query: Natural language search query.
        palace_path: Path to the ChromaDB palace directory.
        wing: Optional wing filter.
        room: Optional room filter.
        n_results: Max results to return.
        max_distance: Max cosine distance threshold. The palace collection uses
            cosine distance (hnsw:space=cosine) — 0 = identical, 2 = opposite.
            Results with distance > this value are filtered out. A value of
            0.0 disables filtering. Typical useful range: 0.3–1.0.
        where: Optional additional ChromaDB where conditions for metadata
            filtering. Supports any ChromaDB where operators ($eq, $gt,
            $gte, $lt, $lte, $in, $nin). These are combined with wing/room
            filters via $and.
        sort_by: "relevance" (default, similarity ranking) or "recency"
            (filed_at descending). Recency sorting happens after ChromaDB
            returns similarity-ranked results.
    """
    try:
        col = get_collection(palace_path, create=False)
    except Exception as e:
        logger.error("No palace found at %s: %s", palace_path, e)
        return {
            "error": "No palace found",
            "hint": "Run: mempalace init <dir> && mempalace mine <dir>",
        }

    where_filter = build_where_filter(wing, room, where)

    try:
        kwargs = {
            "query_texts": [query],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        if where_filter:
            kwargs["where"] = where_filter

        results = col.query(**kwargs)
    except Exception as e:
        return {"error": f"Search error: {e}"}

    docs = results["documents"][0]
    metas = results["metadatas"][0]
    dists = results["distances"][0]

    hits = []
    for doc, meta, dist in zip(docs, metas, dists):
        # Filter on raw distance before rounding to avoid precision loss
        if max_distance > 0.0 and dist > max_distance:
            continue
        hits.append(
            {
                "text": doc,
                "wing": meta.get("wing", "unknown"),
                "room": meta.get("room", "unknown"),
                "source_file": Path(meta.get("source_file", "?")).name,
                "similarity": round(max(0.0, 1 - dist), 3),
                "distance": round(dist, 4),
                "filed_at": meta.get("filed_at", ""),
                "metadata": {k: v for k, v in meta.items()
                             if k not in ("wing", "room", "source_file", "chunk_index")},
            }
        )

    if sort_by == "recency":
        hits.sort(key=lambda h: h.get("filed_at", ""), reverse=True)

    return {
        "query": query,
        "filters": {"wing": wing, "room": room, "where": where},
        "sort_by": sort_by,
        "total_before_filter": len(docs),
        "results": hits,
    }
