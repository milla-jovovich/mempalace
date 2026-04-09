#!/usr/bin/env python3
"""
searcher.py — Find anything. Exact words.

Semantic search against the palace.
Returns verbatim text — the actual words, never summaries.
"""

import logging
from datetime import datetime, timezone
import math
from pathlib import Path

import chromadb

logger = logging.getLogger("mempalace_mcp")

from mempalace.config import MempalaceConfig


def _apply_time_decay(hits, half_life_days):
    """Re-rank hits by applying exponential time-decay to similarity scores.

    Args:
        hits: list of dicts with 'similarity' and 'filed_at' keys.
        half_life_days: half-life in days. If 0 or negative, no decay applied.

    Returns:
        Sorted list of hits with 'decay', 'original_similarity', and updated 'similarity'.
    """
    if not half_life_days or half_life_days <= 0:
        return hits

    now = datetime.now(timezone.utc)

    for hit in hits:
        filed_at_str = hit.get("filed_at", "")
        if filed_at_str:
            try:
                filed_at = datetime.fromisoformat(filed_at_str)
                if filed_at.tzinfo is None:
                    filed_at = filed_at.replace(tzinfo=timezone.utc)
                age_days = max((now - filed_at).total_seconds() / 86400, 0)
            except (ValueError, TypeError):
                age_days = 0
        else:
            age_days = 0

        decay = math.pow(0.5, age_days / half_life_days)
        hit["original_similarity"] = hit["similarity"]
        hit["decay"] = round(decay, 4)
        hit["similarity"] = round(hit["similarity"] * decay, 4)

    hits.sort(key=lambda h: h["similarity"], reverse=True)
    return hits


class SearchError(Exception):
    """Raised when search cannot proceed (e.g. no palace found)."""


def search(query: str, palace_path: str, wing: str = None, room: str = None, n_results: int = 5):
    """
    Search the palace. Returns verbatim drawer content.
    Optionally filter by wing (project) or room (aspect).
    """
    try:
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
    except Exception:
        print(f"\n  No palace found at {palace_path}")
        print("  Run: mempalace init <dir> then mempalace mine <dir>")
        raise SearchError(f"No palace found at {palace_path}")

    # Build where filter
    where = {}
    if wing and room:
        where = {"$and": [{"wing": wing}, {"room": room}]}
    elif wing:
        where = {"wing": wing}
    elif room:
        where = {"room": room}

    try:
        kwargs = {
            "query_texts": [query],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

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

    print(f"\n{'=' * 60}")
    print(f'  Results for: "{query}"')
    if wing:
        print(f"  Wing: {wing}")
    if room:
        print(f"  Room: {room}")
    print(f"{'=' * 60}\n")

    for i, (doc, meta, dist) in enumerate(zip(docs, metas, dists), 1):
        similarity = round(1 - dist, 3)
        source = Path(meta.get("source_file", "?")).name
        wing_name = meta.get("wing", "?")
        room_name = meta.get("room", "?")

        print(f"  [{i}] {wing_name} / {room_name}")
        print(f"      Source: {source}")
        print(f"      Match:  {similarity}")
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
    time_decay: bool = True,
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
    where = {}
    if wing and room:
        where = {"$and": [{"wing": wing}, {"room": room}]}
    elif wing:
        where = {"wing": wing}
    elif room:
        where = {"room": room}

    try:
        kwargs = {
            "query_texts": [query],
            "n_results": n_results,
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
        hits.append(
            {
                "text": doc,
                "wing": meta.get("wing", "unknown"),
                "room": meta.get("room", "unknown"),
                "source_file": Path(meta.get("source_file", "?")).name,
                "similarity": round(1 - dist, 3),
                "filed_at": meta.get("filed_at", ""),
            }
        )

    # Apply time-decay scoring
    if time_decay:
        try:
            half_life = MempalaceConfig().time_decay_half_life_days
        except Exception:
            half_life = 90
        hits = _apply_time_decay(hits, half_life)

    return {
        "query": query,
        "filters": {"wing": wing, "room": room},
        "time_decay": time_decay,
        "results": hits,
    }
