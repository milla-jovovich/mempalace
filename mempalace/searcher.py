#!/usr/bin/env python3
"""
searcher.py — Find anything. Exact words.

Hybrid search: BM25 keyword matching + vector semantic similarity.
Searches closets first (fast index), then hydrates full drawer content.
Falls back to direct drawer search for palaces without closets.
"""

import logging
import math
import re
from pathlib import Path

from .palace import get_collection, get_closets_collection

logger = logging.getLogger("mempalace_mcp")


class SearchError(Exception):
    """Raised when search cannot proceed (e.g. no palace found)."""


def _bm25_score(query: str, document: str, k1: float = 1.5, b: float = 0.75, avg_dl: float = 500) -> float:
    """Simple BM25 score for a single document against a query.

    This is a lightweight keyword-matching signal that complements vector
    similarity. It catches exact matches that embeddings might miss
    (e.g., specific names, project codes, error messages).
    """
    query_terms = set(re.findall(r'\w{2,}', query.lower()))
    doc_terms = re.findall(r'\w{2,}', document.lower())
    if not query_terms or not doc_terms:
        return 0.0
    doc_len = len(doc_terms)
    term_freq = {}
    for t in doc_terms:
        term_freq[t] = term_freq.get(t, 0) + 1

    score = 0.0
    for term in query_terms:
        tf = term_freq.get(term, 0)
        if tf > 0:
            # Simplified IDF — treat each query term as moderately rare
            idf = math.log(2.0)
            numerator = tf * (k1 + 1)
            denominator = tf + k1 * (1 - b + b * doc_len / avg_dl)
            score += idf * numerator / denominator
    return score


