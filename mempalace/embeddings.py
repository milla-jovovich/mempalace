"""Local, offline sentence embeddings for MemPalace.

Wraps the same ONNX-exported ``sentence-transformers/all-MiniLM-L6-v2``
model ChromaDB uses by default (384-dim, cosine space). The model is
downloaded once from Hugging Face on first use and cached on disk; all
later calls run fully offline.

This module exists so non-Chroma backends (e.g. Milvus Lite) can match
Chroma's default embedding space without pulling in ChromaDB itself, and
without introducing any API-key dependency — a hard MemPalace rule.

Heavy third-party imports (``onnxruntime``, ``huggingface_hub``,
``tokenizers``, ``numpy``) are deferred until the first ``Embedder()``
construction so importing :mod:`mempalace.embeddings` from a Chroma-only
install has no side effects.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Iterable, List, Optional

logger = logging.getLogger(__name__)


# --- constants --------------------------------------------------------------

# Chroma's default embedder. Matching model + tokenizer + pooling keeps
# existing palace vectors compatible with Milvus-backed collections.
DEFAULT_MODEL_REPO = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_ONNX_FILENAME = "onnx/model.onnx"
DEFAULT_DIM = 384
DEFAULT_MAX_SEQ_LENGTH = 256
DEFAULT_BATCH_SIZE = 32


def default_cache_dir() -> Path:
    """Return the platform-appropriate ONNX model cache directory."""
    env = os.environ.get("MEMPALACE_EMBEDDINGS_CACHE")
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    return base / "mempalace" / "onnx"


# --- helpers ----------------------------------------------------------------


def _mean_pool(last_hidden, attention_mask):
    """Mean-pool token embeddings using the attention mask.

    ``last_hidden`` shape: (batch, seq_len, hidden). Mask shape: (batch,
    seq_len). Padding tokens are zeroed out before averaging.
    """
    import numpy as np  # deferred

    mask = attention_mask.astype(last_hidden.dtype)[..., None]
    summed = (last_hidden * mask).sum(axis=1)
    counts = np.clip(mask.sum(axis=1), a_min=1e-9, a_max=None)
    return summed / counts


def _l2_normalize(vectors):
    import numpy as np  # deferred

    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.clip(norms, a_min=1e-12, a_max=None)
    return vectors / norms


# --- Embedder ---------------------------------------------------------------


class Embedder:
    """Local ONNX sentence embedder — drop-in for Chroma's default model.

    Parameters
    ----------
    model_repo:
        Hugging Face repo id. Defaults to ``sentence-transformers/all-MiniLM-L6-v2``.
    onnx_filename:
        Path (within the repo) to the ONNX export. Defaults to ``onnx/model.onnx``.
    cache_dir:
        Where to cache the downloaded files. Defaults to
        ``~/.cache/mempalace/onnx`` (or ``$MEMPALACE_EMBEDDINGS_CACHE``).
    local_dir:
        Optional explicit directory containing a pre-downloaded copy of
        ``model.onnx`` + ``tokenizer.json``. When set, no network access
        is attempted at all.
    max_seq_length:
        Truncation length passed to the tokenizer.
    """

    def __init__(
        self,
        model_repo: str = DEFAULT_MODEL_REPO,
        onnx_filename: str = DEFAULT_ONNX_FILENAME,
        cache_dir: Optional[Path] = None,
        local_dir: Optional[Path] = None,
        max_seq_length: int = DEFAULT_MAX_SEQ_LENGTH,
    ):
        self.model_repo = model_repo
        self.onnx_filename = onnx_filename
        self.cache_dir = Path(cache_dir) if cache_dir else default_cache_dir()
        self.local_dir = Path(local_dir).expanduser() if local_dir else None
        self.max_seq_length = max_seq_length
        self._session = None
        self._tokenizer = None
        self._input_names: Optional[List[str]] = None
        self._lock = threading.Lock()

    # -- lazy initialization ---------------------------------------------

    def _ensure_ready(self) -> None:
        if self._session is not None and self._tokenizer is not None:
            return
        with self._lock:
            if self._session is not None and self._tokenizer is not None:
                return
            onnx_path, tokenizer_path = self._resolve_files()
            self._load(onnx_path, tokenizer_path)

    def _find_local_files(self, base: Path):
        """Look for ``model.onnx`` + ``tokenizer.json`` under ``base``.

        ``base`` may point at the ONNX directory directly or at a parent
        that contains an ``onnx/`` subfolder (matching Chroma's layout).
        Returns ``(onnx_path, tokenizer_path)`` or ``(None, None)``.
        """
        if not base.is_dir():
            return None, None
        candidates = [base, base / "onnx"]
        for cand in candidates:
            onnx = cand / "model.onnx"
            tok = cand / "tokenizer.json"
            if onnx.is_file() and tok.is_file():
                return onnx, tok
        return None, None

    def _resolve_files(self):
        """Return paths to ``model.onnx`` and ``tokenizer.json``.

        Resolution order:
            1. ``local_dir`` (if the caller passed one — never touches network)
            2. existing MemPalace cache
            3. existing ChromaDB cache (same model, same files)
            4. download from Hugging Face into MemPalace cache
        """
        if self.local_dir is not None:
            onnx, tok = self._find_local_files(self.local_dir)
            if onnx and tok:
                return onnx, tok
            raise FileNotFoundError(
                f"Embedder(local_dir={self.local_dir!s}) — could not find "
                "model.onnx + tokenizer.json in that directory or its onnx/ subfolder."
            )

        onnx, tok = self._find_local_files(self.cache_dir)
        if onnx and tok:
            return onnx, tok

        chroma_cache = Path.home() / ".cache" / "chroma" / "onnx_models" / "all-MiniLM-L6-v2"
        onnx, tok = self._find_local_files(chroma_cache)
        if onnx and tok:
            return onnx, tok

        return self._download()

    def _download(self):
        from huggingface_hub import hf_hub_download  # deferred

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.cache_dir, 0o700)
        except (OSError, NotImplementedError):
            pass

        required = [self.onnx_filename, "tokenizer.json", "tokenizer_config.json"]
        optional = ["vocab.txt", "special_tokens_map.json"]
        downloaded: dict = {}
        for fname in required:
            downloaded[fname] = hf_hub_download(
                repo_id=self.model_repo,
                filename=fname,
                cache_dir=str(self.cache_dir),
            )
        for fname in optional:
            try:
                hf_hub_download(
                    repo_id=self.model_repo,
                    filename=fname,
                    cache_dir=str(self.cache_dir),
                )
            except Exception:
                pass
        return Path(downloaded[self.onnx_filename]), Path(downloaded["tokenizer.json"])

    def _load(self, onnx_path: Path, tokenizer_path: Path) -> None:
        import onnxruntime  # deferred
        from tokenizers import Tokenizer  # deferred

        session_options = onnxruntime.SessionOptions()
        session_options.log_severity_level = 3  # errors only; keep stdout clean
        self._session = onnxruntime.InferenceSession(
            str(onnx_path),
            sess_options=session_options,
            providers=["CPUExecutionProvider"],
        )
        self._input_names = [i.name for i in self._session.get_inputs()]
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._tokenizer.enable_truncation(max_length=self.max_seq_length)
        self._tokenizer.enable_padding(length=None)

    # -- encoding --------------------------------------------------------

    def embed(
        self,
        texts: Iterable[str],
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        normalize: bool = True,
    ) -> List[List[float]]:
        """Encode ``texts`` to 384-d float vectors.

        Empty / non-string inputs are replaced with a single space so the
        tokenizer never sees an empty sequence. Output order matches input
        order.
        """
        import numpy as np  # deferred

        self._ensure_ready()
        cleaned = [t if isinstance(t, str) and t else " " for t in texts]
        if not cleaned:
            return []

        out: List[List[float]] = []
        for start in range(0, len(cleaned), batch_size):
            batch = cleaned[start : start + batch_size]
            encodings = self._tokenizer.encode_batch(batch)
            input_ids = np.asarray([e.ids for e in encodings], dtype=np.int64)
            attention_mask = np.asarray([e.attention_mask for e in encodings], dtype=np.int64)
            feeds: dict = {}
            for name in self._input_names or []:
                if name == "input_ids":
                    feeds[name] = input_ids
                elif name == "attention_mask":
                    feeds[name] = attention_mask
                elif name == "token_type_ids":
                    feeds[name] = np.zeros_like(input_ids)

            outputs = self._session.run(None, feeds)
            last_hidden = outputs[0]
            pooled = _mean_pool(last_hidden, attention_mask)
            if normalize:
                pooled = _l2_normalize(pooled)
            out.extend(pooled.astype(np.float32).tolist())
        return out

    def embed_one(self, text: str) -> List[float]:
        return self.embed([text])[0]

    @property
    def dim(self) -> int:
        return DEFAULT_DIM


# --- public one-shots -------------------------------------------------------


_default_embedder: Optional[Embedder] = None
_default_lock = threading.Lock()


def get_default_embedder() -> Embedder:
    """Return a process-wide shared :class:`Embedder` (lazily constructed)."""
    global _default_embedder
    if _default_embedder is not None:
        return _default_embedder
    with _default_lock:
        if _default_embedder is None:
            _default_embedder = Embedder()
        return _default_embedder


def warmup() -> None:
    """Prime the default embedder so subsequent calls are fully offline.

    Callers who want to guarantee no network traffic after initialization
    should invoke this once during startup. After ``warmup()`` returns,
    the ONNX model and tokenizer files are cached locally and the model
    is loaded in-memory.
    """
    get_default_embedder()._ensure_ready()


def embed(texts: Iterable[str]) -> List[List[float]]:
    """Shortcut around :meth:`Embedder.embed` using the shared instance."""
    return get_default_embedder().embed(texts)
