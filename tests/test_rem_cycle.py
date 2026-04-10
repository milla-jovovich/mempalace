import pytest
from unittest.mock import MagicMock, patch

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
        "metadatas": [{"room": "room_a", "wing": "w1"}, {"room": "room_c", "wing": "w2"}]
    }
    
    # Simulate query results (finding a wormhole for d1)
    mock_col.query.side_effect = [
        {
            "documents": [["similar_doc"]],
            "metadatas": [[{"room": "room_b", "wing": "w3"}]],
            "distances": [[0.05]] # highly similar!
        },
        {
            "documents": [["unrelated_doc"]],
            "metadatas": [[{"room": "room_d", "wing": "w4"}]],
            "distances": [[0.8]] # not similar
        }
    ]
    
    run_rem_cycle(mock_col, mock_kg, limit=2, threshold=0.08)
    
    # Should have added one bridge between room_a and room_b
    mock_kg.add_bridge.assert_called_once_with("room_a", "room_b", score=0.95, reason="doc1")
