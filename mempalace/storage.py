"""Shared ChromaDB access helpers for MemPalace."""

from pathlib import Path
from typing import Optional

import chromadb

from .config import MempalaceConfig


class PalaceNotFoundError(RuntimeError):
    """Raised when the configured palace or collection does not exist."""


def get_collection(
    palace_path: Optional[str] = None,
    collection_name: Optional[str] = None,
    create: bool = False,
):
    cfg = MempalaceConfig()
    resolved_palace_path = palace_path or cfg.palace_path
    resolved_collection_name = collection_name or cfg.collection_name

    client = chromadb.PersistentClient(path=resolved_palace_path)
    if create:
        return client.get_or_create_collection(resolved_collection_name)
    return client.get_collection(resolved_collection_name)


def build_where(wing: Optional[str] = None, room: Optional[str] = None):
    if wing and room:
        return {"$and": [{"wing": wing}, {"room": room}]}
    if wing:
        return {"wing": wing}
    if room:
        return {"room": room}
    return None


def query_drawers(
    query: str,
    palace_path: Optional[str] = None,
    collection_name: Optional[str] = None,
    wing: Optional[str] = None,
    room: Optional[str] = None,
    n_results: int = 5,
):
    col = get_collection(palace_path=palace_path, collection_name=collection_name)
    kwargs = {
        "query_texts": [query],
        "n_results": n_results,
        "include": ["documents", "metadatas", "distances"],
    }
    where = build_where(wing=wing, room=room)
    if where:
        kwargs["where"] = where

    results = col.query(**kwargs)
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
                "metadata": meta,
            }
        )
    return hits


def get_drawers(
    palace_path: Optional[str] = None,
    collection_name: Optional[str] = None,
    wing: Optional[str] = None,
    room: Optional[str] = None,
    limit: Optional[int] = None,
    include=None,
):
    col = get_collection(palace_path=palace_path, collection_name=collection_name)
    kwargs = {"include": include or ["documents", "metadatas"]}
    if limit is not None:
        kwargs["limit"] = limit
    where = build_where(wing=wing, room=room)
    if where:
        kwargs["where"] = where
    return col.get(**kwargs)


def summarize_taxonomy(metadatas: list):
    taxonomy = {}
    for meta in metadatas:
        wing = meta.get("wing", "unknown")
        room = meta.get("room", "unknown")
        taxonomy.setdefault(wing, {})
        taxonomy[wing][room] = taxonomy[wing].get(room, 0) + 1
    return taxonomy
