#!/usr/bin/env python3
"""
searcher.py — Find anything. Exact words.

Hybrid search: BM25 keyword matching + vector semantic similarity. The
drawer query is the floor — always runs — and closet hits add a rank-based
boost when they agree. Closets are a ranking *signal*, never a gate, so
weak closets (regex extraction on narrative content) can only help, never
hide drawers the direct path would have found.
"""

import logging
import math
import re
from pathlib import Path
from typing import Optional

from .palace import get_closets_collection, get_collection

# Closet pointer line format: "topic|entities|→drawer_id_a,drawer_id_b"
# Multiple lines may join with newlines inside one closet document.
_CLOSET_DRAWER_REF_RE = re.compile(r"→([\w,]+)")


logger = logging.getLogger("mempalace_mcp")


class SearchError(Exception):
    """Raised when search cannot proceed (e.g. no palace found)."""


_TOKEN_RE = re.compile(r"\w{2,}", re.UNICODE)


def _first_or_empty(results, key: str) -> list:
    """Return the first inner list of a query result field, or [].

    Accepts both the typed :class:`QueryResult` (attribute access) and the
    pre-typed chroma dict shape; this polymorphism is retained so test mocks
    still work and callers mid-migration do not crash. Preserves the empty-
    collection semantics from issue #195: when no queries returned hits, the
    outer list may be empty and indexing ``[0]`` would raise.
    """
    outer = getattr(results, key, None) if not isinstance(results, dict) else results.get(key)
    if not outer:
        return []
    return outer[0] or []


def _tokenize(text: str) -> list:
    """Lowercase + strip to alphanumeric tokens of length ≥ 2.

    Tolerates ``None`` documents — Chroma can return ``None`` in the
    ``documents`` field for drawers without text content, which would
    otherwise raise ``AttributeError`` mid-rerank.
    """
    if not text:
        return []
    return _TOKEN_RE.findall(text.lower())


def _bm25_scores(
    query: str,
    documents: list,
    k1: float = 1.5,
    b: float = 0.75,
) -> list:
    """Compute Okapi-BM25 scores for ``query`` against each document.

    IDF is computed over the *provided corpus* using the Lucene/BM25+
    smoothed formula ``log((N - df + 0.5) / (df + 0.5) + 1)``, which is
    always non-negative. This is well-defined for re-ranking a small
    candidate set returned by vector retrieval — IDF then reflects how
    discriminative each query term is *within the candidates*, exactly
    what's needed to reorder them.

    Parameters mirror Okapi-BM25 conventions:
        k1 — term-frequency saturation (1.2-2.0 typical, 1.5 default)
        b  — length normalization (0.0 = none, 1.0 = full, 0.75 default)

    Returns a list of scores in the same order as ``documents``.
    """
    n_docs = len(documents)
    query_terms = set(_tokenize(query))
    if not query_terms or n_docs == 0:
        return [0.0] * n_docs

    tokenized = [_tokenize(d) for d in documents]
    doc_lens = [len(toks) for toks in tokenized]
    if not any(doc_lens):
        return [0.0] * n_docs
    avgdl = sum(doc_lens) / n_docs or 1.0

    # Document frequency: how many docs contain each query term?
    df = {term: 0 for term in query_terms}
    for toks in tokenized:
        seen = set(toks) & query_terms
        for term in seen:
            df[term] += 1

    idf = {term: math.log((n_docs - df[term] + 0.5) / (df[term] + 0.5) + 1) for term in query_terms}

    scores = []
    for toks, dl in zip(tokenized, doc_lens):
        if dl == 0:
            scores.append(0.0)
            continue
        tf: dict = {}
        for t in toks:
            if t in query_terms:
                tf[t] = tf.get(t, 0) + 1
        score = 0.0
        for term, freq in tf.items():
            num = freq * (k1 + 1)
            den = freq + k1 * (1 - b + b * dl / avgdl)
            score += idf[term] * num / den
        scores.append(score)
    return scores


