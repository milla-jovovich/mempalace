"""Tests for Qdrant backend adapter."""

import pytest

# Skip all tests if qdrant_client is not installed
pytest.importorskip("qdrant_client")
pytest.importorskip("sentence_transformers")

from mempalace.backends.qdrant import (
    QdrantBackend,
    QdrantCollection,
    _build_filter,
    _to_qdrant_id,
)


class _FakeQdrantClient:
    """Minimal fake for testing collection wrapper without real Qdrant."""

    def __init__(self):
        self.calls = []

    def count(self, collection_name):
        self.calls.append(("count", {"collection_name": collection_name}))

        class CountResult:
            count = 42

        return CountResult()

    def upsert(self, collection_name, points):
        self.calls.append(("upsert", {"collection_name": collection_name, "points": points}))

    def retrieve(self, collection_name, ids, with_payload, with_vectors):
        self.calls.append(
            (
                "retrieve",
                {
                    "collection_name": collection_name,
                    "ids": ids,
                    "with_payload": with_payload,
                    "with_vectors": with_vectors,
                },
            )
        )

        class Point:
            def __init__(self, qid, orig_id):
                self.id = qid
                self.payload = {"_original_id": orig_id, "document": "doc", "wing": "test"}
                self.vector = [0.1] * 384

        return [Point(ids[0], "original_1")]

    def scroll(self, collection_name, scroll_filter, limit, offset, with_payload, with_vectors):
        self.calls.append(
            (
                "scroll",
                {
                    "collection_name": collection_name,
                    "scroll_filter": scroll_filter,
                    "limit": limit,
                    "offset": offset,
                    "with_payload": with_payload,
                    "with_vectors": with_vectors,
                },
            )
        )
        return [], None

    def query_points(self, collection_name, query, query_filter, limit, with_payload):
        self.calls.append(
            (
                "query_points",
                {
                    "collection_name": collection_name,
                    "query": query,
                    "query_filter": query_filter,
                    "limit": limit,
                    "with_payload": with_payload,
                },
            )
        )

        class ScoredPoint:
            def __init__(self):
                self.id = "uuid-1"
                self.payload = {"_original_id": "doc1", "document": "test", "wing": "w"}
                self.score = 0.95  # Cosine similarity

        class QueryResult:
            points = [ScoredPoint()]

        return QueryResult()

    def delete(self, collection_name, points_selector):
        self.calls.append(
            ("delete", {"collection_name": collection_name, "points_selector": points_selector})
        )


def test_qdrant_collection_count():
    fake_client = _FakeQdrantClient()
    collection = QdrantCollection(fake_client, "test_col")

    count = collection.count()

    assert count == 42
    assert fake_client.calls == [("count", {"collection_name": "test_col"})]


def test_qdrant_collection_get_by_ids():
    fake_client = _FakeQdrantClient()
    collection = QdrantCollection(fake_client, "test_col")

    result = collection.get(ids=["original_1"], include=["documents", "metadatas"])

    assert "ids" in result
    assert "documents" in result
    assert "metadatas" in result
    assert len(fake_client.calls) == 1
    assert fake_client.calls[0][0] == "retrieve"


def test_qdrant_collection_get_with_filter():
    fake_client = _FakeQdrantClient()
    collection = QdrantCollection(fake_client, "test_col")

    result = collection.get(where={"wing": "test"}, limit=10)

    assert "ids" in result
    assert len(fake_client.calls) == 1
    assert fake_client.calls[0][0] == "scroll"


def test_qdrant_collection_delete_by_ids():
    fake_client = _FakeQdrantClient()
    collection = QdrantCollection(fake_client, "test_col")

    collection.delete(ids=["doc1", "doc2"])

    assert len(fake_client.calls) == 1
    assert fake_client.calls[0][0] == "delete"


def test_qdrant_collection_delete_by_filter():
    fake_client = _FakeQdrantClient()
    collection = QdrantCollection(fake_client, "test_col")

    collection.delete(where={"wing": "old"})

    assert len(fake_client.calls) == 1
    assert fake_client.calls[0][0] == "delete"


def test_to_qdrant_id_determinism():
    """UUIDs from same string ID should be identical."""
    id1 = _to_qdrant_id("drawer_abc_123")
    id2 = _to_qdrant_id("drawer_abc_123")
    assert id1 == id2

    id3 = _to_qdrant_id("drawer_abc_124")
    assert id1 != id3


def test_build_filter_simple_eq():
    """Test simple equality filter."""
    f = _build_filter({"wing": "todo"})
    assert f is not None
    assert len(f.must) == 1


def test_build_filter_explicit_eq():
    """Test explicit $eq operator."""
    f = _build_filter({"wing": {"$eq": "todo"}})
    assert f is not None


