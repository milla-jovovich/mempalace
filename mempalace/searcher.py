#!/usr/bin/env python3
"""
searcher.py — Find anything. Exact words.

Semantic search against the palace with keyword fallback.
Returns verbatim text — the actual words, never summaries.
"""

import logging
import re
from pathlib import Path

import chromadb


# Common words to skip when extracting keywords for fallback search
_STOPWORDS = frozenset(
    "a an the is was were be been am are being do does did have has had "
    "will would shall should may might can could get got it its i me my we "
    "our you your he she they them his her this that these those of in to "
    "for on with at by from as into about between through after before "
    "what when where how who which why all any each no not or and but if".split()
)


def _extract_keyword(query: str) -> str:
    """Extract the most distinctive token from a query for keyword fallback.

    Picks the longest non-stopword token.  Prefers tokens that look like
    identifiers (contain digits, dots, underscores, or are ALLCAPS).
    """
    tokens = re.findall(r"[\w.]+", query.lower())
    candidates = [t for t in tokens if t not in _STOPWORDS and len(t) > 2]
    if not candidates:
        return ""
    # Prefer identifier-looking tokens (error codes, config keys, etc.)
    ids = [t for t in candidates if re.search(r"\d|_|\.", t) or t.isupper()]
    if ids:
        return max(ids, key=len)
    return max(candidates, key=len)

logger = logging.getLogger("mempalace_mcp")


class SearchError(Exception):
    """Raised when search cannot proceed (e.g. no palace found)."""


def build_where_filter(wing: str = None, room: str = None) -> dict:
    """Build ChromaDB where filter for wing/room filtering."""
    if wing and room:
        return {"$and": [{"wing": wing}, {"room": room}]}
    elif wing:
        return {"wing": wing}
    elif room:
        return {"room": room}
    return {}


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

    where = build_where_filter(wing, room)

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
        similarity = round(max(0.0, 1 - dist), 3)
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
    max_distance: float = 0.0,
    keyword: str = None,
) -> dict:
    """Programmatic search — returns a dict instead of printing.

    Used by the MCP server and other callers that need data.

    Hybrid search: runs vector search first, then falls back to keyword
    matching via ChromaDB where_document if the vector results are poor
    (best distance > 1.0) or if an explicit keyword is provided.

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
        keyword: Explicit keyword for text-match fallback. If omitted,
            extracted automatically from query when vector results are poor.
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

    where = build_where_filter(wing, room)

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

    # --- Keyword fallback for hybrid search ---
    # If vector results are poor (best > 1.0) or empty, or an explicit
    # keyword was requested, try text-match via where_document.$contains.
    kw = keyword or ""
    best_dist = dists[0] if dists else 2.0
    needs_fallback = not docs or best_dist > 1.0
    if needs_fallback and not kw:
        kw = _extract_keyword(query)

    kw_hits_by_id = {}
    if kw:
        try:
            kw_kwargs = {
                "query_texts": [query],
                "n_results": n_results,
                "include": ["documents", "metadatas", "distances"],
                "where_document": {"$contains": kw},
            }
            if where:
                kw_kwargs["where"] = where
            kw_results = col.query(**kw_kwargs)
            kw_docs = kw_results["documents"][0]
            kw_metas = kw_results["metadatas"][0]
            kw_dists = kw_results["distances"][0]
            kw_ids = kw_results["ids"][0] if kw_results.get("ids") else [""] * len(kw_docs)
            for kid, kdoc, kmeta, kdist in zip(kw_ids, kw_docs, kw_metas, kw_dists):
                kw_hits_by_id[kid] = (kdoc, kmeta, kdist)
        except Exception:
            pass  # keyword fallback is best-effort

    # Build hit list from vector results
    seen_ids = set()
    hits = []
    vec_ids = results["ids"][0] if results.get("ids") else [""] * len(docs)
    for did, doc, meta, dist in zip(vec_ids, docs, metas, dists):
        if max_distance > 0.0 and dist > max_distance:
            continue
        seen_ids.add(did)
        hits.append(
            {
                "text": doc,
                "wing": meta.get("wing", "unknown"),
                "room": meta.get("room", "unknown"),
                "source_file": Path(meta.get("source_file", "?")).name,
                "similarity": round(max(0.0, 1 - dist), 3),
                "distance": round(dist, 4),
            }
        )

    # Merge keyword hits that weren't in vector results
    for kid, (kdoc, kmeta, kdist) in kw_hits_by_id.items():
        if kid in seen_ids:
            continue
        if max_distance > 0.0 and kdist > max_distance:
            continue
        hits.append(
            {
                "text": kdoc,
                "wing": kmeta.get("wing", "unknown"),
                "room": kmeta.get("room", "unknown"),
                "source_file": Path(kmeta.get("source_file", "?")).name,
                "similarity": round(max(0.0, 1 - kdist), 3),
                "distance": round(kdist, 4),
                "keyword_match": kw,
            }
        )

    # Sort merged results by distance
    hits.sort(key=lambda h: h["distance"])
    hits = hits[:n_results]

    return {
        "query": query,
        "filters": {"wing": wing, "room": room},
        "keyword_fallback": kw if kw_hits_by_id else None,
        "total_before_filter": len(docs) + len(kw_hits_by_id),
        "results": hits,
    }
