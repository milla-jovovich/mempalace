"""Extra tests for mempalace.config to cover remaining gaps."""

import json
import os

from mempalace.config import (
    MempalaceConfig,
    get_embedding_function,
    _embedding_fn_cache,
    _create_embedding_function,
)


def test_config_bad_json(tmp_path):
    """Bad JSON in config file falls back to empty."""
    (tmp_path / "config.json").write_text("not json", encoding="utf-8")
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    assert cfg.palace_path  # still returns default


def test_people_map_from_file(tmp_path):
    (tmp_path / "people_map.json").write_text(json.dumps({"bob": "Robert"}), encoding="utf-8")
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    assert cfg.people_map == {"bob": "Robert"}


def test_people_map_bad_json(tmp_path):
    (tmp_path / "people_map.json").write_text("bad", encoding="utf-8")
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    assert cfg.people_map == {}


def test_people_map_missing(tmp_path):
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    assert cfg.people_map == {}


def test_topic_wings_default(tmp_path):
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    assert isinstance(cfg.topic_wings, list)
    assert "emotions" in cfg.topic_wings


def test_hall_keywords_default(tmp_path):
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    assert isinstance(cfg.hall_keywords, dict)
    assert "technical" in cfg.hall_keywords


def test_init_idempotent(tmp_path):
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    cfg.init()
    cfg.init()  # second call should not overwrite
    with open(tmp_path / "config.json") as f:
        data = json.load(f)
    assert "palace_path" in data


def test_save_people_map(tmp_path):
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    result = cfg.save_people_map({"alice": "Alice Smith"})
    assert result.exists()
    with open(result) as f:
        data = json.load(f)
    assert data["alice"] == "Alice Smith"


def test_env_mempal_palace_path(tmp_path):
    """MEMPAL_PALACE_PATH (legacy) should also work."""
    os.environ.pop("MEMPALACE_PALACE_PATH", None)
    os.environ["MEMPAL_PALACE_PATH"] = "/legacy/path"
    try:
        cfg = MempalaceConfig(config_dir=str(tmp_path))
        assert cfg.palace_path == "/legacy/path"
    finally:
        del os.environ["MEMPAL_PALACE_PATH"]


def test_collection_name_from_config(tmp_path):
    (tmp_path / "config.json").write_text(
        json.dumps({"collection_name": "custom_col"}), encoding="utf-8"
    )
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    assert cfg.collection_name == "custom_col"


# ── Embedding endpoint config ────────────────────────────────────────────


def test_embedding_endpoint_default(tmp_path):
    """No endpoint configured returns empty string."""
    os.environ.pop("MEMPALACE_EMBEDDING_ENDPOINT", None)
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    assert cfg.embedding_endpoint == ""


def test_embedding_endpoint_env_var(tmp_path):
    """MEMPALACE_EMBEDDING_ENDPOINT env var is respected."""
    os.environ["MEMPALACE_EMBEDDING_ENDPOINT"] = "http://gpu-server:11434"
    try:
        cfg = MempalaceConfig(config_dir=str(tmp_path))
        assert cfg.embedding_endpoint == "http://gpu-server:11434"
    finally:
        del os.environ["MEMPALACE_EMBEDDING_ENDPOINT"]


def test_embedding_endpoint_from_config(tmp_path):
    """embedding_endpoint from config.json is respected."""
    (tmp_path / "config.json").write_text(
        json.dumps({"embedding_endpoint": "http://custom:11434"}), encoding="utf-8"
    )
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    assert cfg.embedding_endpoint == "http://custom:11434"


# ── Ollama embedding function ────────────────────────────────────────────


def test_ollama_prefix_creates_ollama_function():
    """'ollama:model' prefix creates OllamaEmbeddingFunction."""
    ef = _create_embedding_function("ollama:nomic-embed-text", "http://localhost:11434")
    assert type(ef).__name__ == "OllamaEmbeddingFunction"


def test_ollama_default_url():
    """Ollama uses default URL when endpoint is empty."""
    ef = _create_embedding_function("ollama:nomic-embed-text", "")
    assert type(ef).__name__ == "OllamaEmbeddingFunction"


def test_ollama_custom_endpoint():
    """Ollama uses custom endpoint from config."""
    ef = _create_embedding_function("ollama:qwen3-embedding-8b", "http://gpu-box:11434")
    assert type(ef).__name__ == "OllamaEmbeddingFunction"


# ── Embedding function caching ───────────────────────────────────────────


def test_embedding_function_caching():
    """Same model returns cached instance."""
    _embedding_fn_cache.clear()
    ef1 = get_embedding_function("ollama:test-model")
    ef2 = get_embedding_function("ollama:test-model")
    assert ef1 is ef2
    assert len(_embedding_fn_cache) == 1
    _embedding_fn_cache.clear()


def test_embedding_function_different_models_not_cached():
    """Different models get different instances."""
    _embedding_fn_cache.clear()
    ef1 = get_embedding_function("ollama:model-a")
    ef2 = get_embedding_function("ollama:model-b")
    assert ef1 is not ef2
    assert len(_embedding_fn_cache) == 2
    _embedding_fn_cache.clear()
