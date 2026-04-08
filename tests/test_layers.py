"""
test_layers.py — Regression tests for layered retrieval helpers.
"""

from mempalace.layers import Layer3


class TestLayer3Search:
    def test_search_handles_empty_query_payload(self, monkeypatch):
        class _FakeCollection:
            def query(self, **_kwargs):
                return {"documents": [], "metadatas": [], "distances": []}

        class _FakeClient:
            def __init__(self, path):
                self.path = path

            def get_collection(self, _name):
                return _FakeCollection()

        monkeypatch.setattr(
            "mempalace.layers.chromadb.PersistentClient",
            _FakeClient,
        )

        result = Layer3(palace_path="/tmp/fake-palace").search("anything")
        assert result == "No results found."

    def test_search_raw_handles_empty_query_payload(self, monkeypatch):
        class _FakeCollection:
            def query(self, **_kwargs):
                return {"documents": [], "metadatas": [], "distances": []}

        class _FakeClient:
            def __init__(self, path):
                self.path = path

            def get_collection(self, _name):
                return _FakeCollection()

        monkeypatch.setattr(
            "mempalace.layers.chromadb.PersistentClient",
            _FakeClient,
        )

        result = Layer3(palace_path="/tmp/fake-palace").search_raw("anything")
        assert result == []
