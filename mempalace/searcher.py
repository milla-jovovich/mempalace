#!/usr/bin/env python3
"""
searcher.py — Find anything. Exact words.

Hybrid search: BM25 keyword matching + vector semantic similarity. The
drawer query is the floor — always runs — and closet hits add a rank-based
boost when they agree. Closets are a ranking *signal*, never a gate, so
weak closets (regex extraction on narrative content) can only help, never
hide drawers the direct path would have found.
"""

import hashlib
import json
import logging
import math
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from .palace import get_closets_collection, get_collection

# Closet pointer line format: "topic|entities|→drawer_id_a,drawer_id_b"
# Multiple lines may join with newlines inside one closet document.
_CLOSET_DRAWER_REF_RE = re.compile(r"→([\w,]+)")

logger = logging.getLogger("mempalace_mcp")


def _embed_query_text(collection: Any, text: str) -> list[float]:
    """Return query embedding vector from the collection's embedding function."""
    ef = getattr(collection, "_embedding_function", None)
    if ef is None:
        return []
    try:
        vecs = ef([text])
        if vecs and isinstance(vecs[0], (list, tuple)):
            return [float(x) for x in vecs[0]]
    except Exception as e:
        logger.debug("query embedding failed: %s", e)
    return []


def _chroma_rows_to_hits(
    docs: list,
    metas: list,
    dists: list,
    ids: list,
    from_expansion: bool,
    embeddings_row: Optional[list] = None,
) -> list[dict[str, Any]]:
    hits = []
    for i, (doc, meta, dist) in enumerate(zip(docs, metas, dists)):
        drawer_id = ids[i] if i < len(ids) else ""
        meta = meta or {}
        hit: dict[str, Any] = {
            "id": drawer_id,
            "metadata": meta,
            "text": doc,
            "wing": meta.get("wing", "unknown"),
            "room": meta.get("room", "unknown"),
            "source_file": Path(meta.get("source_file", "?")).name,
            "similarity": round(max(0.0, 1 - dist), 3),
            "distance": dist,
            "_from_expansion": from_expansion,
        }
        if embeddings_row is not None and i < len(embeddings_row):
            emb = embeddings_row[i]
            if emb is not None:
                if hasattr(emb, "tolist"):
                    emb = emb.tolist()
                if isinstance(emb, list):
                    hit["embedding"] = [float(x) for x in emb]
        hits.append(hit)
    return hits


class SearchError(Exception):
    """Raised when search cannot proceed (e.g. no palace found)."""


_TOKEN_RE = re.compile(r"\w{2,}", re.UNICODE)


def _first_or_empty(results: dict, key: str) -> list:
    """Return the first inner list of a ChromaDB query result, or [].

    ChromaDB returns shapes like ``{"documents": [["a", "b"]], ...}`` for a
    successful query, but ``{"documents": [], ...}`` (empty outer list) when
    the collection is empty or the filter excludes everything. Indexing
    ``[0]`` blindly raises IndexError in that case (issue #195).
    """
    outer = results.get(key)
    if not outer:
        return []
    return outer[0] or []


def _tokenize(text: str) -> list:
    """Lowercase + strip to alphanumeric tokens of length ≥ 2."""
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
    for doc, meta in zip(neighbors.get("documents") or [], neighbors.get("metadatas") or []):
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
        ids = all_meta.get("ids") or []
        total_drawers = len(ids) if ids else None
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

    docs = _first_or_empty(results, "documents")
    metas = _first_or_empty(results, "metadatas")
    dists = _first_or_empty(results, "distances")

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


