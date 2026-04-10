"""
Tests for mempalace/crystallize.py
"""

from typing import Any, Dict, List
from mempalace.crystallize import find_room_diamonds


class MockCollection:
    def __init__(self, ids: List[str], docs: List[str], query_returns: Dict[str, Any]):
        self.ids = ids
        self.docs = docs
        self.query_returns = query_returns

    def get(self, where: Dict[str, Any], include: List[str]) -> Dict[str, Any]:
        assert where == {"room": "TestRoom"}
        assert include == ["documents", "metadatas"]
        return {
            "ids": self.ids,
            "documents": self.docs,
            "metadatas": [{}] * len(self.ids),
        }

    def query(
        self,
        query_texts: List[str],
        where: Dict[str, Any],
        n_results: int,
        include: List[str],
    ) -> Dict[str, Any]:
        assert query_texts == self.docs
        assert where == {"room": "TestRoom"}
        assert n_results == min(4, len(self.ids))
        assert include == ["distances"]
        return self.query_returns


def test_find_room_diamonds():
    # Setup mock data
    ids = ["id1", "id2", "id3", "id4", "id5", "id6"]
    docs = ["doc1", "doc2", "doc3", "doc4", "doc5", "doc6"]

    # Let's say id1 is closely related to id2, id3
    # id4 is related to id5
    # Distances < 0.3 will form edges
    query_returns = {
        "ids": [
            ["id1", "id2", "id3", "id4"],  # query for id1
            ["id2", "id1", "id3", "id5"],  # query for id2
            ["id3", "id1", "id2", "id6"],  # query for id3
            ["id4", "id5", "id1", "id2"],  # query for id4
            ["id5", "id4", "id1", "id3"],  # query for id5
            ["id6", "id3", "id1", "id2"],  # query for id6
        ],
        "distances": [
            [0.0, 0.1, 0.2, 0.9],  # id1 matches id2, id3
            [0.0, 0.1, 0.2, 0.8],  # id2 matches id1, id3
            [0.0, 0.2, 0.2, 0.9],  # id3 matches id1, id2
            [0.0, 0.1, 0.8, 0.9],  # id4 matches id5
            [0.0, 0.1, 0.7, 0.8],  # id5 matches id4
            [0.0, 0.2, 0.9, 0.9],  # id6 matches id3
        ],
    }

    col = MockCollection(ids, docs, query_returns)

    diamonds, noise = find_room_diamonds(col, "TestRoom", top_k=2)

    # There are 6 ids. top_k is 2.
    assert len(diamonds) == 2
    assert len(noise) == 4

    # id1, id2, id3 form a clique and will have high pagerank
    # The actual order depends on the exact pagerank scores
    assert set(diamonds).issubset({"id1", "id2", "id3"})


def test_find_room_diamonds_empty():
    col = MockCollection([], [], {})
    diamonds, noise = find_room_diamonds(col, "TestRoom", top_k=2)
    assert diamonds == []
    assert noise == []


def test_find_room_diamonds_percentage():
    from unittest.mock import MagicMock

    mock_col = MagicMock()

    # 10 documents
    ids = [f"doc{i}" for i in range(10)]
    mock_col.get.return_value = {
        "ids": ids,
        "documents": [f"Idea {i}" for i in range(10)],
        "metadatas": [{"room": "ideas"}] * 10,
    }

    mock_col.query.return_value = {
        "ids": [["doc0"] for _ in range(10)],
        "distances": [[0.5] for _ in range(10)],
    }

    # Request top 20% (should be 2 items out of 10)
    diamonds, noise = find_room_diamonds(mock_col, "ideas", top_k=0.2)
    assert len(diamonds) == 2
    assert len(noise) == 8


def test_crystallize_idempotency():
    from unittest.mock import MagicMock

    mock_col = MagicMock()

    # 2 documents (surviving diamonds from previous crystallization)
    ids = ["diamond1", "diamond2"]
    mock_col.get.return_value = {
        "ids": ids,
        "documents": ["Idea 1", "Idea 2"],
        "metadatas": [{"room": "ideas"}] * 2,
    }

    # Second pass: ask for top 5, but we only have 2 left.
    # It should return the 2 diamonds and 0 noise.
    diamonds, noise = find_room_diamonds(mock_col, "ideas", top_k=5)

    assert len(diamonds) == 2
    assert set(diamonds) == {"diamond1", "diamond2"}
    assert len(noise) == 0

    # Query shouldn't be called because of early return
    mock_col.query.assert_not_called()
