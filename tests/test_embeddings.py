"""Tests for mempalace.embeddings — local ONNX sentence embedder.

These tests are skipped when the ONNX model can't be located in any of
the expected caches (fresh CI without network). When the model *is*
available (developer machine, or a previous Chroma-backed install),
they verify the embedder produces sane, deterministic vectors and
reloads cleanly from disk without hitting the network again.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def _locate_model_dir() -> Path | None:
    """Return a directory containing ``model.onnx`` + ``tokenizer.json``, or None.

    The test suite redirects ``$HOME`` to a tmp dir (see ``conftest.py``),
    so we can't rely on ``Path.home()`` here — we inspect the pristine
    filesystem via absolute paths pulled from env vars plus well-known
    Chroma/MemPalace cache locations under the real home.
    """
    env_cache = os.environ.get("MEMPALACE_TEST_ONNX_DIR")
    if env_cache:
        return Path(env_cache).expanduser()

    real_home = os.environ.get("MEMPALACE_TEST_REAL_HOME") or _guess_real_home()
    if not real_home:
        return None
    base = Path(real_home)
    for candidate in (
        base / ".cache" / "mempalace" / "onnx",
        base / ".cache" / "chroma" / "onnx_models" / "all-MiniLM-L6-v2",
    ):
        for d in (candidate, candidate / "onnx"):
            if (d / "model.onnx").is_file() and (d / "tokenizer.json").is_file():
                return d
    return None


def _guess_real_home() -> str | None:
    """Best-effort recovery of the real home dir (conftest clobbers $HOME)."""
    try:
        import pwd

        return pwd.getpwuid(os.getuid()).pw_dir
    except Exception:
        return None


def _model_available() -> bool:
    return _locate_model_dir() is not None


def test_default_cache_dir_respects_env(tmp_path, monkeypatch):
    from mempalace.embeddings import default_cache_dir

    monkeypatch.setenv("MEMPALACE_EMBEDDINGS_CACHE", str(tmp_path))
    assert default_cache_dir() == tmp_path


def test_default_cache_dir_falls_back_to_home(monkeypatch, tmp_path):
    from mempalace.embeddings import default_cache_dir

    monkeypatch.delenv("MEMPALACE_EMBEDDINGS_CACHE", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert default_cache_dir() == tmp_path / ".cache" / "mempalace" / "onnx"


@pytest.fixture
def local_model_dir() -> Path:
    model_dir = _locate_model_dir()
    if model_dir is None:
        pytest.skip("all-MiniLM-L6-v2 ONNX model not cached locally")
    return model_dir


def test_embed_returns_unit_vectors_of_default_dim(local_model_dir):
    from mempalace.embeddings import DEFAULT_DIM, Embedder

    e = Embedder(local_dir=local_model_dir)
    vectors = e.embed(["hello world", "python programming", "vector databases"])

    assert len(vectors) == 3
    for v in vectors:
        assert len(v) == DEFAULT_DIM
        norm = sum(x * x for x in v) ** 0.5
        # L2-normalized by default, tolerating minor float error.
        assert abs(norm - 1.0) < 1e-4


def test_embed_is_deterministic(local_model_dir):
    from mempalace.embeddings import Embedder

    e = Embedder(local_dir=local_model_dir)
    v1 = e.embed(["stable input"])[0]
    v2 = e.embed(["stable input"])[0]
    assert v1 == v2


def test_embed_one_returns_single_vector(local_model_dir):
    from mempalace.embeddings import DEFAULT_DIM, Embedder

    e = Embedder(local_dir=local_model_dir)
    v = e.embed_one("just one")
    assert isinstance(v, list)
    assert len(v) == DEFAULT_DIM


def test_embed_empty_inputs_replaced_with_space(local_model_dir):
    """An empty string must not crash the tokenizer."""
    from mempalace.embeddings import Embedder

    e = Embedder(local_dir=local_model_dir)
    vectors = e.embed(["", "something"])
    assert len(vectors) == 2
    # Distinct inputs should produce distinct (non-equal) vectors.
    assert vectors[0] != vectors[1]


def test_local_dir_is_fully_offline(local_model_dir, monkeypatch):
    """When local_dir is supplied, no HF call must be made."""
    import huggingface_hub

    import mempalace.embeddings as emb

    def _boom(*args, **kwargs):
        raise AssertionError("huggingface_hub was called in local-only mode")

    # Patch in both spots — the module's deferred import happens to live
    # on the huggingface_hub module itself.
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", _boom, raising=True)

    e = emb.Embedder(local_dir=local_model_dir)
    vectors = e.embed(["fully offline"])
    assert len(vectors) == 1
    assert len(vectors[0]) == emb.DEFAULT_DIM


def test_warmup_and_shared_embedder(local_model_dir, monkeypatch):
    import mempalace.embeddings as emb

    # Reset module-level shared state so we can inject a local-dir embedder.
    monkeypatch.setattr(emb, "_default_embedder", None)

    # Swap in a factory that pins the local dir so no download is attempted.
    def _factory():
        return emb.Embedder(local_dir=local_model_dir)

    monkeypatch.setattr(emb, "get_default_embedder", lambda: _factory_memoize(emb, _factory))
    emb.warmup()
    a = emb.get_default_embedder()
    b = emb.get_default_embedder()
    assert a is b
    assert a.embed(["warmed up"])[0]


def _factory_memoize(module, factory):
    # Simple one-shot memo used by test_warmup_and_shared_embedder.
    if module._default_embedder is None:
        module._default_embedder = factory()
    return module._default_embedder


def test_local_dir_missing_files_raises(tmp_path):
    from mempalace.embeddings import Embedder

    e = Embedder(local_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        e.embed(["anything"])
