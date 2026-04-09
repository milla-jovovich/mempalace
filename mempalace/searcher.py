#!/usr/bin/env python3
"""
searcher.py — Find anything. Exact words.

Semantic search against the palace.
Returns verbatim text — the actual words, never summaries.
"""

import hashlib
import logging
import uuid
from pathlib import Path

import chromadb

logger = logging.getLogger("mempalace_mcp")


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
    query: str, palace_path: str, wing: str = None, room: str = None, n_results: int = 5
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
    ids = results.get("ids", [[]])[0]

    hits = []
    for i, (doc, meta, dist) in enumerate(zip(docs, metas, dists)):
        drawer_id = ids[i] if i < len(ids) else ""
        meta = meta or {}
        hits.append(
            {
                "id": drawer_id,
                "metadata": meta,
                "text": doc,
                "wing": meta.get("wing", "unknown"),
                "room": meta.get("room", "unknown"),
                "source_file": Path(meta.get("source_file", "?")).name,
                "similarity": round(1 - dist, 3),
            }
        )

    result = {
        "query": query,
        "filters": {"wing": wing, "room": room},
        "results": hits,
        "hits": hits,
    }

    # --- Synapse integration ---
    try:
        from .config import MempalaceConfig

        cfg = MempalaceConfig()
        if cfg.synapse_enabled:
            from .synapse import SynapseDB

            synapse_db = SynapseDB(palace_path)
            query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
            session_id = uuid.uuid4().hex[:16]

            hit_drawer_ids = []
            for hit in result["hits"]:
                drawer_id = hit.get("metadata", {}).get("drawer_id", hit.get("id", ""))
                if drawer_id:
                    hit_drawer_ids.append(drawer_id)

            ltp_scores = {}
            if cfg.synapse_ltp_enabled:
                ltp_scores = synapse_db.get_ltp_scores_batch(
                    hit_drawer_ids,
                    window_days=cfg.synapse_ltp_window_days,
                    max_boost=cfg.synapse_ltp_max_boost,
                )

            for hit in result["hits"]:
                drawer_id = hit.get("metadata", {}).get("drawer_id", hit.get("id", ""))
                filed_at = hit.get("metadata", {}).get("filed_at", None)
                similarity = hit.get("original_similarity", hit.get("similarity", 0.0))
                decay = hit.get("decay", 1.0)

                ltp = ltp_scores.get(drawer_id, 1.0) if cfg.synapse_ltp_enabled else 1.0
                tagging = (
                    SynapseDB.calculate_tagging_boost(
                        filed_at,
                        cfg.synapse_tagging_window_hours,
                        cfg.synapse_tagging_max_boost,
                    )
                    if cfg.synapse_tagging_enabled
                    else 1.0
                )
                association = 1.0  # Phase 2: cfg.synapse_association_enabled

                final_score = similarity * decay * ltp * association * tagging

                hit["synapse_score"] = final_score
                hit["synapse_factors"] = {
                    "ltp": ltp,
                    "association": association,
                    "tagging": tagging,
                }

            result["hits"].sort(key=lambda h: h.get("synapse_score", 0.0), reverse=True)
            result["synapse_enabled"] = True

            if cfg.synapse_log_retrievals:
                synapse_db.log_retrieval(hit_drawer_ids, query_hash, session_id)
        else:
            result["synapse_enabled"] = False
    except Exception as e:
        logger.warning("Synapse scoring skipped: %s", e)
        result["synapse_enabled"] = False

    return result
