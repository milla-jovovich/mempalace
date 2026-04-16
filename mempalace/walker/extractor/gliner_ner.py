"""GLiNER wrapper — batched entity extraction with GPU autodetect."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from mempalace.walker.gpu_detect import HardwareTier, detect_hardware

log = logging.getLogger(__name__)

ENTITY_TYPES: list[str] = [
    "person",
    "organization",
    "location",
    "date",
    "project",
    "technology",
    "event",
]


@dataclass(slots=True)
class Entity:
    text: str
    type: str
    score: float


class GlinerNER:
    def __init__(
        self,
        model: str = "urchade/gliner_multi-v2.1",
        device: str | None = None,
    ) -> None:
        from gliner import GLiNER

        self._model_name = model
        self._device = device or GlinerNER._select_device()
        try:
            self._model = GLiNER.from_pretrained(model).to(self._device)
        except Exception as e:
            if self._device == "cuda":
                log.warning("GLiNER failed on cuda (%s); falling back to cpu", e)
                self._device = "cpu"
                self._model = GlinerNER._load_cpu(model)
            else:
                raise

    def extract_batch(self, texts: list[str], threshold: float = 0.4) -> list[list[Entity]]:
        if not texts:
            return []
        try:
            raw = self._model.batch_predict_entities(texts, ENTITY_TYPES, threshold=threshold)
        except RuntimeError as e:
            if self._device == "cuda" and ("nvrtc" in str(e).lower() or "cuda" in str(e).lower()):
                log.warning(
                    "GLiNER inference failed on cuda (%s); reloading on cpu",
                    str(e)[:120],
                )
                self._device = "cpu"
                self._model = GlinerNER._load_cpu(self._model_name)
                raw = self._model.batch_predict_entities(texts, ENTITY_TYPES, threshold=threshold)
            else:
                raise
        return [[Entity(r["text"], r["label"], r["score"]) for r in per_text] for per_text in raw]

    @staticmethod
    def _patch_deberta_eager() -> None:
        """Replace the @torch.jit.script'd make_log_bucket_position with an eager version.

        The JIT-compiled DeBERTa helper tries to compile shape-specific CUDA kernels
        via nvrtc even when inference runs on CPU (because CUDA is present on the
        system).  build_relative_position resolves make_log_bucket_position via a
        module-level name lookup at each call, so replacing the name after import is
        sufficient to redirect all future calls to the eager version.
        """
        import torch
        import transformers.models.deberta_v2.modeling_deberta_v2 as _deberta

        if not isinstance(getattr(_deberta, "make_log_bucket_position", None), torch.jit.ScriptFunction):
            return  # already patched or not JIT-compiled

        def _eager(relative_pos, bucket_size, max_position):
            sign = torch.sign(relative_pos)
            mid = bucket_size // 2
            abs_pos = torch.where(
                (relative_pos < mid) & (relative_pos > -mid),
                torch.tensor(mid - 1).type_as(relative_pos),
                torch.abs(relative_pos),
            )
            log_pos = (
                torch.ceil(
                    torch.log(abs_pos / mid)
                    / torch.log(torch.tensor((max_position - 1) / mid))
                    * (mid - 1)
                )
                + mid
            )
            return torch.where(abs_pos <= mid, relative_pos.type_as(log_pos), log_pos * sign)

        _deberta.make_log_bucket_position = _eager
        log.info("Patched DeBERTa make_log_bucket_position to eager mode (nvrtc unavailable)")

    @staticmethod
    def _load_cpu(model: str):
        """Load GLiNER on CPU, patching DeBERTa to avoid nvrtc CUDA kernel compilation."""
        from gliner import GLiNER

        GlinerNER._patch_deberta_eager()
        return GLiNER.from_pretrained(model).to("cpu")

    @staticmethod
    def _select_device() -> str:
        """Returns 'cuda' if a GPU is available, else 'cpu'. Fallback on error."""
        try:
            hw = detect_hardware()
        except Exception as e:
            log.warning("detect_hardware failed: %s — falling back to cpu", e)
            return "cpu"
        return "cpu" if hw.tier == HardwareTier.CPU_ONLY else "cuda"