def search_memories(  # noqa: C901
    query: str,
    palace_path: Optional[str] = None,
    wing: Optional[str] = None,
    room: Optional[str] = None,
    n_results: int = 5,
    max_distance: float = 0.0,
    include_archived: bool = False,
    time_decay: bool = True,
    synapse_ltp_enabled: Optional[bool] = None,
    synapse_tagging_enabled: Optional[bool] = None,
    synapse_association_enabled: Optional[bool] = None,
    synapse_ltp_window_days: Optional[int] = None,
    synapse_ltp_max_boost: Optional[float] = None,
    synapse_tagging_window_hours: Optional[int] = None,
    synapse_tagging_max_boost: Optional[float] = None,
    synapse_profile: Optional[str] = None,
    synapse_half_life_days: Optional[int] = None,
    synapse_association_max_boost: Optional[float] = None,
    synapse_association_coefficient: Optional[float] = None,
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
    from .config import MempalaceConfig

    cfg = MempalaceConfig()
    _pipeline_start = time.monotonic()
    if palace_path is None:
        palace_path = cfg.palace_path

    try:
        drawers_col = get_collection(palace_path, create=False)
    except Exception as e:
        logger.error("No palace found at %s: %s", palace_path, e)
        return {
            "error": "No palace found",
            "hint": "Run: mempalace init <dir> && mempalace mine <dir>",
        }

    where = build_where_filter(wing, room)

    if not include_archived and wing is None:
        aw = cfg.synapse_soft_archive_target_wing
        excl = {"wing": {"$ne": aw}}
        if where:
            where = {"$and": [where, excl]}
        else:
            where = excl

    include_cols = ["documents", "metadatas", "distances"]
    if cfg.synapse_enabled:
        include_cols.append("embeddings")

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
            "include": include_cols,
        }
        if where:
            dkwargs["where"] = where
        drawer_results = drawers_col.query(**dkwargs)
    except Exception as e:
        return {"error": f"Search error: {e}"}

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
    docs = _first_or_empty(drawer_results, "documents")
    metas = _first_or_empty(drawer_results, "metadatas")
    dists = _first_or_empty(drawer_results, "distances")
    ids_row = (drawer_results.get("ids") or [[]])[0] or []
    if len(ids_row) < len(docs):
        ids_row = list(ids_row) + [""] * (len(docs) - len(ids_row))
    for doc, meta, dist, drawer_id in zip(docs, metas, dists, ids_row):
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
        sim = round(max(0.0, 1 - effective_dist), 3)
        entry = {
            "id": drawer_id,
            "metadata": dict(meta),
            "text": doc,
            "wing": meta.get("wing", "unknown"),
            "room": meta.get("room", "unknown"),
            "source_file": Path(source).name if source else "?",
            "created_at": meta.get("filed_at", "unknown"),
            "similarity": sim,
            "original_similarity": sim,
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
        docs = source_drawers.get("documents") or []
        metas_ = source_drawers.get("metadatas") or []
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

    result: dict[str, Any] = {
        "query": query,
        "filters": {"wing": wing, "room": room},
        "total_before_filter": len(_first_or_empty(drawer_results, "documents")),
        "results": hits,
        "hits": hits,
    }
    # --- Synapse integration ---
    try:
        if cfg.synapse_enabled:
            from .synapse import SynapseDB
            from .synapse_profiles import (
                ProfileManager,
                compute_decay,
                global_merged_from_mempalace_config,
                hit_filed_age_days,
            )

            pm = ProfileManager(palace_path)
            per_query: dict[str, Any] = {}
            if synapse_half_life_days is not None:
                per_query["half_life_days"] = synapse_half_life_days
            if synapse_ltp_enabled is not None:
                per_query["ltp_enabled"] = synapse_ltp_enabled
            if synapse_ltp_window_days is not None:
                per_query["ltp_window_days"] = synapse_ltp_window_days
            if synapse_ltp_max_boost is not None:
                per_query["ltp_max_boost"] = synapse_ltp_max_boost
            if synapse_tagging_enabled is not None:
                per_query["tagging_enabled"] = synapse_tagging_enabled
            if synapse_tagging_window_hours is not None:
                per_query["tagging_window_hours"] = synapse_tagging_window_hours
            if synapse_tagging_max_boost is not None:
                per_query["tagging_max_boost"] = synapse_tagging_max_boost
            if synapse_association_enabled is not None:
                per_query["association_enabled"] = synapse_association_enabled
            if synapse_association_max_boost is not None:
                per_query["association_max_boost"] = synapse_association_max_boost
            if synapse_association_coefficient is not None:
                per_query["association_coefficient"] = synapse_association_coefficient

            profile = pm.resolve(
                synapse_profile,
                per_query_overrides=per_query or None,
                global_merged=global_merged_from_mempalace_config(cfg),
            )
            pd = profile.to_dict()

            result["synapse_requested_profile"] = synapse_profile
            result["synapse_profile_used"] = profile.name

            synapse_db = SynapseDB(palace_path)
            query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
            session_id = uuid.uuid4().hex[:16]
            total_candidates_in = 0

            query_embedding = _embed_query_text(drawers_col, query)

            expansion_metadata: dict[str, Any] = {"applied": False}
            expanded_terms: list[str] = []
            if pd.get("query_expansion_enabled", False):
                er = synapse_db.expand_query(
                    drawers_col,
                    query,
                    query_embedding,
                    max_expansions=int(pd.get("query_expansion_max_terms", 3)),
                    similarity_threshold=float(
                        pd.get("query_expansion_similarity_threshold", 0.65)
                    ),
                    lookback_days=int(pd.get("query_expansion_lookback_days", 60)),
                )
                expanded_terms = er.get("expansion_terms") or []
                boost = float(pd.get("query_expansion_boost", 0.7))
                expansion_metadata = {
                    "applied": True,
                    "original_query": query,
                    "similar_past_queries": er.get("similar_past_queries", []),
                    "expansion_terms": expanded_terms,
                    "expansion_boost": boost,
                }
            else:
                boost = float(pd.get("query_expansion_boost", 0.7))

            merged_by_id: dict[str, dict[str, Any]] = {}
            original_ids: set[str] = set()
            for h in hits:
                hid = h.get("id", "")
                merged_by_id[hid] = h
                if hid:
                    original_ids.add(hid)

            if expanded_terms:
                for term in expanded_terms:
                    eq = f"{query} {term}"
                    try:
                        qkwargs = {
                            "query_texts": [eq],
                            "n_results": n_results,
                            "include": include_cols,
                        }
                        if where:
                            qkwargs["where"] = where
                        exr = drawers_col.query(**qkwargs)
                        edocs = exr["documents"][0]
                        emetas = exr["metadatas"][0]
                        edists = exr["distances"][0]
                        eids = exr.get("ids", [[]])[0]
                        eer = exr.get("embeddings", [[]])[0] if cfg.synapse_enabled else None
                        exhits = _chroma_rows_to_hits(
                            edocs,
                            emetas,
                            edists,
                            eids,
                            from_expansion=True,
                            embeddings_row=eer,
                        )
                        for eh in exhits:
                            eid = eh.get("id", "")
                            if eid and eid not in merged_by_id:
                                merged_by_id[eid] = eh
                    except Exception as ex:
                        logger.warning("expansion query failed: %s", ex)

            result["hits"] = list(merged_by_id.values())
            total_candidates_in = len(merged_by_id)
            if expansion_metadata.get("applied"):
                expansion_metadata["results_from_original"] = len(original_ids)
                expansion_metadata["results_from_expansion"] = max(
                    0, len(merged_by_id) - len(original_ids)
                )
            result["synapse_query_expansion"] = expansion_metadata

            hit_drawer_ids = []
            for hit in result["hits"]:
                drawer_id = hit.get("metadata", {}).get("drawer_id", hit.get("id", ""))
                if drawer_id:
                    hit_drawer_ids.append(drawer_id)

            with synapse_db.connection() as conn:
                ltp_scores: dict[str, float] = {}
                if profile.ltp_enabled and hit_drawer_ids:
                    ltp_scores = synapse_db.get_ltp_scores_batch(
                        hit_drawer_ids,
                        window_days=profile.ltp_window_days,
                        max_boost=profile.ltp_max_boost,
                        conn=conn,
                    )

                assoc_scores: dict[str, float] = {}
                if profile.association_enabled and hit_drawer_ids:
                    assoc_scores = synapse_db.get_association_scores_batch(
                        hit_drawer_ids,
                        max_boost=profile.association_max_boost,
                        coefficient=profile.association_coefficient,
                        conn=conn,
                    )

                for hit in result["hits"]:
                    drawer_id = hit.get("metadata", {}).get("drawer_id", hit.get("id", ""))
                    filed_at = hit.get("metadata", {}).get("filed_at", None)
                    similarity = float(hit.get("original_similarity", hit.get("similarity", 0.0)))
                    age_days = hit_filed_age_days(filed_at)
                    decay = (
                        compute_decay(age_days, int(profile.half_life_days)) if time_decay else 1.0
                    )

                    ltp = ltp_scores.get(drawer_id, 1.0) if profile.ltp_enabled else 1.0
                    tagging = (
                        SynapseDB.calculate_tagging_boost(
                            filed_at,
                            window_hours=profile.tagging_window_hours,
                            max_boost=profile.tagging_max_boost,
                        )
                        if profile.tagging_enabled
                        else 1.0
                    )
                    association = (
                        assoc_scores.get(drawer_id, 1.0) if profile.association_enabled else 1.0
                    )

                    final_score = similarity * decay * ltp * association * tagging
                    if hit.get("_from_expansion"):
                        final_score *= boost

                    hit["synapse_score"] = final_score
                    hit["synapse_factors"] = {
                        "similarity": similarity,
                        "decay": decay,
                        "ltp": ltp,
                        "association": association,
                        "tagging": tagging,
                    }
                    hit["synapse_profile"] = profile.name

                result["hits"].sort(
                    key=lambda h: h.get("synapse_score", h.get("similarity", 0.0)),
                    reverse=True,
                )

                # Same drawer: prefer original (non-expansion) 窶・re-sort stable by
                # stripping expansion penalty when duplicate ids (merged_by_id already deduped)

                result["synapse_enabled"] = True
                result["synapse_profile"] = profile.to_dict()

                hits_after_score = result["hits"]

                # Phase 8 窶・Supersede
                if pd.get("supersede_filter_enabled", False):
                    sres = synapse_db.detect_superseded(
                        drawers_col,
                        [h.get("id") for h in hits_after_score if h.get("id")],
                        similarity_threshold=float(pd.get("supersede_similarity_threshold", 0.86)),
                        min_age_gap_days=int(pd.get("supersede_min_age_gap_days", 7)),
                        max_candidates=int(pd.get("supersede_max_candidates", 10)),
                    )
                    filt = synapse_db.apply_supersede_filter(
                        hits_after_score,
                        sres,
                        action=str(pd.get("supersede_action", "filter")),
                    )
                    hits_after_score = filt["results"]
                    result["synapse_supersede"] = filt["synapse_supersede"]
                else:
                    result["synapse_supersede"] = {"checked": False}

                # Phase 9 窶・Consolidation resolve
                consolidation_metadata: dict[str, Any] = {"applied": False}
                if pd.get("include_consolidated_summaries", True):
                    include_sources = pd.get("include_consolidated_sources", False)
                    consolidated_removed: list[str] = []
                    consolidated_sources_nested = 0

                    if include_sources:
                        source_groups: dict[str, list[dict[str, Any]]] = {}
                        non_consolidated_hits: list[dict[str, Any]] = []
                        for hit in hits_after_score:
                            meta = hit.get("metadata") or {}
                            st = meta.get("status", "active")
                            if st == "consolidated":
                                into = meta.get("consolidated_into") or ""
                                if into:
                                    consolidated_sources_nested += 1
                                    text = hit.get("text") or ""
                                    source_groups.setdefault(into, []).append(
                                        {
                                            "id": hit.get("id", ""),
                                            "title": meta.get("title", text[:50]),
                                            "date": meta.get(
                                                "created_at",
                                                meta.get("filed_at", ""),
                                            ),
                                            "content_preview": text[:200],
                                        }
                                    )
                                else:
                                    non_consolidated_hits.append(hit)
                            else:
                                non_consolidated_hits.append(hit)

                        present = {h.get("id") for h in non_consolidated_hits}
                        for cid in dict.fromkeys(list(source_groups.keys())):
                            if cid and cid not in present:
                                try:
                                    got = drawers_col.get(
                                        ids=[cid],
                                        include=["documents", "metadatas", "embeddings"],
                                    )
                                    if got.get("ids"):
                                        doc = (got.get("documents") or [""])[0]
                                        meta = (got.get("metadatas") or [{}])[0] or {}
                                        emb = (got.get("embeddings") or [None])[0]
                                        dist = 0.5
                                        nh = _chroma_rows_to_hits(
                                            [doc],
                                            [meta],
                                            [dist],
                                            [cid],
                                            from_expansion=False,
                                            embeddings_row=[emb] if emb else None,
                                        )[0]
                                        nh["similarity"] = 0.5
                                        nh["synapse_score"] = 0.5
                                        non_consolidated_hits.append(nh)
                                        present.add(cid)
                                except Exception:
                                    pass

                        for hit in non_consolidated_hits:
                            meta = hit.get("metadata") or {}
                            if meta.get("status") == "consolidated_summary":
                                cid = hit.get("id", "")
                                if cid in source_groups:
                                    hit["synapse_consolidation"] = {
                                        "is_consolidated": True,
                                        "source_count": len(source_groups[cid]),
                                        "sources": source_groups[cid],
                                    }
                                elif meta.get("source_drawers"):
                                    try:
                                        sids = json.loads(meta["source_drawers"])
                                        if isinstance(sids, list):
                                            hit["synapse_consolidation"] = {
                                                "is_consolidated": True,
                                                "source_count": len(sids),
                                                "sources": [{"id": sid} for sid in sids],
                                            }
                                    except (json.JSONDecodeError, TypeError):
                                        pass

                        hits_after_score = non_consolidated_hits
                        consolidation_metadata = {
                            "applied": True,
                            "consolidated_sources_hidden": 0,
                            "consolidated_sources_nested": consolidated_sources_nested,
                            "include_sources_as_metadata": True,
                            "include_sources": True,
                        }
                    else:
                        new_hits: list[dict[str, Any]] = []
                        to_fetch_summary: list[str] = []
                        for hit in hits_after_score:
                            meta = hit.get("metadata") or {}
                            if meta.get("status") == "consolidated":
                                consolidated_removed.append(hit.get("id", ""))
                                into = meta.get("consolidated_into")
                                if into:
                                    to_fetch_summary.append(str(into))
                            else:
                                new_hits.append(hit)

                        present = {h.get("id") for h in new_hits}
                        for cid in dict.fromkeys(to_fetch_summary):
                            if cid and cid not in present:
                                try:
                                    got = drawers_col.get(
                                        ids=[cid],
                                        include=["documents", "metadatas", "embeddings"],
                                    )
                                    if got.get("ids"):
                                        doc = (got.get("documents") or [""])[0]
                                        meta = (got.get("metadatas") or [{}])[0] or {}
                                        emb = (got.get("embeddings") or [None])[0]
                                        dist = 0.5
                                        nh = _chroma_rows_to_hits(
                                            [doc],
                                            [meta],
                                            [dist],
                                            [cid],
                                            from_expansion=False,
                                            embeddings_row=[emb] if emb else None,
                                        )[0]
                                        nh["similarity"] = 0.5
                                        nh["synapse_score"] = 0.5
                                        new_hits.append(nh)
                                        present.add(cid)
                                except Exception:
                                    pass

                        hits_after_score = new_hits
                        consolidation_metadata = {
                            "applied": True,
                            "consolidated_sources_hidden": len(consolidated_removed),
                            "consolidated_sources_nested": 0,
                            "include_sources_as_metadata": False,
                            "include_sources": False,
                        }
                result["synapse_consolidation"] = consolidation_metadata

                # Phase 5 窶・MMR
                if pd.get("mmr_enabled", False):
                    mmr_out = synapse_db.apply_mmr(
                        hits_after_score,
                        query_embedding,
                        lambda_param=float(pd.get("mmr_lambda", 0.7)),
                        final_k=int(pd.get("mmr_final_k", 5)),
                    )
                    hits_after_score = mmr_out["results"]
                    result["synapse_mmr"] = mmr_out["mmr_metadata"]
                else:
                    result["synapse_mmr"] = {"applied": False}

                for h in hits_after_score:
                    h.pop("_from_expansion", None)

                result["hits"] = hits_after_score
                result["results"] = hits_after_score

                phases_applied: list[str] = []
                phases_skipped: list[str] = []
                if result.get("synapse_query_expansion", {}).get("applied"):
                    phases_applied.append("query_expansion")
                else:
                    phases_skipped.append("query_expansion")

                ss = result.get("synapse_supersede") or {}
                if ss.get("checked"):
                    phases_applied.append("supersede_" + str(ss.get("action", "filter")))
                else:
                    phases_skipped.append("supersede")

                sc = result.get("synapse_consolidation") or {}
                if sc.get("applied"):
                    phases_applied.append("consolidation")
                else:
                    phases_skipped.append("consolidation")

                sm = result.get("synapse_mmr") or {}
                if sm.get("applied"):
                    phases_applied.append("mmr")
                else:
                    phases_skipped.append("mmr")

                result["synapse_pipeline"] = {
                    "phases_applied": phases_applied,
                    "phases_skipped": phases_skipped,
                    "total_candidates_in": total_candidates_in,
                    "total_results_out": len(hits_after_score),
                    "profile_used": result.get("synapse_profile_used", "default"),
                    "elapsed_ms": round((time.monotonic() - _pipeline_start) * 1000, 1),
                }

                if cfg.synapse_log_retrievals:
                    log_ids = [
                        hit.get("metadata", {}).get("drawer_id", hit.get("id", ""))
                        for hit in hits_after_score
                    ]
                    log_ids = [x for x in log_ids if x]
                    if log_ids:
                        try:
                            synapse_db.log_retrieval(log_ids, query_hash, session_id, conn=conn)
                        except Exception as e:
                            logger.warning("Synapse log_retrieval failed (non-fatal): %s", e)

            try:
                synapse_db.log_query(
                    query,
                    query_embedding,
                    [h.get("id", "") for h in result["hits"]],
                    [
                        float(h.get("synapse_score", h.get("similarity", 0.0)))
                        for h in result["hits"]
                    ],
                )
            except Exception:
                pass
        else:
            result["synapse_enabled"] = False
            result["synapse_query_expansion"] = {"applied": False}
            result["synapse_supersede"] = {"checked": False}
            result["synapse_consolidation"] = {"applied": False}
            result["synapse_mmr"] = {"applied": False}
    except Exception as e:
        logger.warning("Synapse scoring skipped: %s", e)
        result["synapse_enabled"] = False
        result["synapse_query_expansion"] = {"applied": False}
        result["synapse_supersede"] = {"checked": False}
        result["synapse_consolidation"] = {"applied": False}
        result["synapse_mmr"] = {"applied": False}

    if not result.get("synapse_enabled"):
        result.pop("synapse_pipeline", None)

    return result
