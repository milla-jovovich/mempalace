"""
embeddings.py — Pluggable embedding backends for MemPalace.

Supported backends:
  - onnx: all-MiniLM-L6-v2 via ONNX Runtime (default, lightweight — no torch)
  - sentence-transformers: any HuggingFace model (requires `pip install mempalace[gpu]`)
  - ollama: any model served by a local/remote Ollama instance (no extra deps)

Config in ~/.mempalace/config.json:
    {}                                     — uses ONNX default
    {"embedder": "all-MiniLM-L6-v2"}       — same as default
    {"embedder": "bge-small"}              — requires [gpu]
    {"embedder": "all-MiniLM-L6-v2", "embedder_options": {"device": "cuda"}} — requires [gpu]
    {"embedder": "ollama", "embedder_options": {"model": "nomic-embed-text"}}
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger("mempalace")


# ── Protocol ──────────────────────────────────────────────────────────────────


@runtime_checkable
class Embedder(Protocol):
    """Protocol for embedding backends."""

    @property
    def dimension(self) -> int: ...

    @property
    def model_name(self) -> str: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


# ── ONNX (default, lightweight) ───────────────────────────────────────────────

_ONNX_MODEL_NAME = "all-MiniLM-L6-v2"
_ONNX_DOWNLOAD_URL = "https://chroma-onnx-models.s3.amazonaws.com/all-MiniLM-L6-v2/onnx.tar.gz"
_ONNX_SHA256 = "913d7300ceae3b2dbc2c50d1de4baacab4be7b9380491c27fab7418616a16ec3"
_ONNX_ARCHIVE = "onnx.tar.gz"
_ONNX_SUBDIR = "onnx"
_ONNX_REQUIRED_FILES = (
    "config.json", "model.onnx", "special_tokens_map.json",
    "tokenizer_config.json", "tokenizer.json", "vocab.txt",
)


def _onnx_model_dir() -> str:
    """Cache directory for the ONNX model files."""
    import os
    from pathlib import Path
    return str(Path(os.environ.get(
        "MEMPALACE_ONNX_CACHE",
        Path.home() / ".cache" / "mempalace" / "onnx_models" / _ONNX_MODEL_NAME,
    )) / _ONNX_SUBDIR)


def _ensure_onnx_model() -> str:
    """Download and extract the ONNX model if not already cached. Returns model dir."""
    import os
    import tarfile
    from pathlib import Path
    from urllib.request import urlopen, Request

    model_dir = _onnx_model_dir()
    if all(os.path.exists(os.path.join(model_dir, f)) for f in _ONNX_REQUIRED_FILES):
        return model_dir

    cache_root = str(Path(model_dir).parent)
    os.makedirs(cache_root, exist_ok=True)
    archive_path = os.path.join(cache_root, _ONNX_ARCHIVE)

    if not os.path.exists(archive_path) or not _verify_sha256(archive_path, _ONNX_SHA256):
        logger.info("Downloading ONNX model %s...", _ONNX_MODEL_NAME)
        req = Request(_ONNX_DOWNLOAD_URL)
        with urlopen(req) as resp, open(archive_path, "wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)

        if not _verify_sha256(archive_path, _ONNX_SHA256):
            os.remove(archive_path)
            raise RuntimeError(
                f"Downloaded ONNX model failed SHA256 verification. "
                f"Delete {cache_root} and retry."
            )

    with tarfile.open(archive_path, "r:gz") as tar:
        import sys
        if sys.version_info >= (3, 12):
            tar.extractall(path=cache_root, filter="data")
        else:
            tar.extractall(path=cache_root)

    return model_dir


def _verify_sha256(path: str, expected: str) -> bool:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8192), b""):
            h.update(block)
    return h.hexdigest() == expected


class OnnxEmbedder:
    """Embedding via ONNX Runtime — the default, lightweight backend.

    Uses the all-MiniLM-L6-v2 model converted to ONNX format.
    No torch or sentence-transformers required. The ONNX model (~87MB)
    is downloaded once on first use and cached in ~/.cache/mempalace/.
    """

    DIMENSION = 384
    MAX_SEQ_LENGTH = 256
    BATCH_SIZE = 32

    def __init__(self):
        self._session = None
        self._tokenizer = None

    @property
    def model_name(self) -> str:
        return _ONNX_MODEL_NAME

    @property
    def dimension(self) -> int:
        return self.DIMENSION

    def _load(self):
        if self._session is not None:
            return

        try:
            import onnxruntime as ort
        except ImportError:
            raise ImportError(
                "onnxruntime is required for the default embedder. "
                "Install with: pip install onnxruntime"
            )
        try:
            from tokenizers import Tokenizer
        except ImportError:
            raise ImportError(
                "tokenizers is required for the default embedder. "
                "Install with: pip install tokenizers"
            )

        import os
        model_dir = _ensure_onnx_model()

        so = ort.SessionOptions()
        so.log_severity_level = 3
        self._session = ort.InferenceSession(
            os.path.join(model_dir, "model.onnx"),
            providers=ort.get_available_providers(),
            sess_options=so,
        )

        self._tokenizer = Tokenizer.from_file(
            os.path.join(model_dir, "tokenizer.json")
        )
        self._tokenizer.enable_truncation(max_length=self.MAX_SEQ_LENGTH)
        self._tokenizer.enable_padding(
            pad_id=0, pad_token="[PAD]", length=self.MAX_SEQ_LENGTH,
        )
        logger.info("Loaded ONNX embedder: %s (%dd)", _ONNX_MODEL_NAME, self.DIMENSION)

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._load()
        import numpy as np

        all_embeddings = []
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i : i + self.BATCH_SIZE]
            encoded = [self._tokenizer.encode(t) for t in batch]
            input_ids = np.array([e.ids for e in encoded], dtype=np.int64)
            attention_mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
            token_type_ids = np.zeros_like(input_ids, dtype=np.int64)

            output = self._session.run(None, {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": token_type_ids,
            })

            last_hidden = output[0]
            mask_expanded = np.broadcast_to(
                np.expand_dims(attention_mask, -1).astype(np.float32),
                last_hidden.shape,
            )
            embeddings = np.sum(last_hidden * mask_expanded, axis=1) / np.clip(
                mask_expanded.sum(axis=1), a_min=1e-9, a_max=None,
            )
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            norms[norms == 0] = 1e-12
            embeddings = (embeddings / norms).astype(np.float32)
            all_embeddings.append(embeddings)

        return np.concatenate(all_embeddings).tolist()


# ── Sentence Transformers (requires [gpu] extra) ─────────────────────────────


class SentenceTransformerEmbedder:
    """Embedding via sentence-transformers library.

    Works with any HuggingFace model:
      - all-MiniLM-L6-v2 (384d) — fast, decent quality
      - BAAI/bge-small-en-v1.5 (384d) — best quality-at-size for English
      - BAAI/bge-base-en-v1.5 (768d) — higher quality, larger
      - intfloat/e5-base-v2 (768d) — good general purpose
      - nomic-ai/nomic-embed-text-v1.5 (768d) — Matryoshka dimensions
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", device: str = "cpu"):
        self._model_name = model_name
        self._device = device
        self._model = None
        self._dim = None

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        if self._dim is None:
            self._load()
        return self._dim

    def _load(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers is required for this embedder. "
                "Install with: pip install mempalace[gpu]"
            )
        self._model = SentenceTransformer(self._model_name, device=self._device)
        self._dim = self._model.get_embedding_dimension()
        logger.info("Loaded embedder: %s (%dd on %s)", self._model_name, self._dim, self._device)

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._load()
        embeddings = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return embeddings.tolist()


