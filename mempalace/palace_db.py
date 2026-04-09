"""
palace_db.py — Central ChromaDB client factory for MemPalace.

All ChromaDB access in production code must go through this module.
Returns HttpClient when remote config is present, PersistentClient otherwise.
"""

import os

import chromadb

from .config import MempalaceConfig
from .config import DEFAULT_COLLECTION_NAME as DEFAULT_COLLECTION

_http_clients = {}  # cache: (host, port, ssl) -> HttpClient
_persistent_clients = {}  # cache: path -> PersistentClient


def get_client(palace_path=None):
    """Return a ChromaDB client.

    Uses HttpClient when chroma_host is configured; PersistentClient otherwise.
    Both client types are cached to avoid repeated connection overhead in
    long-lived processes (e.g. MCP server).
    palace_path is ignored in remote mode — the server manages its own storage.
    """
    cfg = MempalaceConfig()
    if cfg.chroma_host:
        key = (cfg.chroma_host, cfg.chroma_port, cfg.chroma_ssl)
        if key not in _http_clients:
            _http_clients[key] = chromadb.HttpClient(
                host=cfg.chroma_host, port=cfg.chroma_port, ssl=cfg.chroma_ssl
            )
        return _http_clients[key]

    path = palace_path or cfg.palace_path
    if path not in _persistent_clients:
        os.makedirs(path, exist_ok=True)
        _persistent_clients[path] = chromadb.PersistentClient(path=path)
    return _persistent_clients[path]


def get_collection(palace_path=None, name=DEFAULT_COLLECTION):
    """Return the named ChromaDB collection, creating it if absent.

    palace_path is passed to get_client and is ignored in remote mode.
    """
    client = get_client(palace_path=palace_path)
    return client.get_or_create_collection(name)


def clear_caches():
    """Clear all cached clients.

    Call after config changes or in test teardown to force fresh client
    creation on the next get_client() call.
    Warning: env var changes to MEMPALACE_CHROMA_HOST are not picked up
    automatically in long-running processes — call clear_caches() first.
    """
    _http_clients.clear()
    _persistent_clients.clear()
