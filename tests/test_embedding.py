import os
from unittest.mock import MagicMock, patch

from mempalace.config import MempalaceConfig
from mempalace.embedding import (
    DEFAULT_MODEL,
    NEW_PALACE_MODEL,
    get_embedding_function,
    new_palace_model,
    resolve_model_from_metadata,
)


def test_default_model_is_miniLM():
    assert DEFAULT_MODEL == "all-MiniLM-L6-v2"


def test_new_palace_model_is_mpnet():
    assert NEW_PALACE_MODEL == "all-mpnet-base-v2"


def test_resolve_from_metadata_returns_stored_model():
    metadata = {"hnsw:space": "cosine", "embedding_model": "custom-model-v1"}
    assert resolve_model_from_metadata(metadata) == "custom-model-v1"


def test_resolve_from_metadata_returns_default_when_absent():
    metadata = {"hnsw:space": "cosine"}
    assert resolve_model_from_metadata(metadata) == DEFAULT_MODEL


def test_resolve_from_metadata_handles_none():
    assert resolve_model_from_metadata(None) == DEFAULT_MODEL


def test_resolve_from_metadata_handles_empty_dict():
    assert resolve_model_from_metadata({}) == DEFAULT_MODEL


def test_new_palace_model_returns_mpnet_by_default():
    os.environ.pop("MEMPALACE_EMBEDDING_MODEL", None)
    assert new_palace_model() == NEW_PALACE_MODEL


def test_new_palace_model_respects_env_var(monkeypatch):
    monkeypatch.setenv("MEMPALACE_EMBEDDING_MODEL", "my-custom-model")
    assert new_palace_model() == "my-custom-model"


def test_get_embedding_function_returns_callable():
    mock_ef_class = MagicMock()
    mock_ef_instance = MagicMock()
    mock_ef_class.return_value = mock_ef_instance
    with patch(
        "chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction",
        mock_ef_class,
    ):
        ef = get_embedding_function(DEFAULT_MODEL)
        assert callable(ef)
        mock_ef_class.assert_called_once_with(model_name=DEFAULT_MODEL)


def test_config_embedding_model_default(tmp_path):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text("{}")
    config = MempalaceConfig(config_dir=str(cfg_dir))
    assert config.embedding_model == NEW_PALACE_MODEL


def test_config_embedding_model_from_file(tmp_path):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text('{"embedding_model": "custom-model"}')
    config = MempalaceConfig(config_dir=str(cfg_dir))
    assert config.embedding_model == "custom-model"


def test_new_palace_model_respects_config(tmp_path):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text('{"embedding_model": "config-model"}')
    config = MempalaceConfig(config_dir=str(cfg_dir))
    os.environ.pop("MEMPALACE_EMBEDDING_MODEL", None)
    assert new_palace_model(config) == "config-model"
