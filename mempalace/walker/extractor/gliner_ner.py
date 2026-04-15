"""GLiNER wrapper — batched entity extraction with GPU autodetect."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from mempalace.walker.gpu_detect import HardwareTier, detect_hardware

log = logging.getLogger(__name__)

ENTITY_TYPES: list[str] = [
    "person", "organization", "location",
    "date", "project", "technology", "event",
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
        self._device = device or GlinerNER._select_device()
        try:
            self._model = GLiNER.from_pretrained(model).to(self._device)
        except Exception as e:
            if self._device == "cuda":
                log.warning("GLiNER failed on cuda (%s); falling back to cpu", e)
                self._device = "cpu"
                self._model = GLiNER.from_pretrained(model).to("cpu")
            else:
                raise

    def extract_batch(
        self, texts: list[str], threshold: float = 0.4
    ) -> list[list[Entity]]:
        if not texts:
            return []
        raw = self._model.batch_predict_entities(
            texts, ENTITY_TYPES, threshold=threshold
        )
        return [
            [Entity(r["text"], r["label"], r["score"]) for r in per_text]
            for per_text in raw
        ]

    @staticmethod
    def _select_device() -> str:
        """Returns 'cuda' if a GPU is available, else 'cpu'. Fallback on error."""
        try:
            hw = detect_hardware()
        except Exception as e:
            log.warning("detect_hardware failed: %s — falling back to cpu", e)
            return "cpu"
        return "cpu" if hw.tier == HardwareTier.CPU_ONLY else "cuda"
