#!/usr/bin/env python3
"""
reranker.py — Post-retrieval reranking pipeline for MemPalace search
====================================================================

Applies configurable scoring adjustments after ChromaDB semantic search:

  Stage 1: Weibull decay        — time-based relevance decay
  Stage 2: Keyword boost        — query keyword overlap scoring
  Stage 3: Importance boost     — emotional_weight metadata boost
  Stage 4: LLM rerank           — optional Anthropic API reranking

Each stage is a pure function: (hits, query, config) -> hits.
All stages operate on a unified `fused_distance` field.
When no stages are enabled, the pipeline is an identity function.
"""

import json
import logging
import math
import os
import re
from datetime import datetime

logger = logging.getLogger("mempalace_mcp")


# ---------------------------------------------------------------------------
# Weibull decay
# ---------------------------------------------------------------------------


def weibull_survival(age_days: float, k: float = 1.5, lam: float = 90.0) -> float:
    """Weibull survival function S(t) = exp(-(t/lambda)^k).

    Args:
        age_days: Age of the memory in days.
        k: Shape parameter. k>1 means increasing decay rate over time.
        lam: Scale parameter (characteristic life) in days.

    Returns:
        Survival probability between 0 and 1.
    """
    if age_days <= 0 or lam <= 0:
        return 1.0
    return math.exp(-((age_days / lam) ** k))


def apply_decay(similarity: float, age_days: float, k: float, lam: float, floor: float) -> float:
    """Apply Weibull decay to a similarity score.

    Returns adjusted similarity that never drops below similarity * floor.
    """
    s = weibull_survival(age_days, k, lam)
    return similarity * (floor + (1.0 - floor) * s)


def _parse_age_days(filed_at) -> float:
    """Parse filed_at metadata into age in days. Returns 0 if unparseable."""
    if not filed_at:
        return 0.0
    try:
        filed_dt = datetime.fromisoformat(str(filed_at))
        delta = datetime.now() - filed_dt
        return max(0.0, delta.total_seconds() / 86400)
    except (ValueError, TypeError):
        return 0.0


# ---------------------------------------------------------------------------
# Keyword extraction and overlap
# ---------------------------------------------------------------------------

