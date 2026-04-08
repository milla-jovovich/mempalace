"""
utils.py — Shared utility helpers.
"""


def extract_query_lists(results: dict):
    """
    Return (docs, metas, dists) from a ChromaDB query payload safely.

    ChromaDB can return {"documents": []} when no matches are found.
    Indexing [0] on an empty outer list raises IndexError unless guarded.
    """
    documents = results.get("documents") or []
    metadatas = results.get("metadatas") or []
    distances = results.get("distances") or []

    docs = documents[0] if documents else []
    metas = metadatas[0] if metadatas else []
    dists = distances[0] if distances else []
    return docs, metas, dists
