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
