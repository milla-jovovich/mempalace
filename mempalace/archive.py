"""
archive.py — Moves noise vectors to soft-archive wings to prevent hubness.
"""

from typing import List, Any
from .knowledge_graph import KnowledgeGraph


def archive_noise(col: Any, kg: KnowledgeGraph, room_name: str, noise_ids: List[str]) -> int:
    """
    Archive noisy entries by changing their wing to 'archive' and updating the KnowledgeGraph.
    """
    if not noise_ids:
        return 0

    results = col.get(ids=noise_ids)
    ids = results.get("ids", [])
    metadatas = results.get("metadatas", [])

    if not ids:
        return 0

    updated_metadatas = []
    for meta in metadatas:
        # ChromaDB metadatas can be None, though usually they are dicts
        new_meta = dict(meta) if meta else {}

        # Preserve original metadata for round-trip (uncrystallize) restoration
        if "wing" in new_meta:
            new_meta["original_wing"] = new_meta["wing"]
        if "room" in new_meta:
            new_meta["original_room"] = new_meta["room"]

        new_meta["wing"] = "archive"
        updated_metadatas.append(new_meta)

    col.update(ids=ids, metadatas=updated_metadatas)

    kg.add_entity(room_name, "room")
    kg.add_entity(f"{room_name}_archive", "room")
    kg.add_triple(room_name, "has_archive", f"{room_name}_archive")

    return len(ids)
