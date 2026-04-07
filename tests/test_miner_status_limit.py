import sys
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

# Mock chromadb before importing miner
sys.modules["chromadb"] = Mock()
import chromadb

from mempalace import miner


def test_status_uses_collection_count_not_hardcoded_limit(monkeypatch, capsys):
    mock_collection = Mock()
    mock_collection.count.return_value = 15000
    mock_collection.get.return_value = {
        "metadatas": [
            {"wing": "wing1", "room": "room1"},
            {"wing": "wing1", "room": "room2"},
            {"wing": "wing2", "room": "room1"},
        ]
    }

    mock_client = Mock()
    mock_client.get_collection.return_value = mock_collection

    with patch("mempalace.miner.chromadb.PersistentClient", return_value=mock_client):
        miner.status("/tmp/palace")

    mock_collection.count.assert_called_once()
    mock_collection.get.assert_called_once_with(limit=15000, include=["metadatas"])


def test_status_handles_large_collections_correctly(monkeypatch, capsys):
    mock_collection = Mock()
    mock_collection.count.return_value = 25000
    mock_collection.get.return_value = {
        "metadatas": [{"wing": "wing_large", "room": "room_large"}] * 10
    }

    mock_client = Mock()
    mock_client.get_collection.return_value = mock_collection

    with patch("mempalace.miner.chromadb.PersistentClient", return_value=mock_client):
        miner.status("/tmp/palace")

    # Verify count() was called and get() used that count as limit
    mock_collection.count.assert_called_once()
    mock_collection.get.assert_called_once_with(limit=25000, include=["metadatas"])

    output = capsys.readouterr().out
    assert "wing_large" in output
    assert "room_large" in output
