#!/usr/bin/env python3
"""
searcher.py — Find anything. Exact words.

Semantic search against the palace.
Returns verbatim text — the actual words, never summaries.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from .palace import get_collection, get_support_collection
from .retrieval_signals import (
    HALL_GENERAL,
    HALL_PREFERENCES,
    classify_question_halls,
    is_assistant_reference_query,
)

logger = logging.getLogger("mempalace_mcp")

# The product default now uses persisted preference-support docs when available.
# This keeps raw semantic search available for debugging while letting the app
# benefit from the first mining-time retrieval hints we have productized.
DEFAULT_SEARCH_STRATEGY = "hybrid_v3"
_STRATEGY_ALIASES = {
    # "hybrid_v2" shipped first, but "raw_v2" is a clearer public name: it is
    # still raw verbatim storage/retrieval, just with a better local reranker.
    "hybrid_v2": "raw_v2",
}

_STOP_WORDS = {
    "what",
    "when",
    "where",
    "who",
    "how",
    "which",
    "did",
    "do",
    "was",
    "were",
    "have",
    "has",
    "had",
    "is",
    "are",
    "the",
    "a",
    "an",
    "my",
    "me",
    "i",
    "you",
    "your",
    "their",
    "it",
    "its",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "by",
    "from",
    "ago",
    "last",
    "that",
    "this",
    "there",
    "about",
    "get",
    "got",
    "give",
    "gave",
    "buy",
    "bought",
    "made",
    "make",
}

_MONTH_NAMES = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


class SearchError(Exception):
    """Raised when search cannot proceed (e.g. no palace found)."""


def build_where_filter(
    wing: str = None,
    room: str = None,
    source_file: str = None,
    hall: str = None,
    support_kind: str = None,
) -> dict:
    """Build a ChromaDB metadata filter from the active search scope."""
    clauses = []
    if wing:
        clauses.append({"wing": wing})
    if room:
        clauses.append({"room": room})
    if source_file:
        clauses.append({"source_file": source_file})
    if hall:
        clauses.append({"hall": hall})
    if support_kind:
        clauses.append({"support_kind": support_kind})

    if not clauses:
        return {}
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _append_where_clause(where: dict, clause: dict) -> dict:
    """Append one extra clause to an existing where filter.

    Search strategies frequently start with the caller's wing/room scope and
    then add a narrower constraint such as `hall=...` or `source_file=...`.
    Keeping that composition in one helper prevents subtle `$and` nesting bugs.
    """
    if not where:
        return clause
    if "$and" in where:
        return {"$and": list(where["$and"]) + [clause]}
    return {"$and": [where, clause]}


def _extract_keywords(text: str) -> list[str]:
    """Extract lightweight lexical anchors for reranking."""
    words = re.findall(r"\b[a-z]{3,}\b", text.lower())
    return [word for word in words if word not in _STOP_WORDS]


def _keyword_overlap(query_keywords: list[str], doc_text: str) -> float:
    """Return the fraction of query keywords present in a document."""
    if not query_keywords:
        return 0.0
    doc_lower = doc_text.lower()
    hits = sum(1 for keyword in query_keywords if keyword in doc_lower)
    return hits / len(query_keywords)


def _parse_time_offset_days(query: str) -> tuple[int, int] | None:
    """Parse relative-time language into a target offset and tolerance window."""
    query_lower = query.lower()
    patterns = [
        (r"(\d+)\s+days?\s+ago", lambda m: (int(m.group(1)), 2)),
        (r"a\s+couple\s+(?:of\s+)?days?\s+ago", lambda m: (2, 2)),
        (r"yesterday", lambda m: (1, 1)),
        (r"a\s+week\s+ago", lambda m: (7, 3)),
        (r"(\d+)\s+weeks?\s+ago", lambda m: (int(m.group(1)) * 7, 5)),
        (r"last\s+week", lambda m: (7, 3)),
        (r"a\s+month\s+ago", lambda m: (30, 7)),
        (r"(\d+)\s+months?\s+ago", lambda m: (int(m.group(1)) * 30, 10)),
        (r"last\s+month", lambda m: (30, 7)),
        (r"last\s+year", lambda m: (365, 30)),
        (r"a\s+year\s+ago", lambda m: (365, 30)),
        (r"recently", lambda m: (14, 14)),
    ]
    for pattern, extractor in patterns:
        match = re.search(pattern, query_lower)
        if match:
            return extractor(match)
    return None


def _parse_datetime_value(value) -> datetime | None:
    """Best-effort parser for metadata values that may contain a timestamp."""
    if value is None or value == "":
        return None

    if isinstance(value, datetime):
        return value

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value)
        except (OverflowError, OSError, ValueError):
            return None

    text = str(value).strip()
    if not text:
        return None

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y_%m_%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    return None


def _parse_datetime_from_source_file(source_file: str) -> datetime | None:
    """Extract a date-like value from transcript-style filenames when possible."""
    if not source_file:
        return None

    source_name = Path(source_file).name

    iso_match = re.search(r"(20\d{2})[-_](\d{2})[-_](\d{2})", source_name)
    if iso_match:
        year, month, day = map(int, iso_match.groups())
        try:
            return datetime(year, month, day)
        except ValueError:
            return None

    month_match = re.search(
        r"(?i)(january|february|march|april|may|june|july|august|september|october|november|december)"
        r"[_-](\d{1,2})[_,-](\d{4})",
        source_name,
    )
    if month_match:
        month_name, day, year = month_match.groups()
        try:
            return datetime(int(year), _MONTH_NAMES[month_name.lower()], int(day))
        except ValueError:
            return None

    return None


def _extract_candidate_datetime(meta: dict) -> datetime | None:
    """Read the most trustworthy date-like signal from drawer metadata."""
    for key in (
        "session_timestamp",
        "source_timestamp",
        "timestamp",
        "date",
        "source_mtime",
        "filed_at",
    ):
        parsed = _parse_datetime_value(meta.get(key))
        if parsed is not None:
            return parsed

    return _parse_datetime_from_source_file(meta.get("source_file", ""))


def _apply_temporal_boost(raw_distance: float, meta: dict, query: str) -> tuple[float, float]:
    """Apply a time-aware distance reduction when metadata supports it."""
    offset = _parse_time_offset_days(query)
    if not offset:
        return raw_distance, 0.0

    candidate_time = _extract_candidate_datetime(meta)
    if candidate_time is None:
        return raw_distance, 0.0

    days_back, tolerance = offset
    target_date = datetime.now() - timedelta(days=days_back)
    delta_days = abs((candidate_time.date() - target_date.date()).days)

    if delta_days <= tolerance:
        boost = 0.40
    elif delta_days <= tolerance * 3:
        boost = 0.40 * (1.0 - (delta_days - tolerance) / (tolerance * 2))
    else:
        boost = 0.0

    return raw_distance * (1.0 - boost), boost


def _query_rows(
    collection,
    query: str,
    n_results: int,
    where: dict | None = None,
    retrieval_source: str = "raw",
) -> list[dict]:
    """Run one Chroma query and normalize the result shape for reranking."""
    kwargs = {
        "query_texts": [query],
        "n_results": n_results,
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        kwargs["where"] = where

    results = collection.query(**kwargs)
    return [
        {
            "id": row_id,
            "display_id": row_id,
            "text": doc,
            "meta": meta or {},
            "distance": dist,
            "retrieval_source": retrieval_source,
            "support_kind": None,
        }
        for row_id, doc, meta, dist in zip(
            results["ids"][0],
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        )
    ]


def _get_optional_support_collection(palace_path: str):
    """Return the support collection when it exists, otherwise None.

    Older palaces do not have this collection yet. Search strategies should
    degrade gracefully to raw/hybrid behavior instead of forcing a migration.
    """
    try:
        return get_support_collection(palace_path, create=False)
    except Exception:
        return None


def _map_support_rows_to_raw(raw_collection, support_rows: list[dict]) -> list[dict]:
    """Map support hits back to their raw parent drawers.

    Support docs are only a retrieval aid. Every displayed result must still be
    the original verbatim drawer, so we batch-load the parent raw docs and keep
    the support hit's distance as the retrieval signal.
    """
    parent_ids = []
    for row in support_rows:
        parent_id = row["meta"].get("parent_drawer_id")
        if parent_id and parent_id not in parent_ids:
            parent_ids.append(parent_id)

    if not parent_ids:
        return []

    parent_rows = raw_collection.get(ids=parent_ids, include=["documents", "metadatas"])
    parent_map = {}
    for row_id, doc, meta in zip(
        parent_rows.get("ids", []),
        parent_rows.get("documents", []),
        parent_rows.get("metadatas", []),
    ):
        parent_map[row_id] = {"text": doc, "meta": meta or {}}

    mapped = []
    for row in support_rows:
        parent_id = row["meta"].get("parent_drawer_id")
        parent = parent_map.get(parent_id)
        if parent is None:
            continue
        mapped.append(
            {
                "id": parent_id,
                "display_id": parent_id,
                "text": parent["text"],
                "meta": parent["meta"],
                "distance": row["distance"],
                "retrieval_source": row["retrieval_source"],
                "support_kind": row["meta"].get("support_kind"),
            }
        )
    return mapped


def _query_support_rows(
    raw_collection,
    support_collection,
    query: str,
    n_results: int,
    where: dict,
    support_kind: str | None = None,
    retrieval_source: str = "support",
) -> list[dict]:
    """Query the support collection and map hits back to raw drawers."""
    if support_collection is None:
        return []

    support_where = where
    if support_kind is not None:
        support_where = _append_where_clause(where, {"support_kind": support_kind})

    support_rows = _query_rows(
        support_collection,
        query,
        n_results=n_results,
        where=support_where,
        retrieval_source=retrieval_source,
    )
    return _map_support_rows_to_raw(raw_collection, support_rows)


def _assistant_second_pass(raw_collection, query: str, where: dict, seed_rows: list[dict]) -> list[dict]:
    """Expand assistant-reference queries within the top transcript families."""
    if not is_assistant_reference_query(query):
        return []

    scoped_results = []
    seen_source_files = set()

    for row in seed_rows:
        source_file = row["meta"].get("source_file")
        if not source_file or source_file in seen_source_files:
            continue
        seen_source_files.add(source_file)

        scoped_where = _append_where_clause(where, {"source_file": source_file})
        scoped_results.extend(
            _query_rows(
                raw_collection,
                query,
                n_results=10,
                where=scoped_where,
                retrieval_source="raw_assistant_pass",
            )
        )
        if len(seen_source_files) >= 3:
            break

    return scoped_results


def _score_variants(variants: list[dict], query: str, support_bonus: bool = False) -> list[dict]:
    """Apply lexical and temporal reranking to a set of candidate variants."""
    keywords = _extract_keywords(query)
    scored = []
    for variant in variants:
        overlap = _keyword_overlap(keywords, variant["text"])
        rank_distance = variant["distance"] * (1.0 - 0.30 * overlap)
        rank_distance, temporal_boost = _apply_temporal_boost(rank_distance, variant["meta"], query)

        support_boost = 0.0
        if support_bonus and variant["retrieval_source"].startswith("support"):
            # The support doc is already a distilled preference signal, so a
            # support hit is usually stronger evidence than a generic raw hit at
            # the same distance.
            rank_distance *= 0.80
            support_boost = 0.20

        variant = dict(variant)
        variant["rank_distance"] = rank_distance
        variant["keyword_overlap"] = overlap
        variant["temporal_boost"] = temporal_boost
        variant["support_boost"] = support_boost
        variant["hall_boost"] = 0.0
        variant["validation_boost"] = 0.0
        scored.append(variant)
    return scored


def _consolidate_ranked_rows(variants: list[dict]) -> list[dict]:
    """Keep the best-ranked variant for each displayed raw drawer."""
    best_by_display_id = {}
    for variant in variants:
        current = best_by_display_id.get(variant["display_id"])
        if current is None or (
            variant["rank_distance"],
            variant["distance"],
            variant["display_id"],
        ) < (
            current["rank_distance"],
            current["distance"],
            current["display_id"],
        ):
            best_by_display_id[variant["display_id"]] = variant

    rows = list(best_by_display_id.values())
    rows.sort(key=lambda row: (row["rank_distance"], row["distance"], row["display_id"]))
    return rows


def _search_raw(raw_collection, query: str, where: dict, n_results: int) -> list[dict]:
    """Baseline semantic search: one query, no reranking."""
    rows = _query_rows(raw_collection, query, n_results=n_results, where=where)
    for row in rows:
        row["rank_distance"] = row["distance"]
        row["keyword_overlap"] = 0.0
        row["temporal_boost"] = 0.0
        row["support_boost"] = 0.0
        row["hall_boost"] = 0.0
        row["validation_boost"] = 0.0
    return rows


def _search_hybrid_v2(raw_collection, query: str, where: dict, n_results: int) -> list[dict]:
    """Raw_v2 retrieval: semantic search plus lexical and temporal reranking."""
    candidate_pool = max(n_results, 50)
    seed_rows = _query_rows(raw_collection, query, n_results=candidate_pool, where=where)
    variants = seed_rows + _assistant_second_pass(raw_collection, query, where, seed_rows)
    return _consolidate_ranked_rows(_score_variants(variants, query, support_bonus=False))


def _search_hybrid_v3(
    raw_collection,
    support_collection,
    query: str,
    where: dict,
    n_results: int,
) -> list[dict]:
    """Hybrid_v2 plus persisted preference-support docs from mining time."""
    candidate_pool = max(n_results, 50)
    seed_rows = _query_rows(raw_collection, query, n_results=candidate_pool, where=where)
    variants = seed_rows + _assistant_second_pass(raw_collection, query, where, seed_rows)

    # Support docs are only useful for preference-style questions. Restricting
    # them here keeps hybrid_v3 additive: we get the vocabulary-bridge benefit
    # without letting preference helpers pollute unrelated fact/event searches.
    if HALL_PREFERENCES in classify_question_halls(query):
        variants.extend(
            _query_support_rows(
                raw_collection,
                support_collection,
                query,
                n_results=min(candidate_pool, 30),
                where=where,
                support_kind="preference",
                retrieval_source="support_preference",
            )
        )

    return _consolidate_ranked_rows(_score_variants(variants, query, support_bonus=True))


def _search_palace(
    raw_collection,
    support_collection,
    query: str,
    where: dict,
    n_results: int,
) -> list[dict]:
    """Palace navigation with persisted halls and support docs.

    This mirrors the benchmark's productizable palace ideas:
    1. Infer the likely hall from the question.
    2. Do a tight hall-specific validation pass.
    3. Run a full search, but boost hall-matching and hall-validated results.
    4. Let preference-support docs participate when the query looks like a
       preference or concern question.
    """
    target_halls = classify_question_halls(query)
    primary_hall = target_halls[0]
    candidate_pool = max(n_results, 50)
    hall_validated_ids = set()

    pass1_variants = []
    if primary_hall != HALL_GENERAL:
        hall_where = _append_where_clause(where, {"hall": primary_hall})
        pass1_variants.extend(
            _query_rows(
                raw_collection,
                query,
                n_results=min(candidate_pool, 10),
                where=hall_where,
                retrieval_source="raw_hall_pass",
            )
        )
        if primary_hall == HALL_PREFERENCES:
            pass1_variants.extend(
                _query_support_rows(
                    raw_collection,
                    support_collection,
                    query,
                    n_results=10,
                    where=hall_where,
                    support_kind="preference",
                    retrieval_source="support_preference_hall_pass",
                )
            )
        for variant in pass1_variants:
            hall_validated_ids.add(variant["display_id"])

    full_variants = _query_rows(
        raw_collection,
        query,
        n_results=candidate_pool,
        where=where,
        retrieval_source="raw",
    )
    full_variants.extend(_assistant_second_pass(raw_collection, query, where, full_variants))
    full_variants.extend(pass1_variants)

    if HALL_PREFERENCES in target_halls:
        full_variants.extend(
            _query_support_rows(
                raw_collection,
                support_collection,
                query,
                n_results=min(candidate_pool, 30),
                where=where,
                support_kind="preference",
                retrieval_source="support_preference",
            )
        )

    scored = _score_variants(full_variants, query, support_bonus=True)
    for variant in scored:
        meta_hall = variant["meta"].get("hall")
        hall_boost = 0.0
        validation_boost = 0.0

        if meta_hall == primary_hall and primary_hall != HALL_GENERAL:
            variant["rank_distance"] *= 0.75
            hall_boost = 0.25
        elif meta_hall in target_halls and meta_hall != HALL_GENERAL:
            variant["rank_distance"] *= 0.90
            hall_boost = 0.10

        if variant["display_id"] in hall_validated_ids:
            variant["rank_distance"] *= 0.85
            validation_boost = 0.15

        variant["hall_boost"] = hall_boost
        variant["validation_boost"] = validation_boost

    return _consolidate_ranked_rows(scored)


def _run_search_strategy(
    raw_collection,
    support_collection,
    query: str,
    where: dict,
    n_results: int,
    strategy: str,
) -> list[dict]:
    """Dispatch to the selected retrieval strategy."""
    normalized = _normalize_strategy_name(strategy)
    if normalized == "raw":
        return _search_raw(raw_collection, query, where, n_results)
    if normalized == "raw_v2":
        return _search_hybrid_v2(raw_collection, query, where, n_results)
    if normalized == "hybrid_v3":
        return _search_hybrid_v3(raw_collection, support_collection, query, where, n_results)
    if normalized == "palace":
        return _search_palace(raw_collection, support_collection, query, where, n_results)
    raise ValueError(f"Unknown search strategy: {strategy}")


def _normalize_strategy_name(strategy: str | None) -> str:
    """Return the canonical strategy name used for execution and reporting.

    The CLI, MCP server, and tests all need one stable string in results even
    when callers omit the argument or use different casing. Centralizing that
    normalization avoids subtle drift between "executed strategy" and
    "reported strategy".
    """
    normalized = (strategy or DEFAULT_SEARCH_STRATEGY).lower()
    return _STRATEGY_ALIASES.get(normalized, normalized)


def search(
    query: str,
    palace_path: str,
    wing: str = None,
    room: str = None,
    n_results: int = 5,
    strategy: str = DEFAULT_SEARCH_STRATEGY,
):
    """Search the palace and print verbatim results."""
    normalized_strategy = _normalize_strategy_name(strategy)
    try:
        raw_collection = get_collection(palace_path, create=False)
    except Exception:
        print(f"\n  No palace found at {palace_path}")
        print("  Run: mempalace init <dir> then mempalace mine <dir>")
        raise SearchError(f"No palace found at {palace_path}")

    support_collection = _get_optional_support_collection(palace_path)
    where = build_where_filter(wing, room)

    try:
        rows = _run_search_strategy(
            raw_collection,
            support_collection,
            query=query,
            where=where,
            n_results=n_results,
            strategy=normalized_strategy,
        )
    except Exception as e:
        print(f"\n  Search error: {e}")
        raise SearchError(f"Search error: {e}") from e

    rows = rows[:n_results]
    if not rows:
        print(f'\n  No results found for: "{query}"')
        return

    print(f"\n{'=' * 60}")
    print(f'  Results for: "{query}"')
    print(f"  Strategy: {normalized_strategy}")
    if wing:
        print(f"  Wing: {wing}")
    if room:
        print(f"  Room: {room}")
    print(f"{'=' * 60}\n")

    for i, row in enumerate(rows, 1):
        doc = row["text"]
        meta = row["meta"]
        dist = row["distance"]
        similarity = round(max(0.0, 1 - dist), 3)
        source = Path(meta.get("source_file", "?")).name
        wing_name = meta.get("wing", "?")
        room_name = meta.get("room", "?")

        print(f"  [{i}] {wing_name} / {room_name}")
        print(f"      Source: {source}")
        print(f"      Match:  {similarity}")
        if meta.get("hall"):
            print(f"      Hall:   {meta.get('hall')}")
        if row["retrieval_source"] != "raw":
            print(f"      Via:    {row['retrieval_source']}")
        print()
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
    strategy: str = DEFAULT_SEARCH_STRATEGY,
) -> dict:
    """Programmatic search — returns a dict instead of printing."""
    normalized_strategy = _normalize_strategy_name(strategy)
    try:
        raw_collection = get_collection(palace_path, create=False)
    except Exception as e:
        logger.error("No palace found at %s: %s", palace_path, e)
        return {
            "error": "No palace found",
            "hint": "Run: mempalace init <dir> && mempalace mine <dir>",
        }

    support_collection = _get_optional_support_collection(palace_path)
    where = build_where_filter(wing, room)

    try:
        rows = _run_search_strategy(
            raw_collection,
            support_collection,
            query=query,
            where=where,
            n_results=n_results,
            strategy=normalized_strategy,
        )
    except Exception as e:
        return {"error": f"Search error: {e}"}

    hits = []
    for row in rows:
        doc = row["text"]
        meta = row["meta"]
        dist = row["distance"]
        if max_distance > 0.0 and dist > max_distance:
            continue

        hit = {
            "text": doc,
            "wing": meta.get("wing", "unknown"),
            "room": meta.get("room", "unknown"),
            "hall": meta.get("hall", "unknown"),
            "source_file": Path(meta.get("source_file", "?")).name,
            "similarity": round(max(0.0, 1 - dist), 3),
            "distance": round(dist, 4),
            "retrieval_source": row["retrieval_source"],
        }
        if normalized_strategy != "raw":
            hit["rank_distance"] = round(row["rank_distance"], 4)
            hit["keyword_overlap"] = round(row["keyword_overlap"], 3)
            hit["temporal_boost"] = round(row["temporal_boost"], 3)
            hit["support_boost"] = round(row["support_boost"], 3)
            hit["hall_boost"] = round(row["hall_boost"], 3)
            hit["validation_boost"] = round(row["validation_boost"], 3)
        hits.append(hit)
        if len(hits) >= n_results:
            break

    return {
        "query": query,
        "strategy": normalized_strategy,
        "filters": {"wing": wing, "room": room},
        "total_before_filter": len(rows),
        "results": hits,
    }
