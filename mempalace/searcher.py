#!/usr/bin/env python3
"""
searcher.py — Find anything. Exact words.

Semantic search against the palace.
Returns verbatim text — the actual words, never summaries.
"""

import logging
import re
from pathlib import Path

import chromadb

from .palace import distance_to_similarity, get_embedding_function

logger = logging.getLogger("mempalace_mcp")
_TOKEN_RE = re.compile(r"[a-z0-9_]+")


class SearchError(Exception):
    """Raised when search cannot proceed (e.g. no palace found)."""


def _query_terms(query: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall(query.lower()) if len(token) >= 2}


def _overlap_score(query_terms: set[str], text: str) -> tuple[int, int]:
    if not query_terms:
        return 0, 0
    text_lower = text.lower()
    doc_terms = set(_TOKEN_RE.findall(text_lower))
    overlap = len(query_terms & doc_terms)
    phrase_bonus = int(any(term in text_lower for term in query_terms))
    return overlap, phrase_bonus


def _rerank_hits(query: str, hits: list[dict]) -> list[dict]:
    query_terms = _query_terms(query)
    if not query_terms:
        return hits

    ranked = []
    for index, hit in enumerate(hits):
        overlap, phrase_bonus = _overlap_score(query_terms, hit["text"])
        ranked.append((overlap, phrase_bonus, hit["similarity"], -index, hit))

    ranked.sort(reverse=True)
    return [hit for *_scores, hit in ranked]


def search(query: str, palace_path: str, wing: str = None, room: str = None, n_results: int = 5):
    """
    Search the palace. Returns verbatim drawer content.
    Optionally filter by wing (project) or room (aspect).
    """
    try:
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection(
            "mempalace_drawers",
            embedding_function=get_embedding_function(),
        )
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

    hits = _rerank_hits(
        query,
        [
            {
                "text": doc,
                "meta": meta,
                "distance": dist,
                "similarity": distance_to_similarity(dist),
            }
            for doc, meta, dist in zip(docs, metas, dists)
        ],
    )

    for i, hit in enumerate(hits, 1):
        doc = hit["text"]
        meta = hit["meta"]
        similarity = hit["similarity"]
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
    query: str, palace_path: str, wing: str = None, room: str = None, n_results: int = 5,
    min_similarity: float = 0.0
) -> dict:
    """
    Programmatic search — returns a dict instead of printing.
    Used by the MCP server and other callers that need data.

    Args:
        min_similarity: Minimum similarity score (0.0–1.0). Results below this threshold
            are excluded. Default 0.0 returns all results.
    """
    try:
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection(
            "mempalace_drawers",
            embedding_function=get_embedding_function(),
        )
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
        similarity = distance_to_similarity(dist)
        if similarity < min_similarity:
            continue
        hits.append(
            {
                "text": doc,
                "wing": meta.get("wing", "unknown"),
                "room": meta.get("room", "unknown"),
                "source_file": Path(meta.get("source_file", "?")).name,
                "similarity": similarity,
            }
        )

    hits = _rerank_hits(query, hits)

    return {
        "query": query,
        "filters": {"wing": wing, "room": room},
        "results": hits,
    }
