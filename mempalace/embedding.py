"""Embedding function factory with hardware acceleration.

Returns a ChromaDB-compatible embedding function bound to a user-selected
ONNX Runtime execution provider. The same ``all-MiniLM-L6-v2`` model and
384-dim vectors ChromaDB ships by default are reused, so switching device
does not invalidate existing palaces.

Supported devices (env ``MEMPALACE_EMBEDDING_DEVICE`` or ``embedding_device``
in ``~/.mempalace/config.json``):

* ``auto`` — prefer CUDA ▸ CoreML ▸ DirectML, fall back to CPU
* ``cpu`` — force CPU (the historical default)
* ``cuda`` — NVIDIA GPU via ``onnxruntime-gpu`` (``pip install mempalace[gpu]``)
* ``coreml`` — Apple Neural Engine (macOS)
* ``dml`` — DirectML (Windows / AMD / Intel GPUs)

Requesting an unavailable accelerator emits a warning and falls back to CPU
rather than hard-failing — mining must still work on a laptop without CUDA.

ONNX Runtime's intra-op thread pool is capped via ``MEMPAL_MAX_THREADS``
(default 2; ``0``/``off``/``default``/``none`` disables the cap). Without
this, ORT spawns ≈physical-core-count workers and a background mine can
peg 400-500%% CPU. ``OMP_NUM_THREADS`` does not control the ORT pool.
"""

from __future__ import annotations

import logging
import os
from functools import cached_property
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_THREAD_CAP = 2


def _read_thread_cap() -> int:
    """Return the ONNX intra-op thread cap from ``MEMPAL_MAX_THREADS``.

    * Unset → ``_DEFAULT_THREAD_CAP`` (2).
    * ``"0"`` / ``"off"`` / ``"default"`` / ``"none"`` / empty → 0 (no cap).
    * Positive int → that int.
    * Anything else → 0 with a warning (fail-open: never break mining on a typo).
    """
    raw = os.environ.get("MEMPAL_MAX_THREADS")
    if raw is None:
        return _DEFAULT_THREAD_CAP
    raw = raw.strip().lower()
    if raw in ("", "0", "off", "default", "none"):
        return 0
    try:
        n = int(raw)
    except ValueError:
        logger.warning(
            "MEMPAL_MAX_THREADS=%r is not an integer; leaving ORT defaults",
            raw,
        )
        return 0
    return n if n > 0 else 0


_PROVIDER_MAP = {
    "cpu": ["CPUExecutionProvider"],
    "cuda": ["CUDAExecutionProvider", "CPUExecutionProvider"],
    "coreml": ["CoreMLExecutionProvider", "CPUExecutionProvider"],
    "dml": ["DmlExecutionProvider", "CPUExecutionProvider"],
}

_DEVICE_EXTRA = {
    "cuda": "mempalace[gpu]",
    "coreml": "mempalace[coreml]",
    "dml": "mempalace[dml]",
}

_AUTO_ORDER = [
    ("CUDAExecutionProvider", "cuda"),
    ("CoreMLExecutionProvider", "coreml"),
    ("DmlExecutionProvider", "dml"),
]

_EF_CACHE: dict = {}
_WARNED: set = set()


def _resolve_providers(device: str) -> tuple[list, str]:
    """Return ``(provider_list, effective_device)`` for ``device``.

    Falls back to CPU (with a one-shot warning) when the requested
    accelerator is not compiled into the installed ``onnxruntime``.
    """
    device = (device or "auto").strip().lower()

    try:
        import onnxruntime as ort

        available = set(ort.get_available_providers())
    except ImportError:
        return (["CPUExecutionProvider"], "cpu")

    if device == "auto":
        for provider, name in _AUTO_ORDER:
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


def _build_ef_class(thread_cap: int = 0):
    """Subclass ``ONNXMiniLM_L6_V2`` with name ``"default"``.

    Why the rename: ChromaDB 1.5 persists the EF identity on the collection
    and rejects reads that pass a differently-named EF (``onnx_mini_lm_l6_v2``
    vs ``default``). The vectors and model are identical — only the
    ``name()`` tag differs — so spoofing the name lets one EF class serve
    palaces created with ``DefaultEmbeddingFunction`` *and* palaces we
    create ourselves, with the same GPU-capable ``preferred_providers``.

    When ``thread_cap > 0`` the ``model`` cached property is overridden so
    the ORT ``InferenceSession`` is built with explicit ``SessionOptions``
    capping ``intra_op_num_threads`` and ``inter_op_num_threads=1``. This
    keeps the background mine from pinning every core on multi-core hosts;
    ``OMP_NUM_THREADS`` does not control ORT's intra-op pool.
    """
    from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

    class _MempalaceONNX(ONNXMiniLM_L6_V2):
        @staticmethod
        def name() -> str:
            return "default"

    if thread_cap <= 0:
        return _MempalaceONNX

    class _CappedMempalaceONNX(_MempalaceONNX):
        _mempal_thread_cap = thread_cap

        @cached_property
        def model(self):  # type: ignore[override]
            so = self.ort.SessionOptions()
            so.log_severity_level = 3
            so.intra_op_num_threads = self._mempal_thread_cap
            so.inter_op_num_threads = 1
            if not self._preferred_providers:
                self._preferred_providers = ["CPUExecutionProvider"]
            return self.ort.InferenceSession(
                os.path.join(self.DOWNLOAD_PATH, self.EXTRACTED_FOLDER_NAME, "model.onnx"),
                providers=self._preferred_providers,
                sess_options=so,
            )

    return _CappedMempalaceONNX


def get_embedding_function(device: Optional[str] = None):
    """Return a cached embedding function bound to the requested device.

    ``device=None`` reads from :class:`MempalaceConfig.embedding_device`.
    The returned function is shared across calls with the same resolved
    provider list (and the same ``MEMPAL_MAX_THREADS`` cap) so we only pay
    model-load cost once per process.
    """
    if device is None:
        from .config import MempalaceConfig

        device = MempalaceConfig().embedding_device

    providers, effective = _resolve_providers(device)
    thread_cap = _read_thread_cap()
    cache_key = (tuple(providers), thread_cap)
    cached = _EF_CACHE.get(cache_key)
    if cached is not None:
        return cached

    ef_cls = _build_ef_class(thread_cap)
    ef = ef_cls(preferred_providers=providers)
    _EF_CACHE[cache_key] = ef
    logger.info(
        "Embedding function initialized (device=%s providers=%s thread_cap=%d)",
        effective,
        providers,
        thread_cap,
    )
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