def _hybrid_rank(
    results: list,
    query: str,
    vector_weight: float = 0.6,
    bm25_weight: float = 0.4,
) -> list:
    """Re-rank ``results`` by a convex combination of vector similarity and BM25.

    * Vector similarity uses absolute cosine sim ``max(0, 1 - distance)`` —
      ChromaDB's hnsw cosine distance lives in ``[0, 2]`` (0 = identical).
      Absolute (not relative-to-max) means adding/removing a candidate
      can't reshuffle the others.
    * BM25 is real Okapi-BM25 with corpus-relative IDF over the candidates
      themselves. Since the absolute scale is unbounded, BM25 is min-max
      normalized within the candidate set so weights are commensurable.

    Mutates each result dict to add ``bm25_score`` and reorders the list
    in place. Returns the same list for convenience.
    """
    if not results:
        return results

    docs = [r.get("text", "") for r in results]
    bm25_raw = _bm25_scores(query, docs)
    max_bm25 = max(bm25_raw) if bm25_raw else 0.0
    bm25_norm = [s / max_bm25 for s in bm25_raw] if max_bm25 > 0 else [0.0] * len(bm25_raw)

    scored = []
    for r, raw, norm in zip(results, bm25_raw, bm25_norm):
        vec_sim = max(0.0, 1.0 - r.get("distance", 1.0))
        r["bm25_score"] = round(raw, 3)
        scored.append((vector_weight * vec_sim + bm25_weight * norm, r))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    results[:] = [r for _, r in scored]
    return results


def build_where_filter(wing: str = None, room: str = None) -> dict:
    """Build ChromaDB where filter for wing/room filtering."""
    if wing and room:
        return {"$and": [{"wing": wing}, {"room": room}]}
    elif wing:
        return {"wing": wing}
    elif room:
        return {"room": room}
    return {}


def _extract_drawer_ids_from_closet(closet_doc: str) -> list:
    """Parse all `→drawer_id_a,drawer_id_b` pointers out of a closet document.

    Preserves order and dedupes.
    """
    seen: dict = {}
    for match in _CLOSET_DRAWER_REF_RE.findall(closet_doc):
        for did in match.split(","):
            did = did.strip()
            if did and did not in seen:
                seen[did] = None
    return list(seen.keys())


def _expand_with_neighbors(drawers_col, matched_doc: str, matched_meta: dict, radius: int = 1):
    """Expand a matched drawer with its ±radius sibling chunks in the same source file.

    Motivation — "drawer-grep context" feature: a closet hit returns one
    drawer, but the chunk boundary may clip mid-thought (e.g., the matched
    chunk says "here's a breakdown:" and the actual breakdown lives in the
    next chunk). Fetching the small neighborhood around the match gives
    callers enough context without forcing a follow-up ``get_drawer`` call.

    Returns a dict with:
        ``text``            combined chunks in chunk_index order
        ``drawer_index``    the matched chunk's index in the source file
        ``total_drawers``   total drawer count for the source file (or None)

    On any ChromaDB failure or missing metadata, falls back to returning the
    matched drawer alone so search never breaks because neighbor expansion
    failed.
    """
    src = matched_meta.get("source_file")
    chunk_idx = matched_meta.get("chunk_index")
    if not src or not isinstance(chunk_idx, int):
        return {"text": matched_doc, "drawer_index": chunk_idx, "total_drawers": None}

    target_indexes = [chunk_idx + offset for offset in range(-radius, radius + 1)]
    try:
        neighbors = drawers_col.get(
            where={
                "$and": [
                    {"source_file": src},
                    {"chunk_index": {"$in": target_indexes}},
                ]
            },
            include=["documents", "metadatas"],
        )
    except Exception:
        return {"text": matched_doc, "drawer_index": chunk_idx, "total_drawers": None}

    indexed_docs = []
    for doc, meta in zip(neighbors.documents, neighbors.metadatas):
        ci = meta.get("chunk_index")
        if isinstance(ci, int):
            indexed_docs.append((ci, doc))
    indexed_docs.sort(key=lambda pair: pair[0])

    if not indexed_docs:
        combined_text = matched_doc
    else:
        combined_text = "\n\n".join(doc for _, doc in indexed_docs)

    # Cheap total_drawers lookup: metadata-only scan of the source file.
    total_drawers = None
    try:
        all_meta = drawers_col.get(where={"source_file": src}, include=["metadatas"])
        total_drawers = len(all_meta.ids) if all_meta.ids else None
    except Exception:
        pass

    return {
        "text": combined_text,
        "drawer_index": chunk_idx,
        "total_drawers": total_drawers,
    }


