#!/usr/bin/env python3
"""
searcher.py — Find anything. Exact words.

Semantic search against the palace.
Returns verbatim text — the actual words, never summaries.
"""

import logging
import re
from pathlib import Path
from typing import Optional

import chromadb

logger = logging.getLogger("mempalace_mcp")

# ---------------------------------------------------------------------------
# Vocabulary map — query expansion
# ---------------------------------------------------------------------------
# Stored as vocabulary_map.yaml inside the palace directory.
# Format:
#
#   concepts:
#     - natural_language:
#         - "what camera should I get"
#         - "camera recommendation"
#       corpus_terms:
#         - "Sony A7R V"
#         - "mirrorless"
#         - "61MP"
#
# When a query matches any natural_language phrase, its corpus_terms are
# appended to the query text before it hits ChromaDB.  This turns a casual
# natural-language question into the exact vocabulary that lives in the
# corpus, which is the single biggest source of search misses.
# ---------------------------------------------------------------------------


def _load_yaml_simple(path: Path) -> dict:
    """
    Minimal YAML parser for the vocabulary_map format — no PyYAML dependency.
    Handles only the two-level structure MemPalace uses:

        concepts:
          - natural_language:
              - "phrase one"
              - phrase two
            corpus_terms:
              - Term A
              - Term B

    Returns {"concepts": [{"natural_language": [...], "corpus_terms": [...]}]}
    or {} on parse error.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    concepts = []
    current: Optional[dict] = None
    in_natural = False
    in_corpus = False

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.lstrip()

        # Strip inline comments
        stripped = re.sub(r"\s+#.*$", "", stripped)

        if not stripped or stripped.startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip())

        if stripped == "concepts:":
            in_natural = in_corpus = False
            continue

        # New concept block (list item at indent 2)
        if indent == 2 and stripped.startswith("- natural_language:"):
            if current is not None:
                concepts.append(current)
            current = {"natural_language": [], "corpus_terms": []}
            in_natural = True
            in_corpus = False
            continue

        if indent == 4 and stripped == "corpus_terms:":
            in_natural = False
            in_corpus = True
            continue

        if indent == 4 and stripped == "natural_language:":
            in_natural = True
            in_corpus = False
            continue

        # List items (indent 6)
        if indent == 6 and stripped.startswith("- ") and current is not None:
            value = stripped[2:].strip().strip('"').strip("'")
            if in_natural:
                current["natural_language"].append(value)
            elif in_corpus:
                current["corpus_terms"].append(value)

    if current is not None:
        concepts.append(current)

    return {"concepts": concepts} if concepts else {}


def load_vocab_map(palace_path: str) -> dict:
    """
    Load vocabulary_map.yaml from the palace directory.
    Returns the parsed map or {} if the file does not exist or is unreadable.
    """
    path = Path(palace_path) / "vocabulary_map.yaml"
    if not path.exists():
        return {}
    data = _load_yaml_simple(path)
    logger.debug("Loaded vocab map with %d concepts from %s", len(data.get("concepts", [])), path)
    return data


def expand_query(query: str, vocab_map: dict) -> str:
    """
    Expand *query* with corpus-specific terms from *vocab_map*.

    For each concept whose natural_language phrases match (case-insensitive
    substring) inside the query, the matching corpus_terms are appended once.
    The original query is always preserved — expansion only adds terms.

    Returns the (possibly expanded) query string.
    """
    if not vocab_map or "concepts" not in vocab_map:
        return query

    query_lower = query.lower()
    extra: list[str] = []
    matched_terms: set[str] = set()

    for concept in vocab_map["concepts"]:
        nl_phrases = concept.get("natural_language", [])
        corpus_terms = concept.get("corpus_terms", [])
        if not nl_phrases or not corpus_terms:
            continue

        matched = any(phrase.lower() in query_lower for phrase in nl_phrases)
        if matched:
            for term in corpus_terms:
                if term not in matched_terms:
                    matched_terms.add(term)
                    extra.append(term)

    if extra:
        expanded = query + " " + " ".join(extra)
        logger.debug("Query expanded: %r → %r", query, expanded)
        return expanded

    return query


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

    # Query expansion via vocabulary map
    vocab_map = load_vocab_map(palace_path)
    effective_query = expand_query(query, vocab_map)

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
            "query_texts": [effective_query],
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
    if effective_query != query:
        print(f"  Expanded:    {effective_query}")
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

    # Query expansion via vocabulary map
    vocab_map = load_vocab_map(palace_path)
    effective_query = expand_query(query, vocab_map)

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
            "query_texts": [effective_query],
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
            }
        )

    result: dict = {
        "query": query,
        "filters": {"wing": wing, "room": room},
        "results": hits,
    }
    if effective_query != query:
        result["expanded_query"] = effective_query
    return result