def _hybrid_rank(vector_results, query: str, vector_weight: float = 0.6, bm25_weight: float = 0.4):
    """Re-rank results using both vector distance and BM25 keyword score.

    Returns results sorted by combined score (higher = better).
    """
    if not vector_results:
        return vector_results

    # Normalize vector distances to 0-1 similarity
    max_dist = max(r.get("distance", 1.0) for r in vector_results) or 1.0
    for r in vector_results:
        vec_sim = max(0.0, 1 - r.get("distance", 1.0) / max(max_dist, 0.001))
        bm25 = _bm25_score(query, r.get("text", ""))
        # Normalize BM25 to roughly 0-1 range
        bm25_norm = min(bm25 / 3.0, 1.0)
        r["_hybrid_score"] = vector_weight * vec_sim + bm25_weight * bm25_norm
        r["bm25_score"] = round(bm25, 3)

    vector_results.sort(key=lambda r: r["_hybrid_score"], reverse=True)
    # Clean up internal field
    for r in vector_results:
        del r["_hybrid_score"]
    return vector_results


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
        col = get_collection(palace_path, create=False)
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
    """
    try:
        drawers_col = get_collection(palace_path, create=False)
    except Exception as e:
        logger.error("No palace found at %s: %s", palace_path, e)
        return {
            "error": "No palace found",
            "hint": "Run: mempalace init <dir> && mempalace mine <dir>",
        }

    where = build_where_filter(wing, room)

    # Hybrid retrieval: always query drawers directly (the floor), then use
    # closet hits to boost rankings. Closets are a ranking SIGNAL, never a
    # GATE — direct drawer search is always the baseline.
    #
    # This avoids the "weak-closets regression" where narrative content
    # produces low-signal closets (regex extraction matches few topics)
    # and closet-first routing hides drawers that direct search would find.
    try:
        dkwargs = {
            "query_texts": [query],
            "n_results": n_results * 3,  # over-fetch for re-ranking
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            dkwargs["where"] = where
        drawer_results = drawers_col.query(**dkwargs)
    except Exception as e:
        return {"error": f"Search error: {e}"}

    # Gather closet hits (best-per-source) to build a boost lookup.
    closet_boost_by_source = {}  # source_file -> (rank, closet_dist, preview)
    try:
        closets_col = get_closets_collection(palace_path, create=False)
        ckwargs = {
            "query_texts": [query],
            "n_results": n_results * 2,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            ckwargs["where"] = where
        closet_results = closets_col.query(**ckwargs)
        for rank, (doc, meta, dist) in enumerate(
            zip(
                closet_results["documents"][0],
                closet_results["metadatas"][0],
                closet_results["distances"][0],
            )
        ):
            source = meta.get("source_file", "")
            if source and source not in closet_boost_by_source:
                closet_boost_by_source[source] = (rank, dist, doc[:200])
    except Exception:
        pass  # no closets yet — hybrid degrades to pure drawer search

    # Rank-based boost. Ordinal signal (which closet matched best) is more
    # reliable than absolute distance on narrative content.
    CLOSET_RANK_BOOSTS = [0.40, 0.25, 0.15, 0.08, 0.04]
    CLOSET_DISTANCE_CAP = 1.5  # cosine dist > 1.5 = too weak to use as signal

    scored = []
    for doc, meta, dist in zip(
        drawer_results["documents"][0],
        drawer_results["metadatas"][0],
        drawer_results["distances"][0],
    ):
        if max_distance > 0.0 and dist > max_distance:
            continue

        source = meta.get("source_file", "")
        boost = 0.0
        matched_via = "drawer"
        closet_preview = None
        if source in closet_boost_by_source:
            c_rank, c_dist, c_preview = closet_boost_by_source[source]
            if c_dist <= CLOSET_DISTANCE_CAP and c_rank < len(CLOSET_RANK_BOOSTS):
                boost = CLOSET_RANK_BOOSTS[c_rank]
                matched_via = "drawer+closet"
                closet_preview = c_preview

        effective_dist = dist - boost
        entry = {
            "text": doc,
            "wing": meta.get("wing", "unknown"),
            "room": meta.get("room", "unknown"),
            "source_file": Path(source).name if source else "?",
            "similarity": round(max(0.0, 1 - effective_dist), 3),
            "distance": round(dist, 4),
            "effective_distance": round(effective_dist, 4),
            "closet_boost": round(boost, 3),
            "matched_via": matched_via,
            "_sort_key": effective_dist,
        }
        if closet_preview:
            entry["closet_preview"] = closet_preview
        scored.append(entry)

    scored.sort(key=lambda h: h["_sort_key"])
    hits = scored[:n_results]

    # Drawer-grep enrichment: for top hits whose source file has multiple
    # drawers, return the best-matching chunk + its immediate neighbors
    # instead of just the single drawer. Preserves the chunk-expansion
    # behavior users relied on in the closet-first path.
    MAX_HYDRATION_CHARS = 10000
    import re as _re

    for h in hits:
        if h["matched_via"] == "drawer":
            continue
        # Only enrich closet-matched hits (cheap: we already know source matters)
        source_name = h["source_file"]
        # Look up full source_file by matching suffix in candidate pool
        full_source = next(
            (
                m.get("source_file", "")
                for m in drawer_results["metadatas"][0]
                if m.get("source_file", "").endswith(source_name)
            ),
            "",
        )
        if not full_source:
            continue
        try:
            source_drawers = drawers_col.get(
                where={"source_file": full_source}, include=["documents"]
            )
        except Exception:
            continue
        docs = source_drawers.get("documents") or []
        if len(docs) <= 1:
            continue

        query_terms = set(_re.findall(r"\w{2,}", query.lower()))
        best_idx, best_score = 0, -1
        for idx, d in enumerate(docs):
            d_lower = d.lower()
            s = sum(1 for t in query_terms if t in d_lower)
            if s > best_score:
                best_score, best_idx = s, idx

        start = max(0, best_idx - 1)
        end = min(len(docs), best_idx + 2)
        expanded = "\n\n".join(docs[start:end])
        if len(expanded) > MAX_HYDRATION_CHARS:
            expanded = (
                expanded[:MAX_HYDRATION_CHARS]
                + f"\n\n[...truncated. {len(docs)} total drawers. Use mempalace_get_drawer for full content.]"
            )
        h["text"] = expanded
        h["drawer_index"] = best_idx
        h["total_drawers"] = len(docs)

    # BM25 hybrid re-rank within the final candidate set
    hits = _hybrid_rank(hits, query)
    for h in hits:
        h.pop("_sort_key", None)

    return {
        "query": query,
        "filters": {"wing": wing, "room": room},
        "total_before_filter": len(drawer_results["documents"][0]),
        "results": hits,
    }
