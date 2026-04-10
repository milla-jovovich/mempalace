#!/usr/bin/env python3
"""
searcher.py — Find anything. Exact words.

Semantic search against the palace.
Returns verbatim text — the actual words, never summaries.

When ``cursor_source_filter`` is enabled, ``search_memories`` requests extra
candidates from Chroma before post-filtering. Tune how many with the environment
variable ``MEMPALACE_CURSOR_SEARCH_FETCH_MULTIPLIER`` (integer, default 12, max 48),
or pass ``cursor_fetch_multiplier`` for programmatic overrides.
"""

import logging
import os
from pathlib import Path
from typing import Optional

import chromadb

logger = logging.getLogger("mempalace_mcp")
CHAT_SOURCE_MARKER = "/agent-transcripts/"
SUBAGENT_SOURCE_MARKER = "/subagents/"
MIN_SIMILARITY = 0.15
FETCH_MULTIPLIER = 12
_CURSOR_FETCH_MULTIPLIER_ENV = "MEMPALACE_CURSOR_SEARCH_FETCH_MULTIPLIER"
_MAX_CURSOR_FETCH_MULTIPLIER = 48


def _cursor_fetch_multiplier() -> int:
    """Default multiplier when ``cursor_fetch_multiplier`` is not passed explicitly."""
    raw = os.environ.get(_CURSOR_FETCH_MULTIPLIER_ENV, "").strip()
    if not raw:
        return FETCH_MULTIPLIER
    try:
        n = int(raw)
    except ValueError:
        return FETCH_MULTIPLIER
    return max(1, min(n, _MAX_CURSOR_FETCH_MULTIPLIER))


def _effective_cursor_fetch_multiplier(explicit: Optional[int]) -> int:
    """Multiplier for Chroma fetch size when cursor post-filtering is on."""
    if explicit is not None:
        return max(1, min(int(explicit), _MAX_CURSOR_FETCH_MULTIPLIER))
    return _cursor_fetch_multiplier()


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
    cursor_source_filter: bool = False,
    cursor_fetch_multiplier: Optional[int] = None,
) -> dict:
    """
    Programmatic search — returns a dict instead of printing.
    Used by the MCP server and other callers that need data.

    If ``cursor_source_filter`` is True, Chroma is queried with
    ``n_results * multiplier`` rows so weak or duplicate transcript chunks can be
    dropped; ``multiplier`` comes from ``cursor_fetch_multiplier``, else from
    ``MEMPALACE_CURSOR_SEARCH_FETCH_MULTIPLIER`` (default 12).
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
        if cursor_source_filter:
            mult = _effective_cursor_fetch_multiplier(cursor_fetch_multiplier)
            fetch_n = n_results * mult
        else:
            fetch_n = n_results
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
    seen_texts = set()
    for doc, meta, dist in zip(docs, metas, dists):
        source_file = meta.get("source_file", "") or ""
        similarity = round(1 - dist, 3)

        if cursor_source_filter:
            # Keep primary chat transcript chunks, drop known noisy sources.
            if CHAT_SOURCE_MARKER not in source_file or SUBAGENT_SOURCE_MARKER in source_file:
                continue

            # Avoid weak matches that often produce irrelevant suggestions.
            if similarity < MIN_SIMILARITY:
                continue

            # Deduplicate repeated text chunks.
            doc_key = doc.strip()
            if doc_key in seen_texts:
                continue
            seen_texts.add(doc_key)

        hits.append(
            {
                "text": doc,
                "wing": meta.get("wing", "unknown"),
                "room": meta.get("room", "unknown"),
                "source_file": Path(source_file or "?").name,
                "similarity": similarity,
            }
        )
        if len(hits) >= n_results:
            break

    return {
        "query": query,
        "filters": {"wing": wing, "room": room},
        "results": hits,
    }
