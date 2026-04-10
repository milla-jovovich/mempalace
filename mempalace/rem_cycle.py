"""
rem_cycle.py — Proactive memory consolidation for MemPalace.
Finds semantic wormholes and structural holes in the background.
"""

import logging
from .palace import get_collection
from .knowledge_graph import KnowledgeGraph
from .config import MempalaceConfig

logger = logging.getLogger("mempalace_rem")


def run_rem_cycle(col=None, kg=None, limit: int = 50, threshold: float = 0.08) -> None:
    """
    Scan recent entries and find deep semantic connections.
    Note: col.get() does not guarantee chronological insertion order.
    This acts as a random/approximate sample of the collection for background processing.
    """
    if col is None:
        config = MempalaceConfig()
        col = get_collection(config.palace_path, config.collection_name)
    if kg is None:
        kg = KnowledgeGraph()

    try:
        total = col.count()
        if total == 0:
            return

        offset = max(0, total - limit)
        # Fetch IDs to prevent self-matching
        recent = col.get(limit=limit, offset=offset, include=["documents", "metadatas"])
        recent_ids = recent.get("ids", [])

        for i, doc in enumerate(recent["documents"]):
            source_id = recent_ids[i] if i < len(recent_ids) else None

            # Safe metadata extraction
            metadatas = recent.get("metadatas") or []
            meta = metadatas[i] if i < len(metadatas) and metadatas[i] else {}
            room_a = meta.get("room")

            if not room_a or room_a == "general":
                continue

            # Request n_results=4 to account for self-match
            results = col.query(
                query_texts=[doc], n_results=4, include=["documents", "metadatas", "distances"]
            )

            for j, dist in enumerate(results["distances"][0]):
                # Skip self-match by comparing IDs
                match_ids = results.get("ids", [[]])[0]
                if source_id and j < len(match_ids) and match_ids[j] == source_id:
                    continue

                if dist < threshold:  # Distance < 0.08 means highly similar
                    # Safe match metadata extraction
                    match_metas = results.get("metadatas", [[]])[0] or []
                    match_meta = match_metas[j] if j < len(match_metas) and match_metas[j] else {}
                    room_b = match_meta.get("room")

                    if room_b and room_b != room_a and room_b != "general":
                        score = round(1 - dist, 3)
                        kg.add_bridge(room_a, room_b, score=score, reason=doc)
                        logger.info(f"WORMHOLE OPENED: {room_a} <-> {room_b} ({score})")

    except Exception as e:
        logger.error(f"REM Cycle failed: {e}")
    finally:
        if hasattr(kg, "close"):
            kg.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_rem_cycle()
