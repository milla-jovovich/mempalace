"""ambient.py — Onnipervasività for MemPalace."""

import logging
from .config import MempalaceConfig
from .knowledge_graph import KnowledgeGraph
from .palace import get_collection
from .topology import calculate_pagerank, find_structural_holes


def get_whisper(context: str, palace_path: str = None, threshold: float = 0.3) -> str:
    """Get a highly relevant historical context whisper based on current text."""
    config = MempalaceConfig()
    path = palace_path or config.palace_path
    col = get_collection(path, config.collection_name)
    if not col:
        return ""

    try:
        res = col.query(
            query_texts=[context], n_results=1, include=["documents", "metadatas", "distances"]
        )
        if res["distances"] and len(res["distances"]) > 0 and len(res["distances"][0]) > 0:
            dist = res["distances"][0][0]
            if dist < threshold:
                doc = res["documents"][0][0]

                # Safe metadata extraction
                metas = res.get("metadatas", [[{}]])[0] or []
                meta = metas[0] if len(metas) > 0 and metas[0] else {}
                room = meta.get("room", "unknown")

                return f"[Whisper from {room}]: {doc[:200]}..."
    except Exception as e:
        logging.error(f"Whisper error: {e}")
        pass
    return ""


def get_socratic_question() -> str:
    """Generate a question based on structural holes in the knowledge graph."""
    kg = KnowledgeGraph()
    conn = kg._conn()

    # Get all room edges from graph and wormholes
    edges = []
    nodes = set()
    rows = conn.execute(
        "SELECT subject, object FROM triples WHERE predicate = 'semantically_bridges'"
    ).fetchall()
    for r in rows:
        edges.append((r["subject"], r["object"]))
        nodes.add(r["subject"])
        nodes.add(r["object"])

    if not nodes:
        return "Not enough data to ask a socratic question yet. Keep building your palace."

    holes = find_structural_holes(list(nodes), edges)
    if holes:
        broker = holes[0]
        return f"Socratic Question: You often bridge ideas through '{broker}'. Have you considered exploring what connects its disparate neighbors directly?"

    return "Your palace is highly interconnected. What new domain can you explore today?"


def get_eigen_thoughts() -> list:
    """Return top 5 core pillars of the user's mind."""
    kg = KnowledgeGraph()
    conn = kg._conn()
    edges = [
        (r["subject"], r["object"])
        for r in conn.execute("SELECT subject, object FROM triples").fetchall()
    ]
    nodes = list(set([u for u, v in edges] + [v for u, v in edges]))

    pr = calculate_pagerank(nodes, edges)
    sorted_pr = sorted(pr.items(), key=lambda x: -x[1])
    return [n for n, score in sorted_pr[:5]]
