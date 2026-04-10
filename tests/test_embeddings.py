"""Tests for the embeddings module — pluggable vectorizers."""

import numpy as np
import pytest
from unittest.mock import patch, MagicMock

from mempalace.embeddings import (
    OnnxEmbedder,
    SentenceTransformerEmbedder,
    OllamaEmbedder,
    get_embedder,
    resolve_model_name,
    list_embedders,
    MODEL_ALIASES,
)

_st_available = True
try:
    import sentence_transformers  # noqa: F401
except ImportError:
    _st_available = False

st_required = pytest.mark.skipif(not _st_available, reason="sentence-transformers not installed")


# ── Model aliases ──────────────────────────────────────────────────────


def test_resolve_known_alias():
    assert resolve_model_name("bge-small") == "BAAI/bge-small-en-v1.5"
    assert resolve_model_name("minilm") == "all-MiniLM-L6-v2"
    assert resolve_model_name("nomic") == "nomic-ai/nomic-embed-text-v1.5"


def test_resolve_unknown_passes_through():
    assert resolve_model_name("my-custom-model") == "my-custom-model"
    assert resolve_model_name("all-MiniLM-L6-v2") == "all-MiniLM-L6-v2"


def test_all_aliases_have_entries():
    embedders = list_embedders()
    aliases = {e["alias"] for e in embedders}
    for alias in MODEL_ALIASES:
        assert alias in aliases, f"Alias {alias} not in list_embedders()"


# ── SentenceTransformerEmbedder ────────────────────────────────────────


def test_st_embedder_properties():
    e = SentenceTransformerEmbedder(model_name="test-model", device="cpu")
    assert e.model_name == "test-model"


def test_st_embedder_lazy_load():
    """Model is not loaded until embed() or dimension is called."""
    e = SentenceTransformerEmbedder(model_name="test-model")
    assert e._model is None  # not loaded yet


@st_required
def test_st_embedder_embed():
    """Integration test — actually loads the default model."""
    e = SentenceTransformerEmbedder()
    result = e.embed(["hello world", "test sentence"])
    assert len(result) == 2
    assert len(result[0]) == 384  # MiniLM dimension
    assert all(isinstance(x, float) for x in result[0])


@st_required
def test_st_embedder_dimension():
    e = SentenceTransformerEmbedder()
    assert e.dimension == 384


# ── OllamaEmbedder ────────────────────────────────────────────────────


def test_ollama_embedder_properties():
    e = OllamaEmbedder(model="test-model", base_url="http://myserver:11434")
    assert e.model_name == "ollama/test-model"


def test_ollama_embedder_connection_error():
    """OllamaEmbedder raises ConnectionError when server unreachable."""
    e = OllamaEmbedder(base_url="http://127.0.0.1:9", timeout=1.0)
    with pytest.raises(ConnectionError, match="Cannot reach Ollama"):
        e.embed(["test"])


def test_ollama_embedder_embed_mock():
    """Test Ollama embedding with mocked HTTP response."""
    import json

    fake_response = json.dumps({"embeddings": [[0.1, 0.2, 0.3]]}).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = fake_response
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        e = OllamaEmbedder(model="test-model")
        result = e.embed(["hello"])

    assert result == [[0.1, 0.2, 0.3]]
    assert e.dimension == 3


def test_ollama_embedder_no_embeddings_error():
    """OllamaEmbedder raises ValueError when Ollama returns empty."""
    import json

    fake_response = json.dumps({"embeddings": []}).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = fake_response
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        e = OllamaEmbedder(model="missing-model")
        with pytest.raises(ValueError, match="no embeddings"):
            e.embed(["hello"])


# ── OnnxEmbedder ──────────────────────────────────────────────────────


def test_onnx_embedder_properties():
    e = OnnxEmbedder()
    assert e.model_name == "all-MiniLM-L6-v2"


def test_onnx_embedder_lazy_load():
    """ONNX session and tokenizer are not loaded until embed() or dimension is called."""
    e = OnnxEmbedder()
    assert e._session is None
    assert e._tokenizer is None


def test_onnx_embedder_embed():
    e = OnnxEmbedder()
    result = e.embed(["hello world", "test sentence"])
    assert len(result) == 2
    assert len(result[0]) == 384
    assert all(isinstance(x, float) for x in result[0])


def test_onnx_embedder_dimension():
    e = OnnxEmbedder()
    assert e.dimension == 384


def test_onnx_embedder_output_normalized():
    """ONNX embedder output vectors must be unit length."""
    e = OnnxEmbedder()
    result = e.embed(["normalization check"])
    norm = np.linalg.norm(result[0])
    assert abs(norm - 1.0) < 1e-5


def test_onnx_embedder_batch():
    """ONNX embedder handles batches larger than internal batch size."""
    e = OnnxEmbedder()
    texts = [f"document number {i}" for i in range(50)]
    result = e.embed(texts)
    assert len(result) == 50
    assert all(len(v) == 384 for v in result)


def test_onnx_embedder_deterministic():
    """Same input produces identical output across calls."""
    e = OnnxEmbedder()
    r1 = e.embed(["reproducibility test"])
    r2 = e.embed(["reproducibility test"])
    assert r1 == r2


