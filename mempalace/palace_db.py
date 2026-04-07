"""Shared ChromaDB operations. Single client, single collection."""

import os

import chromadb

from .config import MempalaceConfig

_clients: dict = {}
_collections: dict = {}


def get_client(palace_path: str = None) -> chromadb.ClientAPI:
    """Singleton PersistentClient per palace_path."""
    cfg = MempalaceConfig()
    path = palace_path or cfg.palace_path
    if path not in _clients:
        os.makedirs(path, exist_ok=True)
        _clients[path] = chromadb.PersistentClient(path=path)
    return _clients[path]


def get_collection(palace_path: str = None, create: bool = False, collection_name: str = None):
    """Get the drawers collection. Cached per (path, name)."""
    cfg = MempalaceConfig()
    path = palace_path or cfg.palace_path
    name = collection_name or cfg.collection_name
    cache_key = (path, name)

    if cache_key in _collections:
        return _collections[cache_key]

    client = get_client(path)
    try:
        if create:
            col = client.get_or_create_collection(name)
        else:
            col = client.get_collection(name)
        _collections[cache_key] = col
        return col
    except Exception:
        return None


def build_where_filter(wing: str = None, room: str = None) -> dict:
    """Build ChromaDB where filter. THE one place this logic lives."""
    if wing and room:
        return {"$and": [{"wing": wing}, {"room": room}]}
    elif wing:
        return {"wing": wing}
    elif room:
        return {"room": room}
    return {}


def file_already_mined(collection, source_file: str) -> bool:
    """Check if a file has been filed before."""
    try:
        results = collection.get(where={"source_file": source_file}, limit=1)
        return len(results.get("ids", [])) > 0
    except Exception:
        return False


def no_palace_error(palace_path: str = None) -> dict:
    """Standard error response when palace not found."""
    cfg = MempalaceConfig()
    path = palace_path or cfg.palace_path
    return {
        "error": "No palace found",
        "palace_path": path,
        "hint": "Run: mempalace init <dir> && mempalace mine <dir>",
    }


def query_palace(
    query: str,
    n_results: int = 5,
    wing: str = None,
    room: str = None,
    palace_path: str = None,
) -> dict | None:
    """Semantic search. Returns raw ChromaDB results dict, or None if no palace."""
    col = get_collection(palace_path=palace_path)
    if not col:
        return None

    where = build_where_filter(wing, room)
    kwargs = {
        "query_texts": [query],
        "n_results": n_results,
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        kwargs["where"] = where

    return col.query(**kwargs)


def reset():
    """Reset all caches. For testing."""
    _clients.clear()
    _collections.clear()
