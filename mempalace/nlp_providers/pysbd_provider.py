"""
pysbd_provider.py -- Sentence splitting provider using pySBD.

Feature-gated: only active when MEMPALACE_NLP_SENTENCES=1 (or backend >= pysbd).
pySBD is lazily imported on first use. If not installed, is_available() returns False
and the registry falls back to the legacy provider.
"""

import logging
import os
import threading
from typing import Dict, List, Optional

from .negation import is_negated

logger = logging.getLogger(__name__)


class PySBDProvider:
    """NLP provider for sentence splitting via pySBD."""

    def __init__(self):
        self._segmenter = None
        self._pysbd = None
        self._load_lock = threading.Lock()
        self._loaded = False
        self._available = None

    @property
    def name(self) -> str:
        return "pysbd"

    @property
    def capabilities(self) -> set:
        return {"sentences", "negation"}

    def _ensure_loaded(self):
        """Lazily load pysbd on first use. Thread-safe."""
        if self._loaded:
            return
        with self._load_lock:
            if self._loaded:
                return
            try:
                import pysbd

                self._pysbd = pysbd
                self._segmenter = pysbd.Segmenter(language="en", clean=False)
                self._available = True
            except ImportError:
                logger.debug("pysbd not installed — PySBDProvider unavailable")
                self._available = False
            except Exception as e:
                logger.warning(f"Failed to initialize pysbd: {e}")
                self._available = False
            self._loaded = True

    def is_available(self) -> bool:
        """Check if pysbd is importable and the feature is enabled."""
        # Check feature gate
        env_val = os.environ.get("MEMPALACE_NLP_SENTENCES")
        backend = os.environ.get("MEMPALACE_NLP_BACKEND", "legacy")
        feature_enabled = env_val in ("1", "true", "yes", "on") or backend in (
            "pysbd",
            "spacy",
            "gliner",
            "full",
        )

        if not feature_enabled:
            return False

        self._ensure_loaded()
        return self._available is True

    def split_sentences(self, text: str) -> List[str]:
        """Split text into sentences using pySBD."""
        self._ensure_loaded()
        if not self._available or self._segmenter is None:
            return []
        try:
            segments = self._segmenter.segment(text)
            return [s.strip() for s in segments if s.strip()]
        except Exception as e:
            logger.warning(f"pySBD segmentation failed: {e}")
            return []

    def split_sentences_with_negation(self, text: str, markers: list) -> List[Dict]:
        """Split sentences and annotate with negation detection.

        Returns list of dicts with 'sentence', 'negated_markers' keys.
        """
        sentences = self.split_sentences(text)
        results = []
        for sentence in sentences:
            negated = []
            for marker in markers:
                import re

                for match in re.finditer(marker, sentence.lower()):
                    if is_negated(sentence, match.start()):
                        negated.append(match.group(0))
            results.append({"sentence": sentence, "negated_markers": negated})
        return results

    def extract_entities(self, text: str) -> List[Dict]:
        """Not supported by pySBD provider."""
        return []

    def extract_triples(self, text: str) -> List[Dict]:
        """Not supported by pySBD provider."""
        return []

    def classify_text(self, text: str, labels: List[str]) -> Optional[Dict]:
        """Not supported by pySBD provider."""
        return None

    def resolve_coreferences(self, text: str) -> List[Dict]:
        """Not supported by pySBD provider."""
        return []

    def analyze_sentiment(self, text: str) -> str:
        """Not supported by pySBD provider."""
        return "neutral"
