"""
rem_cycle.py — Proactive memory consolidation for MemPalace.
Finds semantic wormholes and structural holes in the background.
"""
import logging
from .palace import get_collection
from .knowledge_graph import KnowledgeGraph
from .config import MempalaceConfig

logger = logging.getLogger("mempalace_rem")

def run_rem_cycle(col=None, kg=None, limit=50, threshold=0.08):
    """Scan recent entries and find deep semantic connections."""
    if col is None:
        config = MempalaceConfig()
        col = get_collection(config.palace_path, config.collection_name)
    if kg is None:
        kg = KnowledgeGraph()
        
    try:
        # Get latest N drawers (ChromaDB doesn't sort by time natively without metadata, 
        # but we can get the tail or just sample. For now, get last N items)
        total = col.count()
        if total == 0:
            return
            
        offset = max(0, total - limit)
        recent = col.get(limit=limit, offset=offset, include=["documents", "metadatas"])
        
        for i, doc in enumerate(recent["documents"]):
            meta = recent["metadatas"][i]
            room_a = meta.get("room")
            if not room_a or room_a == "general":
                continue
                
            # Query for similar items
            results = col.query(
                query_texts=[doc],
                n_results=3,
                include=["documents", "metadatas", "distances"]
            )
            
            for j, dist in enumerate(results["distances"][0]):
                if dist < threshold: # Distance < 0.08 means highly similar
                    match_meta = results["metadatas"][0][j]
                    room_b = match_meta.get("room")
                    if room_b and room_b != room_a and room_b != "general":
                        score = round(1 - dist, 3)
                        kg.add_bridge(room_a, room_b, score=score, reason=doc)
                        logger.info(f"WORMHOLE OPENED: {room_a} <-> {room_b} ({score})")
                        
    except Exception as e:
        logger.error(f"REM Cycle failed: {e}")
    finally:
        if hasattr(kg, 'close'):
            kg.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_rem_cycle()
