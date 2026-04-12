def test_eigen_thoughts():
    from mempalace.topology import calculate_pagerank, find_structural_holes

    # Simple graph: A-B, B-C, C-A (triangle), and D connected only to C
    nodes = ["A", "B", "C", "D"]
    edges = [("A", "B"), ("B", "C"), ("C", "A"), ("C", "D")]

    pr = calculate_pagerank(nodes, edges, iterations=10)
    # C should have highest rank
    assert pr["C"] > pr["D"]
    assert pr["C"] > pr["A"]

    holes = find_structural_holes(nodes, edges)
    # C is the broker (structural hole filler)
    assert holes[0] == "C"


def test_find_structural_holes_with_duplicates():
    from mempalace.topology import find_structural_holes

    # B is the broker. We add duplicate A-B and B-C edges to simulate multiple wormholes.
    nodes = ["A", "B", "C", "D"]
    edges = [("A", "B"), ("A", "B"), ("B", "C"), ("B", "C"), ("C", "D")]

    holes = find_structural_holes(nodes, edges)

    # If not deduplicated, B's score inflates incorrectly.
    # With deduplication, B is still the top broker but calculation doesn't crash or skew.
    assert holes[0] == "B"
    # Also verify that it doesn't fail on deduplication
    assert len(holes) >= 1
