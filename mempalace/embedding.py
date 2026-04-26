"""Embedding function factory with hardware acceleration.

Returns a ChromaDB-compatible embedding function bound to a user-selected
backend. The same ``all-MiniLM-L6-v2`` model and 384-dim vectors ChromaDB
ships by default are reused, so switching device does not invalidate
existing palaces.

Supported devices (env ``MEMPALACE_EMBEDDING_DEVICE`` or ``embedding_device``
in ``~/.mempalace/config.json``):

* ``auto`` — prefer ``mps`` ▸ ``cuda`` ▸ ``coreml`` ▸ ``dml``, fall back to CPU
* ``cpu`` — force ONNX Runtime on CPU (the historical default)
* ``cuda`` — NVIDIA GPU via ``onnxruntime-gpu`` (``pip install mempalace[gpu]``)
* ``coreml`` — Apple Neural Engine via ONNX Runtime CoreML provider (macOS)
* ``dml`` — DirectML (Windows / AMD / Intel GPUs)
* ``mps`` — Apple Metal GPU via PyTorch + sentence-transformers
  (``pip install mempalace[mps]``)

Why ``mps`` is its own path: on Apple Silicon, ChromaDB's bundled ONNX
embedding function enables ``CoreMLExecutionProvider`` by default, which
silently falls back op-by-op to CPU for ``all-MiniLM-L6-v2`` because some
ops are not yet implemented in CoreML's MLProgram lowering. The resulting
ANE↔CPU copies cost more than they save (measured 60–256× slowdown vs.
PyTorch MPS on the same hardware, M5, 200 real chunks). Routing
``mps`` through sentence-transformers + PyTorch bypasses CoreML
entirely. The ``coreml`` device is retained for users who want ONNX
Runtime's CoreML provider explicitly (e.g. on an M1 base where the
ANE↔CPU thrash is less pronounced).

The ``mps`` and ``cuda``/``coreml``/``dml`` paths produce embeddings that
differ by ~1e-6 (numerical FP drift between ONNX Runtime and PyTorch
implementations of the same MiniLM weights). This drift is well below the
noise floor of cosine retrieval, so backends can be switched on an
existing palace without re-mining. The HNSW *index* itself is
order- and value-sensitive, so an index built end-to-end on one backend
will not be bit-identical to one built on another (graph neighbor lists
differ); query results stay correct, but exact ``recall@k`` can shift by
a hit or two between runtimes. Pin ``MEMPALACE_EMBEDDING_DEVICE`` if you
need strict reproducibility.

Requesting an unavailable accelerator emits a warning and falls back to
CPU rather than hard-failing — mining must still work on a laptop without
CUDA, MPS, or CoreML.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Sentinel returned in the provider list to mark the PyTorch-MPS path.
# Anything that consumes a (providers, device) pair must treat this as a
# signal to take the sentence-transformers branch rather than passing the
# providers through to ONNX Runtime.
_MPS_SENTINEL = "__mempalace_torch_mps__"

_PROVIDER_MAP = {
    "cpu": ["CPUExecutionProvider"],
    "cuda": ["CUDAExecutionProvider", "CPUExecutionProvider"],
    "coreml": ["CoreMLExecutionProvider", "CPUExecutionProvider"],
    "dml": ["DmlExecutionProvider", "CPUExecutionProvider"],
    # "mps" is resolved without consulting onnxruntime — the sentinel exists so
    # cache_key / EF-construction code can stay uniform across backends.
    "mps": [_MPS_SENTINEL, "CPUExecutionProvider"],
}

_DEVICE_EXTRA = {
    "cuda": "mempalace[gpu]",
    "coreml": "mempalace[coreml]",
    "dml": "mempalace[dml]",
    "mps": "mempalace[mps]",
}

# auto-resolution order. MPS is preferred over CoreML on Apple Silicon
# because sentence-transformers + torch.mps avoids the CoreML op-fallback
# thrash that pins ``onnx_default`` to ~2 chunks/s on this model.
_AUTO_ORDER_ONNX = [
    ("CUDAExecutionProvider", "cuda"),
    ("CoreMLExecutionProvider", "coreml"),
    ("DmlExecutionProvider", "dml"),
]

_EF_CACHE: dict = {}
_WARNED: set = set()


def _torch_mps_available() -> bool:
    """Return True iff PyTorch is installed AND its MPS backend is usable.

    Wrapped in a broad ``except`` because torch can raise platform-specific
    errors on non-Apple Silicon hosts (NotImplementedError, RuntimeError),
    and we want a clean False fallback rather than a stack trace.
    """
    try:
        import torch

        return (
            hasattr(torch.backends, "mps")
            and torch.backends.mps.is_available()
            and torch.backends.mps.is_built()
        )
    except Exception:
        return False


def _sentence_transformers_available() -> bool:
    """True iff both ``torch`` and ``sentence_transformers`` import cleanly."""
    try:
        import sentence_transformers  # noqa: F401
        import torch  # noqa: F401

        return True
    except ImportError:
        return False


def _resolve_providers(device: str) -> tuple[list, str]:
    """Return ``(provider_list, effective_device)`` for ``device``.

    For ONNX devices the first element of ``provider_list`` is the
    onnxruntime provider name. For the ``mps`` device the first element is
    :data:`_MPS_SENTINEL` and the rest of the system reads ``effective``
    to take the sentence-transformers branch.

    Falls back to CPU (with a one-shot warning) when the requested
    accelerator is not compiled into the installed ``onnxruntime`` or when
    the optional ``mempalace[mps]`` extra is missing.
    """
    device = (device or "auto").strip().lower()

    # MPS is special: it does not consult onnxruntime providers at all.
    if device == "mps":
        return _resolve_mps_or_cpu()

    try:
        import onnxruntime as ort

        available = set(ort.get_available_providers())
    except ImportError:
        return (["CPUExecutionProvider"], "cpu")

    if device == "auto":
        # Prefer MPS on Apple Silicon when the optional extra is installed —
        # CoreML thrashes on this model, so MPS is materially faster even
        # though both target the same physical GPU.
        if _torch_mps_available() and _sentence_transformers_available():
            return ([_MPS_SENTINEL, "CPUExecutionProvider"], "mps")
        for provider, name in _AUTO_ORDER_ONNX:
            if provider in available:
                return ([provider, "CPUExecutionProvider"], name)
        return (["CPUExecutionProvider"], "cpu")

    requested = _PROVIDER_MAP.get(device)
    if requested is None:
        if device not in _WARNED:
            logger.warning("Unknown embedding_device %r — falling back to cpu", device)
            _WARNED.add(device)
        return (["CPUExecutionProvider"], "cpu")

    preferred = requested[0]
    if preferred == "CPUExecutionProvider":
        return (requested, "cpu")

    if preferred not in available:
        if device not in _WARNED:
            extra = _DEVICE_EXTRA.get(device, "the matching mempalace extra for your device")
            logger.warning(
                "embedding_device=%r requested but %s is not installed — "
                "falling back to CPU. Install %s.",
                device,
                preferred,
                extra,
            )
            _WARNED.add(device)
        return (["CPUExecutionProvider"], "cpu")

    return (requested, device)


def _resolve_mps_or_cpu() -> tuple[list, str]:
    """Return MPS providers if torch+MPS+ST available, else warn and fall to CPU."""
    if not _sentence_transformers_available():
        if "mps" not in _WARNED:
            logger.warning(
                "embedding_device='mps' requested but the optional 'mps' extra "
                "is not installed — falling back to CPU. Install %s.",
                _DEVICE_EXTRA["mps"],
            )
            _WARNED.add("mps")
        return (["CPUExecutionProvider"], "cpu")
    if not _torch_mps_available():
        if "mps" not in _WARNED:
            logger.warning(
                "embedding_device='mps' requested but torch.backends.mps is "
                "not available on this host — falling back to CPU."
            )
            _WARNED.add("mps")
        return (["CPUExecutionProvider"], "cpu")
    return ([_MPS_SENTINEL, "CPUExecutionProvider"], "mps")


def _build_ef_class():
    """Subclass ``ONNXMiniLM_L6_V2`` with name ``"default"``.

    Why the rename: ChromaDB 1.5 persists the EF identity on the collection
    and rejects reads that pass a differently-named EF (``onnx_mini_lm_l6_v2``
    vs ``default``). The vectors and model are identical — only the
    ``name()`` tag differs — so spoofing the name lets one EF class serve
    palaces created with ``DefaultEmbeddingFunction`` *and* palaces we
    create ourselves, with the same GPU-capable ``preferred_providers``.
    """
    from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

    class _MempalaceONNX(ONNXMiniLM_L6_V2):
        @staticmethod
        def name() -> str:
            return "default"

    return _MempalaceONNX


def _build_mps_ef(model_name: str = "all-MiniLM-L6-v2"):
    """Build a sentence-transformers EF on torch MPS, named ``"default"``.

    The ``name()`` override mirrors :func:`_build_ef_class` — it lets a
    palace persisted by ChromaDB's bundled default EF reopen with this EF
    without tripping the 1.x ``Embedding function conflict`` guard. The
    embeddings produced agree with ONNX Runtime's to ~1e-6 (same MiniLM
    weights, FP32 vs ANE/MPS arithmetic ordering), well below cosine
    retrieval's noise floor.
    """
    from chromadb.utils.embedding_functions.sentence_transformer_embedding_function import (
        SentenceTransformerEmbeddingFunction,
    )

    class _MempalaceMPS(SentenceTransformerEmbeddingFunction):
        @staticmethod
        def name() -> str:
            return "default"

    return _MempalaceMPS(model_name=model_name, device="mps")


def get_embedding_function(device: Optional[str] = None):
    """Return a cached embedding function bound to the requested device.

    ``device=None`` reads from :class:`MempalaceConfig.embedding_device`.
    The returned function is shared across calls with the same resolved
    provider list so we only pay model-load cost once per process.
    """
    if device is None:
        from .config import MempalaceConfig

        device = MempalaceConfig().embedding_device

    providers, effective = _resolve_providers(device)
    cache_key = tuple(providers)
    cached = _EF_CACHE.get(cache_key)
    if cached is not None:
        return cached

    if providers and providers[0] == _MPS_SENTINEL:
        ef = _build_mps_ef()
    else:
        ef_cls = _build_ef_class()
        ef = ef_cls(preferred_providers=providers)

    _EF_CACHE[cache_key] = ef
    logger.info("Embedding function initialized (device=%s providers=%s)", effective, providers)
    return ef


def describe_device(device: Optional[str] = None) -> str:
    """Return a short human-readable label for the resolved device.

    Used by the miner CLI header so users can see at a glance whether GPU
    acceleration actually engaged.
    """
    if device is None:
        from .config import MempalaceConfig

        device = MempalaceConfig().embedding_device
    _, effective = _resolve_providers(device)
    return effective