def search(query: str, palace_path: str, wing: str = None, room: str = None, n_results: int = 5):
    """
    Search the palace. Returns verbatim drawer content.
    Optionally filter by wing (project) or room (aspect).

    Delegates to ``search_memories`` so CLI and MCP callers share the same
    hybrid ranking, sqlite-BM25 fallback, and scope-aware warnings.
    """
    result = search_memories(query, palace_path, wing=wing, room=room, n_results=n_results)
    if "error" in result and not result.get("results"):
        # Preserve the palace path in the printed error so the user sees
        # which palace the search tried to open (a common source of
        # confusion when more than one palace is in play). The structured
        # error payload from search_memories is intentionally path-agnostic.
        error_message = result["error"]
        if error_message == "No palace found":
            error_message = f"{error_message} at {palace_path}"
        print(f"\n  {error_message}")
        if "hint" in result:
            print(f"  {result['hint']}")
        raise SearchError(error_message)

    warnings = result.get("warnings") or []
    hits = result.get("results") or []

    if not hits:
        print(f'\n  No results found for: "{query}"')
        for w in warnings:
            print(f"  ! {w}")
        return

    print(f"\n{'=' * 60}")
    print(f'  Results for: "{query}"')
    if wing:
        print(f"  Wing: {wing}")
    if room:
        print(f"  Room: {room}")
    if result.get("available_in_scope") is not None:
        print(f"  Scope has: {result['available_in_scope']} drawers matching filter")
    if warnings:
        for w in warnings:
            print(f"  ! {w}")
    print(f"{'=' * 60}\n")

    for i, hit in enumerate(hits, 1):
        wing_name = hit.get("wing", "?")
        room_name = hit.get("room", "?")
        source = hit.get("source_file", "?")
        similarity = hit.get("similarity")
        bm25 = hit.get("bm25_score")
        matched_via = hit.get("matched_via", "drawer")

        print(f"  [{i}] {wing_name} / {room_name}")
        print(f"      Source: {source}")
        if similarity is not None:
            print(f"      Match:  {similarity}")
        elif bm25 is not None:
            print(f"      BM25:   {bm25}  (matched_via: {matched_via})")
        else:
            print(f"      (matched_via: {matched_via})")
        print()
        for line in (hit.get("text") or "").strip().split("\n"):
            print(f"      {line}")
        print()
        print(f"  {'─' * 56}")

    print()


def _count_in_scope(drawers_col, where: dict) -> Optional[int]:
    """Return the total number of drawers matching ``where``.

    When ``where`` is empty (unfiltered scope), uses ``Collection.count()``
    which is O(1). Otherwise paginates ``get(include=[])`` — ChromaDB's
    ``count()`` does not accept a ``where`` filter. Pagination keeps each
    query well under the #950 "too many SQL variables" limit.

    Returns ``None`` if the count could not be computed (e.g., filter
    planner error).
    """
    try:
        if not where:
            return drawers_col.count()
        PAGE = 5000
        offset = 0
        total = 0
        while True:
            batch = drawers_col.get(limit=PAGE, offset=offset, include=[], where=where)
            batch_ids = batch.get("ids") or []
            if not batch_ids:
                break
            total += len(batch_ids)
            if len(batch_ids) < PAGE:
                break
            offset += len(batch_ids)
    except Exception:
        return None
    return total