def test_onnx_embedder_missing_onnxruntime():
    with patch.dict("sys.modules", {"onnxruntime": None}):
        e = OnnxEmbedder()
        with pytest.raises(ImportError, match="onnxruntime"):
            e.embed(["test"])


def test_onnx_embedder_missing_tokenizers():
    with patch.dict("sys.modules", {"tokenizers": None}):
        e = OnnxEmbedder()
        with pytest.raises(ImportError, match="tokenizers"):
            e.embed(["test"])


# ── get_embedder factory ──────────────────────────────────────────────


def test_get_embedder_default():
    e = get_embedder()
    assert isinstance(e, OnnxEmbedder)
    assert e.model_name == "all-MiniLM-L6-v2"


def test_get_embedder_explicit_onnx():
    e = get_embedder({"embedder": "all-MiniLM-L6-v2"})
    assert isinstance(e, OnnxEmbedder)


def test_get_embedder_gpu_device_uses_st():
    """Requesting cuda/mps device routes to SentenceTransformerEmbedder."""
    e = get_embedder({"embedder": "all-MiniLM-L6-v2", "embedder_options": {"device": "cuda"}})
    assert isinstance(e, SentenceTransformerEmbedder)


def test_get_embedder_by_alias():
    """Non-default HF models route to SentenceTransformerEmbedder."""
    e = get_embedder({"embedder": "bge-small"})
    assert isinstance(e, SentenceTransformerEmbedder)
    assert e.model_name == "BAAI/bge-small-en-v1.5"


def test_get_embedder_ollama():
    e = get_embedder(
        {
            "embedder": "ollama",
            "embedder_options": {"model": "nomic-embed-text", "base_url": "http://myserver:11434"},
        }
    )
    assert isinstance(e, OllamaEmbedder)
    assert e.model_name == "ollama/nomic-embed-text"


def test_get_embedder_caching():
    """Same config returns same cached instance."""
    e1 = get_embedder({"embedder": "all-MiniLM-L6-v2"})
    e2 = get_embedder({"embedder": "all-MiniLM-L6-v2"})
    assert e1 is e2


def test_get_embedder_different_configs():
    """Different configs return different instances."""
    e1 = get_embedder({"embedder": "all-MiniLM-L6-v2"})
    e2 = get_embedder({"embedder": "bge-small"})
    assert e1 is not e2


# ── list_embedders ────────────────────────────────────────────────────


def test_list_embedders_returns_list():
    result = list_embedders()
    assert isinstance(result, list)
    assert len(result) >= 5
    for e in result:
        assert "name" in e
        assert "alias" in e
        assert "dim" in e
        assert "backend" in e
        assert "notes" in e


# ── embedding_model tracking in db.py ─────────────────────────────────


def test_embedding_model_stored_in_metadata(tmp_path):
    """Verify the embedding model name is stored in each record's metadata."""
    from mempalace.db import open_collection

    col = open_collection(str(tmp_path / "palace"), backend="lance")
    col.upsert(
        documents=["test document"],
        ids=["t1"],
        metadatas=[{"wing": "test", "room": "general", "source_file": ""}],
    )

    result = col.get(ids=["t1"], include=["metadatas"])
    meta = result["metadatas"][0]
    assert "embedding_model" in meta
    # Default embedder is now OnnxEmbedder, same model name
    assert meta["embedding_model"] == "all-MiniLM-L6-v2"


def test_lance_dimension_mismatch_guard(tmp_path):
    """Reopening a LanceDB collection with a different embedder dimension must fail."""
    from mempalace.db import open_collection

    class FakeEmbedder384:
        model_name = "fake-384"
        dimension = 384
        def embed(self, texts):
            return [[0.0] * 384 for _ in texts]

    class FakeEmbedder768:
        model_name = "fake-768"
        dimension = 768
        def embed(self, texts):
            return [[0.0] * 768 for _ in texts]

    palace = str(tmp_path / "palace")
    col = open_collection(palace, backend="lance", embedder=FakeEmbedder384())
    col.upsert(documents=["seed"], ids=["s1"], metadatas=[{"wing": "t", "room": "r", "source_file": ""}])
    assert col.count() == 1

    with pytest.raises(RuntimeError, match="dimension"):
        open_collection(palace, backend="lance", embedder=FakeEmbedder768())


def test_lance_node_id_seq_are_filterable_columns(tmp_path):
    """node_id and seq must be top-level LanceDB columns, not buried in metadata_json."""
    from mempalace.db import open_collection

    palace = str(tmp_path / "palace")
    col = open_collection(palace, backend="lance")
    col.upsert(
        documents=["doc one", "doc two"],
        ids=["d1", "d2"],
        metadatas=[
            {"wing": "w", "room": "r", "source_file": "", "node_id": "aaa", "seq": 1},
            {"wing": "w", "room": "r", "source_file": "", "node_id": "bbb", "seq": 5},
        ],
    )

    # Filter by node_id — only works if it's a real column
    result = col.get(where={"node_id": "bbb"}, include=["metadatas"])
    assert len(result["ids"]) == 1
    assert result["ids"][0] == "d2"

    # Filter by seq with $gt — only works if it's a real column
    result = col.get(where={"seq": {"$gt": 2}}, include=["metadatas"])
    assert len(result["ids"]) == 1
    assert result["ids"][0] == "d2"