def test_build_filter_in():
    """Test $in operator."""
    f = _build_filter({"wing": {"$in": ["bellona", "todo"]}})
    assert f is not None


def test_build_filter_ne():
    """Test $ne operator."""
    f = _build_filter({"wing": {"$ne": "archived"}})
    assert f is not None


def test_build_filter_and():
    """Test $and operator."""
    f = _build_filter({"$and": [{"wing": "todo"}, {"room": "general"}]})
    assert f is not None
    assert len(f.must) == 2


def test_build_filter_or():
    """Test $or operator."""
    f = _build_filter({"$or": [{"wing": "todo"}, {"wing": "bellona"}]})
    assert f is not None
    assert len(f.should) == 2


def test_build_filter_none():
    """Empty filter should return None."""
    f = _build_filter(None)
    assert f is None

    f = _build_filter({})
    assert f is None


def test_qdrant_backend_create_false_raises_without_creating_directory(tmp_path):
    """Backend should raise FileNotFoundError when create=False and path missing."""
    palace_path = tmp_path / "missing-palace"

    with pytest.raises(FileNotFoundError):
        QdrantBackend().get_collection(
            str(palace_path),
            collection_name="mempalace_drawers",
            create=False,
        )

    assert not palace_path.exists()


def test_qdrant_backend_create_true_creates_directory_and_collection(tmp_path):
    """Backend should create directory and collection when create=True."""
    palace_path = tmp_path / "palace"

    collection = QdrantBackend().get_collection(
        str(palace_path),
        collection_name="mempalace_drawers",
        create=True,
    )

    assert palace_path.is_dir()
    assert isinstance(collection, QdrantCollection)


def test_qdrant_backend_get_existing_collection(tmp_path):
    """Backend should retrieve existing collection."""
    palace_path = tmp_path / "palace"

    # Create collection
    backend = QdrantBackend()
    backend.get_collection(str(palace_path), collection_name="test_col", create=True)

    # Retrieve existing
    collection = backend.get_collection(str(palace_path), collection_name="test_col", create=False)

    assert isinstance(collection, QdrantCollection)


def test_qdrant_backend_raises_on_missing_collection(tmp_path):
    """Backend should raise ValueError when collection doesn't exist and create=False."""
    palace_path = tmp_path / "palace"
    palace_path.mkdir()

    with pytest.raises(ValueError, match="does not exist"):
        QdrantBackend().get_collection(
            str(palace_path),
            collection_name="missing_col",
            create=False,
        )


@pytest.mark.slow
def test_qdrant_collection_add_and_query_integration(tmp_path):
    """End-to-end test: add documents and query them."""
    palace_path = tmp_path / "palace"
    backend = QdrantBackend()
    collection = backend.get_collection(str(palace_path), collection_name="test", create=True)

    # Add documents
    collection.add(
        documents=["bellona military planning", "todo technical writing"],
        ids=["doc1", "doc2"],
        metadatas=[{"wing": "bellona"}, {"wing": "todo"}],
    )

    # Query by text
    result = collection.query(query_texts=["military strategy"], n_results=1)

    assert len(result["ids"]) == 1
    assert len(result["ids"][0]) == 1
    assert "doc1" in result["ids"][0] or "doc2" in result["ids"][0]
    assert 0.0 <= result["distances"][0][0] <= 1.0


@pytest.mark.slow
def test_qdrant_collection_filter_query_integration(tmp_path):
    """End-to-end test: query with metadata filter."""
    palace_path = tmp_path / "palace"
    backend = QdrantBackend()
    collection = backend.get_collection(str(palace_path), collection_name="test", create=True)

    collection.add(
        documents=["bellona doc 1", "todo doc 1", "bellona doc 2"],
        ids=["b1", "t1", "b2"],
        metadatas=[{"wing": "bellona"}, {"wing": "todo"}, {"wing": "bellona"}],
    )

    # Query with filter
    result = collection.query(
        query_texts=["document"],
        n_results=10,
        where={"wing": "bellona"},
    )

    # Should only return bellona documents
    for meta in result["metadatas"][0]:
        assert meta["wing"] == "bellona"


@pytest.mark.slow
def test_qdrant_collection_upsert_integration(tmp_path):
    """Test upsert updates existing documents."""
    palace_path = tmp_path / "palace"
    backend = QdrantBackend()
    collection = backend.get_collection(str(palace_path), collection_name="test", create=True)

    # Add initial
    collection.add(documents=["original"], ids=["doc1"], metadatas=[{"version": 1}])

    # Upsert (update)
    collection.upsert(documents=["updated"], ids=["doc1"], metadatas=[{"version": 2}])

    # Retrieve
    result = collection.get(ids=["doc1"])

    assert result["documents"][0] == "updated"
    assert result["metadatas"][0]["version"] == 2
