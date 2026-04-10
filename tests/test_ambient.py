from mempalace.ambient import get_whisper, get_socratic_question
from unittest.mock import patch, MagicMock

@patch("mempalace.ambient.get_collection")
def test_ambient_whisper(mock_get_col):
    mock_col = MagicMock()
    mock_get_col.return_value = mock_col
    
    mock_col.query.return_value = {
        "documents": [["Historical wisdom"]],
        "metadatas": [[{"room": "wisdom", "wing": "past"}]],
        "distances": [[0.05]]
    }
    
    res = get_whisper("I am coding something")
    assert "Historical wisdom" in res
    assert "wisdom" in res

def test_socratic_question():
    mock_kg = MagicMock()
    # Mock some triples to form a graph
    mock_kg._conn().execute().fetchall.return_value = [
        {"subject": "A", "object": "B"},
        {"subject": "B", "object": "C"}
    ]
    with patch("mempalace.ambient.KnowledgeGraph", return_value=mock_kg):
        with patch("mempalace.topology.find_structural_holes", return_value=["B"]):
            q = get_socratic_question()
            assert "B" in q
