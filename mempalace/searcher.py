#!/usr/bin/env python3
"""
searcher.py — Find anything. Exact words.

Semantic search against the palace.
Returns verbatim text — the actual words, never summaries.
"""

import logging
from pathlib import Path

import chromadb

logger = logging.getLogger("mempalace_mcp")


class SearchError(Exception):
    """Raised when search cannot proceed (e.g. no palace found)."""


def search(
    query: str,
    palace_path: str,
    wing: str = None,
    room: str = None,
    n_results: int = 5,
    deep: bool = False,
) -> list[dict]:
    """
    Search the palace. Returns verbatim drawer content.
    Optionally filter by wing (project) or room (aspect).
    """
    try:
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
    except Exception:
        raise SearchError(f"No palace found at {palace_path}")

    # Build where filter
    where_clauses = []
    if wing:
        where_clauses.append({"wing": wing})

    if room:
        where_clauses.append({"room": room})

    where = {}
    if len(where_clauses) == 1:
        where = where_clauses[0]
    elif len(where_clauses) > 1:
        where = {"$and": where_clauses}

    try:
        fetch_n = n_results * 2 if not deep and not wing else n_results
        kwargs = {
            "query_texts": [query],
            "n_results": fetch_n,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        results = col.query(**kwargs)

    except Exception as e:
        raise SearchError(f"Search error: {e}") from e

    docs = results["documents"][0]
    metas = results["metadatas"][0]
    dists = results["distances"][0]

    filtered = []
    for doc, meta, dist in zip(docs, metas, dists):
        meta = meta or {}
        if not deep and meta.get("wing") == "archive":
            continue
        filtered.append({
            "document": doc,
            "metadata": meta,
            "distance": dist
        })
        if len(filtered) >= n_results:
            break

    return filtered



def search_memories(
    query: str,
    palace_path: str,
    wing: str = None,
    room: str = None,
    n_results: int = 5,
    deep: bool = False,
) -> dict:
    """
    Programmatic search — returns a dict instead of printing.
    Used by the MCP server and other callers that need data.
    """
    try:
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
    except Exception as e:
        logger.error("No palace found at %s: %s", palace_path, e)
        return {
            "error": "No palace found",
            "hint": "Run: mempalace init <dir> && mempalace mine <dir>",
        }

    # Build where filter
    where_clauses = []
    if wing:
        where_clauses.append({"wing": wing})

    if room:
        where_clauses.append({"room": room})

    where = {}
    if len(where_clauses) == 1:
        where = where_clauses[0]
    elif len(where_clauses) > 1:
        where = {"$and": where_clauses}

    try:
        fetch_n = n_results * 2 if not deep and not wing else n_results
        kwargs = {
            "query_texts": [query],
            "n_results": fetch_n,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        results = col.query(**kwargs)
    except Exception as e:
        return {"error": f"Search error: {e}"}

    docs = results["documents"][0]
    metas = results["metadatas"][0]
    dists = results["distances"][0]

    hits = []
    for doc, meta, dist in zip(docs, metas, dists):
        meta = meta or {}
        if not deep and meta.get("wing") == "archive":
            continue

        hits.append(
            {
                "text": doc,
                "wing": meta.get("wing", "unknown"),
                "room": meta.get("room", "unknown"),
                "source_file": Path(meta.get("source_file", "?")).name,
                "similarity": round(1 - dist, 3),
            }
        )
        if len(hits) >= n_results:
            break

    return {
        "query": query,
        "filters": {"wing": wing, "room": room},
        "results": hits,
    }
