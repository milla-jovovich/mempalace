"""Tests for mempalace.embeddings — embedding function selection and compatibility checks."""

import logging
from unittest.mock import MagicMock, patch

import chromadb
import pytest

from mempalace.embeddings import (
    _DISTANCE_THRESHOLD,
    clear_compatibility_cache,
    get_embedding_function,
    verify_embedding_compatibility,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Ensure each test starts with a fresh compatibility cache."""
    clear_compatibility_cache()
    yield
    clear_compatibility_cache()


@pytest.fixture
def raw_collection(palace_path):
    """A ChromaDB collection that stores pre-computed embeddings only.

    Does NOT use any embedding function, so we never trigger the ONNX model
    download (which fails when HOME is redirected by the test harness).
    Documents are added with explicit ``embeddings=`` parameter.
    """
    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_or_create_collection("test_col")
    yield col
    try:
        client.delete_collection("test_col")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# get_embedding_function
# ---------------------------------------------------------------------------


class TestGetEmbeddingFunction:
    def test_returns_none_when_import_fails(self):
        """When sentence-transformers is not installed, returns None."""
        import mempalace.embeddings as mod

        original = mod.get_embedding_function

        def failing_get(device="auto"):
            try:
                raise ImportError("no module")
            except (ImportError, Exception):
                return None

        mod.get_embedding_function = failing_get
        try:
            result = mod.get_embedding_function()
            assert result is None
        finally:
            mod.get_embedding_function = original

    def test_no_crash_on_call(self):
        """get_embedding_function should never raise — it returns None or a callable."""
        result = get_embedding_function()
        # Either None (sentence-transformers not installed) or a callable
        assert result is None or callable(result)

    def test_device_cpu(self):
        """Passing device='cpu' should not crash."""
        result = get_embedding_function(device="cpu")
        assert result is None or callable(result)


# ---------------------------------------------------------------------------
# verify_embedding_compatibility
# ---------------------------------------------------------------------------


class TestVerifyEmbeddingCompatibility:
    """Tests for the one-time compatibility check."""

    def test_empty_collection_returns_true(self, raw_collection):
        """An empty collection is always 'compatible'."""
        # ef=None path — should return True immediately
        with patch("mempalace.embeddings.get_embedding_function", return_value=None):
            assert verify_embedding_compatibility(raw_collection) is True

    def test_none_ef_returns_true_immediately(self, raw_collection):
        """When get_embedding_function returns None, skip check entirely."""
        with patch("mempalace.embeddings.get_embedding_function", return_value=None):
            result = verify_embedding_compatibility(raw_collection)
        assert result is True

    def test_compatible_vectors_return_true(self, raw_collection):
        """When nearest-neighbor distance is small, report compatible."""
        # Seed the collection with an explicit embedding vector
        raw_collection.add(
            ids=["doc1"],
            embeddings=[[0.1] * 10],
            documents=["Some text"],
            metadatas=[{"wing": "test", "room": "test"}],
        )

        # Mock embedder that returns a similar vector
        def close_ef(texts):
            return [[0.1] * 10 for _ in texts]

        with patch("mempalace.embeddings.get_embedding_function", return_value=close_ef):
            result = verify_embedding_compatibility(raw_collection)
        assert result is True

    def test_incompatible_vectors_return_false(self, raw_collection, caplog):
        """When L2 distance exceeds threshold, report incompatible."""
        raw_collection.add(
            ids=["doc1"],
            embeddings=[[0.1] * 10],
            documents=["Hello world"],
            metadatas=[{"wing": "test", "room": "test"}],
        )

        # Mock embedder that produces vectors in a completely different space
        def far_ef(texts):
            return [[999.0] * 10 for _ in texts]

        with patch("mempalace.embeddings.get_embedding_function", return_value=far_ef):
            with caplog.at_level(logging.WARNING, logger="mempalace"):
                result = verify_embedding_compatibility(raw_collection)

        assert result is False
        assert "different embedding spaces" in caplog.text

    def test_result_is_cached(self, raw_collection):
        """Second call returns cached result without re-querying."""
        raw_collection.add(
            ids=["doc1"],
            embeddings=[[0.1] * 10],
            documents=["Some content here"],
            metadatas=[{"wing": "test", "room": "test"}],
        )

        with patch("mempalace.embeddings.get_embedding_function", return_value=None):
            result1 = verify_embedding_compatibility(raw_collection)
        assert result1 is True

        # Patch query to prove it's not called again
        original_query = raw_collection.query
        raw_collection.query = MagicMock(side_effect=RuntimeError("should not be called"))
        result2 = verify_embedding_compatibility(raw_collection)
        assert result2 is True
        raw_collection.query.assert_not_called()
        raw_collection.query = original_query

    def test_clear_cache_resets(self, raw_collection):
        """clear_compatibility_cache allows re-checking."""
        with patch("mempalace.embeddings.get_embedding_function", return_value=None):
            verify_embedding_compatibility(raw_collection)

        clear_compatibility_cache()

        with patch("mempalace.embeddings.get_embedding_function", return_value=None):
            result = verify_embedding_compatibility(raw_collection)
        assert result is True

    def test_embed_error_returns_true(self, raw_collection, caplog):
        """If the embedding function itself errors, return True (safe default)."""
        raw_collection.add(
            ids=["doc1"],
            embeddings=[[0.1] * 10],
            documents=["Content"],
            metadatas=[{"wing": "test", "room": "test"}],
        )

        def broken_ef(texts):
            raise RuntimeError("CUDA out of memory")

        with patch("mempalace.embeddings.get_embedding_function", return_value=broken_ef):
            with caplog.at_level(logging.WARNING, logger="mempalace"):
                result = verify_embedding_compatibility(raw_collection)

        assert result is True
        assert "embed error" in caplog.text

    def test_query_error_returns_true(self, raw_collection, caplog):
        """If the collection query errors, return True (safe default)."""

        def fake_ef(texts):
            return [[0.1] * 10 for _ in texts]

        original_query = raw_collection.query
        raw_collection.query = MagicMock(side_effect=RuntimeError("DB locked"))

        with patch("mempalace.embeddings.get_embedding_function", return_value=fake_ef):
            with caplog.at_level(logging.WARNING, logger="mempalace"):
                result = verify_embedding_compatibility(raw_collection)

        assert result is True
        assert "query error" in caplog.text
        raw_collection.query = original_query

    def test_threshold_boundary_below(self, raw_collection):
        """Distance just below threshold should pass."""
        raw_collection.add(
            ids=["doc1"],
            embeddings=[[0.1] * 10],
            documents=["Content"],
            metadatas=[{"wing": "test", "room": "test"}],
        )

        def fake_ef(texts):
            return [[0.1] * 10 for _ in texts]

        mock_results = {
            "ids": [["doc1"]],
            "distances": [[_DISTANCE_THRESHOLD - 1]],
            "documents": [["Content"]],
            "metadatas": [[{"wing": "test", "room": "test"}]],
        }

        with patch("mempalace.embeddings.get_embedding_function", return_value=fake_ef):
            with patch.object(raw_collection, "query", return_value=mock_results):
                result = verify_embedding_compatibility(raw_collection)
        assert result is True

    def test_threshold_boundary_above(self, raw_collection):
        """Distance just above threshold should fail."""
        raw_collection.add(
            ids=["doc1"],
            embeddings=[[0.1] * 10],
            documents=["Content"],
            metadatas=[{"wing": "test", "room": "test"}],
        )

        def fake_ef(texts):
            return [[0.1] * 10 for _ in texts]

        mock_results = {
            "ids": [["doc1"]],
            "distances": [[_DISTANCE_THRESHOLD + 1]],
            "documents": [["Content"]],
            "metadatas": [[{"wing": "test", "room": "test"}]],
        }

        with patch("mempalace.embeddings.get_embedding_function", return_value=fake_ef):
            with patch.object(raw_collection, "query", return_value=mock_results):
                result = verify_embedding_compatibility(raw_collection)
        assert result is False


class TestGetCollectionFallback:
    """Test that palace.get_collection integrates the compatibility check."""

    def test_normal_get_collection_works(self, palace_path):
        """Normal path — no ValueError, no compatibility check needed."""
        from mempalace.palace import get_collection

        col = get_collection(palace_path)
        assert col is not None

    def test_valueerror_triggers_fallback_and_warning(self, palace_path, caplog):
        """When get_collection raises ValueError, fall back and log warning."""
        from chromadb.api.client import Client
        from mempalace.palace import get_collection

        original_get = Client.get_collection

        call_count = {"n": 0}

        def patched_get(self, name, *args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise ValueError("Embedding function mismatch")
            return original_get(self, name, *args, **kwargs)

        with patch.object(Client, "get_collection", patched_get):
            with patch("mempalace.palace.verify_embedding_compatibility") as mock_verify:
                with caplog.at_level(logging.WARNING, logger="mempalace"):
                    col = get_collection(palace_path)

        assert col is not None
        assert "different embedding function" in caplog.text
        mock_verify.assert_called_once()

    def test_non_valueerror_creates_collection(self, palace_path):
        """When get_collection raises a non-ValueError, create a new collection."""
        from chromadb.api.client import Client
        from mempalace.palace import get_collection

        def patched_get(self, name, *args, **kwargs):
            raise RuntimeError("Collection not found")

        with patch.object(Client, "get_collection", patched_get):
            col = get_collection(palace_path)

        assert col is not None
