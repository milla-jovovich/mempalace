"""
topology.py — Graph analysis for Eigen-Thoughts and Structural Holes.
Pure Python implementations (no NetworkX required).
"""

from collections import defaultdict

from typing import List, Tuple, Dict


def calculate_pagerank(
    nodes: List[str], edges: List[Tuple[str, str]], iterations: int = 20, damping: float = 0.85
) -> Dict[str, float]:
    """Calculate Eigen-Thoughts (PageRank) of nodes."""
    if not nodes:
        return {}

    # Deduplicate edges to prevent score inflation
    edges = list(set(edges))

    adj = defaultdict(list)
    for u, v in edges:
        adj[u].append(v)
        adj[v].append(u)  # undirected for our use case

    n = len(nodes)
    pr = {node: 1.0 / n for node in nodes}

    for _ in range(iterations):
        new_pr = {}
        for node in nodes:
            rank_sum = 0.0
            for neighbor in adj[node]:
                if len(adj[neighbor]) > 0:
                    rank_sum += pr[neighbor] / len(adj[neighbor])
            new_pr[node] = (1 - damping) / n + damping * rank_sum
        pr = new_pr

    return pr


def find_structural_holes(nodes: List[str], edges: List[Tuple[str, str]]) -> List[str]:
    """Find brokers (nodes that bridge otherwise disconnected clusters).
    Using a simplified betweenness centrality approximation."""
    
    # Deduplicate edges to prevent score inflation
    edges = list(set(edges))
    
    adj = defaultdict(list)
    for u, v in edges:
        adj[u].append(v)
        adj[v].append(u)

    betweenness = {node: 0.0 for node in nodes}

    # Very simplified: count shortest paths of length 2 that pass through node
    # A node is a broker if it connects two nodes that aren't connected to each other
    for node in nodes:
        neighbors = adj[node]
        for i in range(len(neighbors)):
            for j in range(i + 1, len(neighbors)):
                n1, n2 = neighbors[i], neighbors[j]
                if n2 not in adj[n1]:  # hole found!
                    betweenness[node] += 1.0

    # Sort by score descending
    sorted_nodes = sorted(betweenness.items(), key=lambda x: -x[1])
    return [n for n, score in sorted_nodes if score > 0]
