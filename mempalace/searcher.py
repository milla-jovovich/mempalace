#!/usr/bin/env python3
"""
searcher.py — Find anything. Exact words.

Semantic search against the palace.
Returns verbatim text — the actual words, never summaries.
"""

import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

import chromadb

logger = logging.getLogger("mempalace_mcp")


class SearchError(Exception):
    """Raised when search cannot proceed (e.g. no palace found)."""


def _verify_with_tardygrada(hits: list) -> dict:
    """
    Run tardygrada verify-doc on search results to detect contradictions.
    Returns {"contradictions": [...]} or {"contradictions": None, "verify_warning": "..."}.
    """
    if not hits:
        return {"contradictions": []}

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, prefix="mempalace_verify_"
        ) as f:
            for i, hit in enumerate(hits, 1):
                f.write(
                    f"## [{i}] {hit['wing']} / {hit['room']} (similarity: {hit['similarity']})\n"
                )
                f.write(hit["text"].strip() + "\n\n")
            tmp_path = f.name

        result = subprocess.run(
            ["tardygrada", "verify-doc", tmp_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return {
                "contradictions": None,
                "verify_warning": f"tardygrada exited with code {result.returncode}: {result.stderr[:200]}",
            }
        return {"contradictions": _parse_conflicts(result.stdout)}
    except FileNotFoundError:
        return {
            "contradictions": None,
            "verify_warning": "tardygrada binary not found on PATH — install from https://github.com/fabio-rovai/tardygrada",
        }
    except subprocess.TimeoutExpired:
        return {
            "contradictions": None,
            "verify_warning": "tardygrada verify-doc timeout after 10s",
        }
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _parse_conflicts(stdout: str) -> list:
    """Parse tardygrada verify-doc output into structured conflict objects."""
    conflicts = []
    pattern = re.compile(
        r'\[CONFLICT\] Lines? (\d+) vs (\d+):\s*\n'
        r'\s*"([^"]+)"\s*\n'
        r'\s*"([^"]+)"\s*\n'
        r'\s*-> [^\n]+\n'
        r'\s*Confidence: ([\d.]+)',
        re.MULTILINE,
    )
    for match in pattern.finditer(stdout):
        conflicts.append({
            "line_a": int(match.group(1)),
            "line_b": int(match.group(2)),
            "claim_a": match.group(3),
            "claim_b": match.group(4),
            "confidence": float(match.group(5)),
        })
    return conflicts


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
    query: str, palace_path: str, wing: str = None, room: str = None, n_results: int = 5,
    verify: bool = False,
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

    response = {
        "query": query,
        "filters": {"wing": wing, "room": room},
        "results": hits,
    }

    if verify:
        response.update(_verify_with_tardygrada(hits))

    return response