# ── Ollama ────────────────────────────────────────────────────────────────────


class OllamaEmbedder:
    """Embedding via a local or remote Ollama server.

    Useful for:
      - Running large models on a GPU server
      - Keeping the laptop dependency-light (no torch needed)
      - Using models like nomic-embed-text, mxbai-embed-large, snowflake-arctic-embed

    Requires Ollama running: ollama serve
    Pull the model first: ollama pull nomic-embed-text
    """

    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = "http://localhost:11434",
        timeout: float = 60.0,
    ):
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._dim = None

    @property
    def model_name(self) -> str:
        return f"ollama/{self._model}"

    @property
    def dimension(self) -> int:
        if self._dim is None:
            # Embed a probe string to discover dimension
            probe = self._embed_batch(["dimension probe"])
            self._dim = len(probe[0])
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._embed_batch(texts)

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Call Ollama /api/embed endpoint."""
        import json
        from urllib.request import Request, urlopen
        from urllib.error import URLError

        url = f"{self._base_url}/api/embed"
        payload = json.dumps({"model": self._model, "input": texts}).encode("utf-8")

        req = Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except URLError as e:
            raise ConnectionError(
                f"Cannot reach Ollama at {self._base_url}. "
                f"Is it running? (ollama serve)\n  Error: {e}"
            ) from e

        embeddings = data.get("embeddings")
        if not embeddings:
            raise ValueError(
                f"Ollama returned no embeddings for model '{self._model}'. "
                f"Did you pull it? (ollama pull {self._model})"
            )

        if self._dim is None:
            self._dim = len(embeddings[0])
            logger.info("Ollama embedder: %s (%dd via %s)", self._model, self._dim, self._base_url)

        return embeddings


# ── Embedder cache & factory ─────────────────────────────────────────────────

_embedder_cache: dict[str, Embedder] = {}


# Well-known model aliases that map to full HuggingFace names.
MODEL_ALIASES = {
    "minilm": "all-MiniLM-L6-v2",
    "bge-small": "BAAI/bge-small-en-v1.5",
    "bge-base": "BAAI/bge-base-en-v1.5",
    "e5-base": "intfloat/e5-base-v2",
    "nomic": "nomic-ai/nomic-embed-text-v1.5",
}


def resolve_model_name(name: str) -> str:
    """Resolve a short alias to a full model name."""
    return MODEL_ALIASES.get(name, name)


def get_embedder(config: dict = None) -> Embedder:
    """Factory: get or create a cached embedder from config.

    Config keys:
        embedder: model name or "ollama" (default: "all-MiniLM-L6-v2")
        embedder_options:
            device: "cpu" | "cuda" | "mps"  (sentence-transformers, requires [gpu])
            model: Ollama model name        (ollama backend)
            base_url: Ollama server URL     (ollama backend)
            timeout: request timeout secs   (ollama backend)

    Routing:
        - "ollama" → OllamaEmbedder (no extra deps)
        - "all-MiniLM-L6-v2" + device=cpu → OnnxEmbedder (default, lightweight)
        - "all-MiniLM-L6-v2" + device=cuda/mps → SentenceTransformerEmbedder (requires [gpu])
        - any other model → SentenceTransformerEmbedder (requires [gpu])
    """
    config = config or {}
    name = config.get("embedder", "all-MiniLM-L6-v2")
    options = config.get("embedder_options", {})

    if name == "ollama":
        model = options.get("model", "nomic-embed-text")
        base_url = options.get("base_url", "http://localhost:11434")
        timeout = float(options.get("timeout", 60.0))
        cache_key = f"ollama:{model}@{base_url}"

        if cache_key not in _embedder_cache:
            _embedder_cache[cache_key] = OllamaEmbedder(
                model=model, base_url=base_url, timeout=timeout
            )
        return _embedder_cache[cache_key]

    resolved = resolve_model_name(name)
    device = options.get("device", "cpu")

    # Default model on CPU → lightweight ONNX backend
    if resolved == "all-MiniLM-L6-v2" and device == "cpu":
        cache_key = "onnx:all-MiniLM-L6-v2"
        if cache_key not in _embedder_cache:
            _embedder_cache[cache_key] = OnnxEmbedder()
        return _embedder_cache[cache_key]

    # GPU device or non-default model → sentence-transformers
    cache_key = f"st:{resolved}:{device}"
    if cache_key not in _embedder_cache:
        _embedder_cache[cache_key] = SentenceTransformerEmbedder(model_name=resolved, device=device)
    return _embedder_cache[cache_key]


def list_embedders() -> list[dict]:
    """List available embedder configurations for CLI help."""
    return [
        {
            "name": "all-MiniLM-L6-v2",
            "alias": "minilm",
            "dim": 384,
            "backend": "onnx",
            "notes": "Default. Fast, lightweight (no torch).",
        },
        {
            "name": "BAAI/bge-small-en-v1.5",
            "alias": "bge-small",
            "dim": 384,
            "backend": "sentence-transformers",
            "notes": "Best quality-at-size for English. Requires [gpu].",
        },
        {
            "name": "BAAI/bge-base-en-v1.5",
            "alias": "bge-base",
            "dim": 768,
            "backend": "sentence-transformers",
            "notes": "Higher quality, larger model. Requires [gpu].",
        },
        {
            "name": "intfloat/e5-base-v2",
            "alias": "e5-base",
            "dim": 768,
            "backend": "sentence-transformers",
            "notes": "Good general purpose. Requires [gpu].",
        },
        {
            "name": "nomic-ai/nomic-embed-text-v1.5",
            "alias": "nomic",
            "dim": 768,
            "backend": "sentence-transformers",
            "notes": "Matryoshka dims (truncatable to 256/384). Requires [gpu].",
        },
        {
            "name": "ollama",
            "alias": "ollama",
            "dim": "varies",
            "backend": "ollama",
            "notes": "Any model via Ollama server. Set model + base_url in options.",
        },
    ]
