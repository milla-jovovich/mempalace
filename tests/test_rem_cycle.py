from unittest.mock import MagicMock


def test_rem_cycle_wormholes():
    from mempalace.rem_cycle import run_rem_cycle

    # Mock ChromaDB and KG
    mock_col = MagicMock()
    mock_kg = MagicMock()
    mock_col.count.return_value = 2

    # Simulate 2 recent drawers
    mock_col.get.return_value = {
        "ids": ["d1", "d2"],
        "documents": ["doc1", "doc2"],
        "metadatas": [{"room": "room_a", "wing": "w1"}, {"room": "room_c", "wing": "w2"}],
    }

    # Simulate query results (finding a wormhole for d1)
    mock_col.query.side_effect = [
        {
            "ids": [["d3"]],
            "documents": [["similar_doc"]],
            "metadatas": [[{"room": "room_b", "wing": "w3"}]],
            "distances": [[0.05]],  # highly similar!
        },
        {
            "ids": [["d4"]],
            "documents": [["unrelated_doc"]],
            "metadatas": [[{"room": "room_d", "wing": "w4"}]],
            "distances": [[0.8]],  # not similar
        },
    ]

    run_rem_cycle(mock_col, mock_kg, limit=2, threshold=0.08)

    # Should have added one bridge between room_a and room_b
    mock_kg.add_bridge.assert_called_once_with("room_a", "room_b", score=0.95, reason="doc1")


def test_rem_cycle_ignores_self_match():
    from mempalace.rem_cycle import run_rem_cycle

    mock_col = MagicMock()
    mock_kg = MagicMock()
    mock_col.count.return_value = 1

    mock_col.get.return_value = {
        "ids": ["doc_123"],
        "documents": ["My brilliant idea"],
        "metadatas": [{"room": "room_a", "wing": "w1"}],
    }

    # Query returns the exact same document as the best match (distance 0.0)
    # and another document as the second match
    mock_col.query.return_value = {
        "ids": [["doc_123", "doc_456"]],
        "documents": [["My brilliant idea", "Another idea"]],
        "metadatas": [[{"room": "room_a", "wing": "w1"}, {"room": "room_b", "wing": "w2"}]],
        "distances": [[0.0, 0.05]],
    }

    run_rem_cycle(mock_col, mock_kg, limit=1, threshold=0.08)

    # Should only add bridge for doc_456 (room_b), NOT doc_123 (self, room_a)
    mock_kg.add_bridge.assert_called_once_with(
        "room_a", "room_b", score=0.95, reason="My brilliant idea"
    )
