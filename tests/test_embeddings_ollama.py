"""Tests for the env-gated Ollama embedding function path.

These exercise ``get_embedding_function`` / ``_ef_kwargs`` / ``_parse_timeout``
without requiring a running Ollama server — we only inspect the returned
object's configuration and the kwargs dict contents.
"""

import pytest

from mempalace.backends import chroma as chroma_backend
from mempalace.backends.chroma import (
    _ef_kwargs,
    _parse_timeout,
    get_embedding_function,
)


@pytest.fixture
def clean_env(monkeypatch):
    for key in (
        "EMBEDDING_PROVIDER",
        "OLLAMA_URL",
        "OLLAMA_EMBED_MODEL",
        "OLLAMA_EMBED_TIMEOUT",
    ):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


# ---------------------------------------------------------------------------
# get_embedding_function
# ---------------------------------------------------------------------------


def test_returns_none_when_env_unset(clean_env):
    assert get_embedding_function() is None


@pytest.mark.parametrize("value", ["", "  ", "chroma", "openai", "nomic"])
def test_returns_none_for_non_ollama_provider(clean_env, value):
    clean_env.setenv("EMBEDDING_PROVIDER", value)
    assert get_embedding_function() is None


@pytest.mark.parametrize("value", ["ollama", "OLLAMA", " Ollama ", "\tollama\n"])
def test_enabled_variants_normalize(clean_env, value):
    clean_env.setenv("EMBEDDING_PROVIDER", value)
    ef = get_embedding_function()
    assert ef is not None
    assert type(ef).__name__ == "OllamaEmbeddingFunction"


def test_defaults_when_only_provider_set(clean_env):
    clean_env.setenv("EMBEDDING_PROVIDER", "ollama")
    ef = get_embedding_function()
    assert ef is not None
    assert ef.model_name == "nomic-embed-text"
    assert ef.timeout == 60
    # url is exposed both as self.url and self._base_url (backcompat slot)
    assert ef._base_url == "http://localhost:11434"


def test_env_overrides_url_model_timeout(clean_env):
    clean_env.setenv("EMBEDDING_PROVIDER", "ollama")
    clean_env.setenv("OLLAMA_URL", "  http://gpu-host:11435  ")
    clean_env.setenv("OLLAMA_EMBED_MODEL", "  snowflake-arctic-embed  ")
    clean_env.setenv("OLLAMA_EMBED_TIMEOUT", "  120  ")
    ef = get_embedding_function()
    assert ef is not None
    assert ef._base_url == "http://gpu-host:11435"
    assert ef.model_name == "snowflake-arctic-embed"
    assert ef.timeout == 120


def test_bad_timeout_raises_clear_error(clean_env):
    clean_env.setenv("EMBEDDING_PROVIDER", "ollama")
    clean_env.setenv("OLLAMA_EMBED_TIMEOUT", "not-a-number")
    with pytest.raises(ValueError, match="OLLAMA_EMBED_TIMEOUT"):
        get_embedding_function()


# ---------------------------------------------------------------------------
# _parse_timeout
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    (None, 60),
    ("", 60),
    ("   ", 60),
    ("30", 30),
    ("  45  ", 45),
    (90, 90),
])
def test_parse_timeout_accepts_valid(raw, expected):
    assert _parse_timeout(raw) == expected


@pytest.mark.parametrize("raw", ["abc", "3.5", "12s", "-"])
def test_parse_timeout_rejects_invalid(raw):
    with pytest.raises(ValueError, match="OLLAMA_EMBED_TIMEOUT"):
        _parse_timeout(raw)


# ---------------------------------------------------------------------------
# _ef_kwargs
# ---------------------------------------------------------------------------


def test_ef_kwargs_empty_when_disabled(clean_env):
    assert _ef_kwargs() == {}


def test_ef_kwargs_contains_embedding_function_when_enabled(clean_env):
    clean_env.setenv("EMBEDDING_PROVIDER", "ollama")
    kwargs = _ef_kwargs()
    assert set(kwargs) == {"embedding_function"}
    assert kwargs["embedding_function"] is not None


def test_ef_kwargs_spread_is_noop_on_default_path(clean_env):
    """Spreading {} into a call adds no kwargs — the key invariant."""
    assert {**_ef_kwargs(), "metadata": {"x": 1}} == {"metadata": {"x": 1}}


# ---------------------------------------------------------------------------
# Integration hook: ensure the helper sees monkeypatched env without
# requiring a module reload (no globals cached at import).
# ---------------------------------------------------------------------------


def test_no_cached_state_between_calls(clean_env):
    clean_env.setenv("EMBEDDING_PROVIDER", "ollama")
    ef1 = get_embedding_function()
    clean_env.delenv("EMBEDDING_PROVIDER")
    ef2 = get_embedding_function()
    assert ef1 is not None
    assert ef2 is None


def test_module_exports_public_helpers():
    assert callable(chroma_backend.get_embedding_function)
    assert callable(chroma_backend._ef_kwargs)
    assert callable(chroma_backend._parse_timeout)