def _sqlite_fallback_and_scope(
    drawers_col,
    query: str,
    where: dict,
    hits: list,
    n_results: int,
    vector_underdelivered: bool,
    allow_fallback: bool,
) -> tuple:
    """Compute the sqlite-authoritative in-scope count and, if enabled, top
    up the hits list with BM25-ranked sqlite candidates when the vector
    path returned fewer than ``n_results``.

    ``vector_underdelivered`` is independent from ``len(hits) < n_results``
    after this function mutates ``hits``, so callers can gate the "more in
    scope than we could rank" warning on whether the *vector path* was the
    degraded layer, rather than on the final hit count after BM25 top-up.

    Returns ``(available_in_scope, warnings)``. Mutates ``hits`` in place
    when it adds fallback entries.
    """
    warnings: list[str] = []

    # Sqlite-authoritative scope count (paginated, independent of the pool
    # we read for BM25 ranking). None on failure — caller treats that as
    # "unknown" rather than crashing.
    available_in_scope = _count_in_scope(drawers_col, where)

    if not allow_fallback or not vector_underdelivered:
        return available_in_scope, warnings

    shortfall = n_results - len(hits)
    if shortfall <= 0:
        return available_in_scope, warnings

    # Fetch a bounded BM25 candidate pool. Cap keeps #950 at bay and a
    # pool 20x the request is plenty for keyword-rank top-up.
    try:
        pool_kwargs: dict = {"include": ["documents", "metadatas"]}
        if where:
            pool_kwargs["where"] = where
        pool_kwargs["limit"] = max(n_results * 20, 100)
        pool = drawers_col.get(**pool_kwargs)
    except Exception as e:
        warnings.append(f"sqlite fallback unavailable: {e}")
        return available_in_scope, warnings

    pool_docs = pool.get("documents") or []
    pool_metas = pool.get("metadatas") or []
    if not pool_docs:
        return available_in_scope, warnings

    seen_texts = {h.get("text") for h in hits if h.get("text")}
    candidate_docs: list = []
    candidate_metas: list = []
    for d, m in zip(pool_docs, pool_metas):
        if d in seen_texts:
            continue
        candidate_docs.append(d)
        candidate_metas.append(m or {})

    if not candidate_docs:
        return available_in_scope, warnings

    bm25 = _bm25_scores(query, candidate_docs)
    ranked = sorted(
        zip(candidate_docs, candidate_metas, bm25),
        key=lambda t: t[2],
        reverse=True,
    )
    added = 0
    for doc, meta, score in ranked:
        if added >= shortfall:
            break
        if score <= 0.0:
            # No query term present — skip rather than pad with arbitrary
            # content, so the warning stays accurate.
            break
        src = meta.get("source_file", "") or ""
        hits.append(
            {
                "text": doc,
                "wing": meta.get("wing", "unknown"),
                "room": meta.get("room", "unknown"),
                "source_file": Path(src).name if src else "?",
                "created_at": meta.get("filed_at", "unknown"),
                "similarity": None,
                "distance": None,
                "bm25_score": round(score, 3),
                "matched_via": "sqlite_bm25_fallback",
            }
        )
        added += 1
    if added > 0:
        vector_count = len(hits) - added
        warnings.append(
            f"vector search returned {vector_count} of {n_results} "
            f"requested; filled {added} from sqlite+BM25 keyword match"
        )
    return available_in_scope, warnings


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

    Hybrid search: BM25 keyword matching + vector semantic similarity.
    The drawer query is the floor — always runs — and closet hits add a
    rank-based boost when they agree.

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
    warnings: list[str] = []
    drawer_results: dict = {"documents": [[]], "metadatas": [[]], "distances": [[]]}
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
        # Don't hard-fail: degrade to sqlite fallback below so callers still
        # get the drawers that match the scope, with a warning explaining why
        # vector ranking was unavailable. This covers the #951 filter-planner
        # "Error finding id" failure mode and HNSW runtime errors on drifted
        # indexes.
        warnings.append(f"vector search unavailable: {e}")

    # Gather closet hits (best-per-source) to build a boost lookup.
    closet_boost_by_source: dict = {}  # source_file -> (rank, closet_dist, preview)
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
        for rank, (cdoc, cmeta, cdist) in enumerate(
            zip(
                _first_or_empty(closet_results, "documents"),
                _first_or_empty(closet_results, "metadatas"),
                _first_or_empty(closet_results, "distances"),
            )
        ):
            cmeta = cmeta or {}
            source = cmeta.get("source_file", "")
            if source and source not in closet_boost_by_source:
                closet_boost_by_source[source] = (rank, cdist, cdoc[:200])
    except Exception:
        pass  # no closets yet — hybrid degrades to pure drawer search

    # Rank-based boost. The ordinal signal ("which closet matched best") is
    # more reliable than absolute distance on narrative content, where
    # closet distances cluster in 1.2-1.5 range regardless of match quality.
    CLOSET_RANK_BOOSTS = [0.40, 0.25, 0.15, 0.08, 0.04]
    CLOSET_DISTANCE_CAP = 1.5  # cosine dist > 1.5 = too weak to use as signal

    scored: list = []
    for doc, meta, dist in zip(
        _first_or_empty(drawer_results, "documents"),
        _first_or_empty(drawer_results, "metadatas"),
        _first_or_empty(drawer_results, "distances"),
    ):
        # Filter on raw distance before rounding to avoid precision loss.
        if max_distance > 0.0 and dist > max_distance:
            continue

        meta = meta or {}
        source = meta.get("source_file", "") or ""
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
            "created_at": meta.get("filed_at", "unknown"),
            "similarity": round(max(0.0, 1 - effective_dist), 3),
            "distance": round(dist, 4),
            "effective_distance": round(effective_dist, 4),
            "closet_boost": round(boost, 3),
            "matched_via": matched_via,
            # Internal: retain the full source_file path + chunk_index so the
            # enrichment step below doesn't have to reverse-lookup via
            # basename-suffix matching (which silently collides when two
            # files share a basename across different directories).
            "_sort_key": effective_dist,
            "_source_file_full": source,
            "_chunk_index": meta.get("chunk_index"),
        }
        if closet_preview:
            entry["closet_preview"] = closet_preview
        scored.append(entry)

    scored.sort(key=lambda h: h["_sort_key"])
    hits = scored[:n_results]

    # Drawer-grep enrichment: for closet-boosted hits whose source has
    # multiple drawers, return the keyword-best chunk + its immediate
    # neighbors instead of just the drawer vector search landed on. The
    # closet said "this source is relevant"; vector may have picked the
    # wrong chunk within it; grep picks the right one.
    MAX_HYDRATION_CHARS = 10000
    for h in hits:
        if h["matched_via"] == "drawer":
            continue
        full_source = h.get("_source_file_full") or ""
        if not full_source:
            continue
        try:
            source_drawers = drawers_col.get(
                where={"source_file": full_source},
                include=["documents", "metadatas"],
            )
        except Exception:
            continue
        docs = source_drawers.documents
        metas_ = source_drawers.metadatas
        if len(docs) <= 1:
            continue

        # Sort by chunk_index so best_idx + neighbors are positional.
        indexed = []
        for idx, (d, m) in enumerate(zip(docs, metas_)):
            ci = m.get("chunk_index", idx) if isinstance(m, dict) else idx
            if not isinstance(ci, int):
                ci = idx
            indexed.append((ci, d))
        indexed.sort(key=lambda p: p[0])
        ordered_docs = [d for _, d in indexed]

        query_terms = set(_tokenize(query))
        best_idx, best_score = 0, -1
        for idx, d in enumerate(ordered_docs):
            d_lower = d.lower()
            s = sum(1 for t in query_terms if t in d_lower)
            if s > best_score:
                best_score, best_idx = s, idx

        start = max(0, best_idx - 1)
        end = min(len(ordered_docs), best_idx + 2)
        expanded = "\n\n".join(ordered_docs[start:end])
        if len(expanded) > MAX_HYDRATION_CHARS:
            expanded = (
                expanded[:MAX_HYDRATION_CHARS]
                + f"\n\n[...truncated. {len(ordered_docs)} total drawers. "
                "Use mempalace_get_drawer for full content.]"
            )
        h["text"] = expanded
        h["drawer_index"] = best_idx
        h["total_drawers"] = len(ordered_docs)

    # BM25 hybrid re-rank within the final candidate set.
    hits = _hybrid_rank(hits, query)
    for h in hits:
        h.pop("_sort_key", None)
        h.pop("_source_file_full", None)
        h.pop("_chunk_index", None)

    # Track whether the VECTOR path was the degraded layer, separate from
    # the final hit count. This lets the "more in scope than we could rank"
    # warning fire correctly even when the BM25 fallback happened to fill
    # the request — the vector index still underdelivered, which is the
    # real signal pointing at `mempalace repair`.
    vector_hit_count = len(hits)
    vector_underdelivered = vector_hit_count < n_results

    # Capture vector hit count before BM25 may extend hits. The scope warning
    # must fire whenever vector underdelivered — even when BM25 fills the
    # request to n_results — because vector is still the degraded layer.
    # BM25 fallback is a reliability mechanism: it fires when the distance
    # threshold is permissive (max_distance=0.0 means "no filtering") OR
    # when a vector error occurred (warnings non-empty at this point). This
    # ensures MCP callers on a drifted palace get fallback coverage even
    # though tool_search passes max_distance=1.5, without firing fallback
    # when a strict distance filter legitimately eliminates all results on
    # a working HNSW index.
    allow_fallback = (max_distance <= 0.0) or bool(warnings)
    available_in_scope, fallback_warnings = _sqlite_fallback_and_scope(
        drawers_col,
        query,
        where,
        hits,
        n_results=n_results,
        vector_underdelivered=vector_underdelivered,
        allow_fallback=allow_fallback,
    )
    warnings.extend(fallback_warnings)

    # Surface unreachable data: the scope in sqlite has more drawers than
    # the vector path could rank. Gate off vector_underdelivered (not final
    # hit count) so the warning still surfaces when BM25 fallback filled
    # the request — vector is still the degraded layer; the fallback is
    # keyword-only and doesn't have semantic recall.
    if (
        vector_underdelivered
        and available_in_scope is not None
        and available_in_scope > vector_hit_count
    ):
        warnings.append(
            f"{available_in_scope} drawers match this scope in sqlite; "
            f"vector ranked {vector_hit_count} — the rest are only reachable "
            f"by keyword match. Run `mempalace repair` to rebuild the HNSW "
            f"index for full semantic recall."
        )

    return {
        "query": query,
        "filters": {"wing": wing, "room": room},
        "total_before_filter": len(_first_or_empty(drawer_results, "documents")),
        "available_in_scope": available_in_scope,
        "warnings": warnings,
        "results": hits,
    }