STOP_WORDS = {
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


def extract_keywords(text: str) -> list:
    """Extract meaningful keywords from text, stripping stop words."""
    words = re.findall(r"\b[a-z]{3,}\b", text.lower())
    return [w for w in words if w not in STOP_WORDS]


def keyword_overlap(query_keywords: list, doc_text: str) -> float:
    """Fraction of query keywords found in document text (0.0 to 1.0)."""
    if not query_keywords:
        return 0.0
    doc_lower = doc_text.lower()
    hits = sum(1 for kw in query_keywords if kw in doc_lower)
    return hits / len(query_keywords)


# ---------------------------------------------------------------------------
# Rerank stages
# ---------------------------------------------------------------------------


def stage_weibull_decay(hits: list, query: str, config: dict) -> list:
    """Apply Weibull time-decay to fused_distance.

    Config keys (under rerank.weibull_decay):
        k:     shape parameter (default 1.5)
        lambda: scale parameter in days (default 90)
        floor: minimum retention factor (default 0.3)
    """
    decay_cfg = config.get("weibull_decay", {})
    k = float(decay_cfg.get("k", 1.5))
    lam = float(decay_cfg.get("lambda", 90))
    floor = float(decay_cfg.get("floor", 0.3))

    for hit in hits:
        age = _parse_age_days(hit.get("filed_at"))
        if age <= 0:
            continue
        s = weibull_survival(age, k, lam)
        decay_factor = floor + (1.0 - floor) * s
        # Lower fused_distance for newer items (multiply distance by inverse of decay)
        # decay_factor is 1.0 for new, approaches floor for old
        # We want newer items to have LOWER distance, so divide distance by decay_factor
        # But to keep the formula intuitive: increase distance for older items
        if decay_factor > 0:
            hit["fused_distance"] = hit["fused_distance"] / decay_factor

    return hits


def stage_keyword_boost(hits: list, query: str, config: dict) -> list:
    """Apply keyword overlap boost to fused_distance.

    Config keys (under rerank.keyword_boost):
        weight: max distance reduction factor (default 0.30)
    """
    boost_cfg = config.get("keyword_boost", {})
    weight = float(boost_cfg.get("weight", 0.30))

    query_kws = extract_keywords(query)
    if not query_kws:
        return hits

    for hit in hits:
        text = hit.get("text", "")
        overlap = keyword_overlap(query_kws, text)
        if overlap > 0:
            hit["fused_distance"] = hit["fused_distance"] * (1.0 - weight * overlap)

    return hits


def stage_importance_boost(hits: list, query: str, config: dict) -> list:
    """Apply emotional_weight/importance boost to fused_distance.

    Config keys (under rerank.importance_boost):
        weight: max distance reduction factor (default 0.15)
    """
    boost_cfg = config.get("importance_boost", {})
    weight = float(boost_cfg.get("weight", 0.15))

    for hit in hits:
        ew = hit.get("emotional_weight")
        if ew is None:
            continue
        try:
            ew_val = float(ew)
        except (ValueError, TypeError):
            continue
        # Normalize emotional_weight to 0-1 range (typically 0-5 scale)
        normalized = min(1.0, max(0.0, ew_val / 5.0))
        if normalized > 0:
            hit["fused_distance"] = hit["fused_distance"] * (1.0 - weight * normalized)

    return hits


def stage_llm_rerank(hits: list, query: str, config: dict) -> list:
    """Optional LLM reranking — promotes the LLM's best pick to rank 1.

    Config keys (under rerank.llm_rerank):
        model:  Claude model ID (default claude-haiku-4-5-20251001)
        top_k:  Number of candidates to send to LLM (default 10)
        api_key: Anthropic API key (or use ANTHROPIC_API_KEY env var)
    """
    import urllib.request
    import urllib.error

    llm_cfg = config.get("llm_rerank", {})
    api_key = llm_cfg.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return hits

    model = llm_cfg.get("model", "claude-haiku-4-5-20251001")
    top_k = int(llm_cfg.get("top_k", 10))

    candidates = hits[:top_k]
    if len(candidates) < 2:
        return hits

    # Format sessions for the prompt
    session_blocks = []
    for rank, hit in enumerate(candidates, 1):
        text = hit.get("text", "")[:500].replace("\n", " ").strip()
        session_blocks.append(f"Session {rank}:\n{text}")

    sessions_text = "\n\n".join(session_blocks)

    prompt = (
        f"Question: {query}\n\n"
        f"Below are {len(candidates)} memory excerpts. "
        f"Which single excerpt is most likely to contain the answer? "
        f"Reply with ONLY a number between 1 and {len(candidates)}. Nothing else.\n\n"
        f"{sessions_text}\n\n"
        f"Most relevant excerpt number:"
    )

    payload = json.dumps(
        {
            "model": model,
            "max_tokens": 8,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
        raw = result["content"][0]["text"].strip()
        m = re.search(r"\b(\d+)\b", raw)
        if m:
            pick = int(m.group(1))
            if 1 <= pick <= len(candidates):
                # Promote the picked hit to rank 1 by giving it the lowest fused_distance
                chosen = candidates[pick - 1]
                min_dist = min(h["fused_distance"] for h in hits)
                chosen["fused_distance"] = min_dist * 0.5  # ensure it's clearly first
                chosen["llm_promoted"] = True
    except Exception as e:
        logger.debug("LLM rerank failed (graceful fallback): %s", e)

    return hits


# ---------------------------------------------------------------------------
# Pipeline coordinator
# ---------------------------------------------------------------------------

_STAGES = {
    "weibull_decay": stage_weibull_decay,
    "keyword_boost": stage_keyword_boost,
    "importance_boost": stage_importance_boost,
    "llm_rerank": stage_llm_rerank,
}

# Execution order
_STAGE_ORDER = ["weibull_decay", "keyword_boost", "importance_boost", "llm_rerank"]


def rerank(hits: list, query: str, config: dict) -> list:
    """Run all enabled rerank stages in order.

    Args:
        hits: List of hit dicts from search_memories(). Each must have
              'distance' and 'similarity' keys at minimum.
        query: The original search query string.
        config: The 'rerank' section from config.json.

    Returns:
        Reranked list of hits, sorted by fused_distance ascending.
        Each hit gains 'fused_distance' and 'adjusted_similarity' keys.
    """
    if not hits or not config:
        return hits

    # Initialize fused_distance from raw distance
    for hit in hits:
        hit["fused_distance"] = hit.get("distance", 0.0)

    stages_run = []
    for stage_name in _STAGE_ORDER:
        stage_cfg = config.get(stage_name, {})
        if stage_cfg.get("enabled", False):
            stage_fn = _STAGES.get(stage_name)
            if stage_fn:
                hits = stage_fn(hits, query, config)
                stages_run.append(stage_name)

    if stages_run:
        # Re-sort by fused_distance ascending (lower = better match)
        hits.sort(key=lambda h: h["fused_distance"])
        # Compute adjusted_similarity from fused_distance
        for hit in hits:
            hit["adjusted_similarity"] = round(max(0.0, 1 - hit["fused_distance"]), 3)
            hit["fused_distance"] = round(hit["fused_distance"], 4)
        # Tag which stages ran
        hits[0]["rerank_stages"] = stages_run if hits else []

    return hits
