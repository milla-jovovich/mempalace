"""
embeddings.py — Pluggable embedding backends for MemPalace.

Supported backends:
  - sentence-transformers: any HuggingFace model (default: all-MiniLM-L6-v2)
  - ollama: any model served by a local/remote Ollama instance

Config in ~/.mempalace/config.json:
    {"embedder": "all-MiniLM-L6-v2", "embedder_options": {"device": "cpu"}}
    {"embedder": "BAAI/bge-small-en-v1.5", "embedder_options": {"device": "cuda"}}
    {"embedder": "ollama", "embedder_options": {"model": "nomic-embed-text", "base_url": "http://localhost:11434"}}
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


# ── Sentence Transformers ─────────────────────────────────────────────────────


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
                "sentence-transformers is required. "
                "Install with: pip install sentence-transformers"
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
            logger.info(
                "Ollama embedder: %s (%dd via %s)", self._model, self._dim, self._base_url
            )

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
            device: "cpu" | "cuda" | "mps"  (sentence-transformers)
            model: Ollama model name        (ollama backend)
            base_url: Ollama server URL     (ollama backend)
            timeout: request timeout secs   (ollama backend)
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

    # Sentence-transformers backend (default)
    resolved = resolve_model_name(name)
    device = options.get("device", "cpu")
    cache_key = f"st:{resolved}:{device}"

    if cache_key not in _embedder_cache:
        _embedder_cache[cache_key] = SentenceTransformerEmbedder(
            model_name=resolved, device=device
        )
    return _embedder_cache[cache_key]


def list_embedders() -> list[dict]:
    """List available embedder configurations for CLI help."""
    return [
        {
            "name": "all-MiniLM-L6-v2",
            "alias": "minilm",
            "dim": 384,
            "backend": "sentence-transformers",
            "notes": "Default. Fast, decent quality.",
        },
        {
            "name": "BAAI/bge-small-en-v1.5",
            "alias": "bge-small",
            "dim": 384,
            "backend": "sentence-transformers",
            "notes": "Best quality-at-size for English.",
        },
        {
            "name": "BAAI/bge-base-en-v1.5",
            "alias": "bge-base",
            "dim": 768,
            "backend": "sentence-transformers",
            "notes": "Higher quality, larger model.",
        },
        {
            "name": "intfloat/e5-base-v2",
            "alias": "e5-base",
            "dim": 768,
            "backend": "sentence-transformers",
            "notes": "Good general purpose.",
        },
        {
            "name": "nomic-ai/nomic-embed-text-v1.5",
            "alias": "nomic",
            "dim": 768,
            "backend": "sentence-transformers",
            "notes": "Matryoshka dims (truncatable to 256/384).",
        },
        {
            "name": "ollama",
            "alias": "ollama",
            "dim": "varies",
            "backend": "ollama",
            "notes": "Any model via Ollama server. Set model + base_url in options.",
        },
    ]
