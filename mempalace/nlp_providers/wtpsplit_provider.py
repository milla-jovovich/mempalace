"""
wtpsplit_provider.py -- Best-in-class sentence segmentation via wtpsplit SaT model.

Feature-gated: only active when MEMPALACE_NLP_SENTENCES=1 (or backend >= full).
wtpsplit is lazily imported and model loaded on first use.
Thread-safe model loading with lock.
"""

import logging
import os
import threading
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class WtpsplitProvider:
    """NLP provider for sentence segmentation via wtpsplit."""

    def __init__(self):
        self._model = None
        self._wtpsplit = None
        self._load_lock = threading.Lock()
        self._loaded = False
        self._available = None

    @property
    def name(self) -> str:
        return "wtpsplit"

    @property
    def capabilities(self) -> set:
        return {"sentences"}

    def _ensure_loaded(self):
        """Lazily load wtpsplit model on first use. Thread-safe."""
        if self._loaded:
            return
        with self._load_lock:
            if self._loaded:
                return
            try:
                import wtpsplit

                self._wtpsplit = wtpsplit

                from .model_manager import ModelManager

                mm = ModelManager.get()
                model_path = mm.ensure_model("wtpsplit-sat3l-sm")

                if model_path is not None:
                    self._model = wtpsplit.SaT(str(model_path))
                    self._available = True
                else:
                    try:
                        self._model = wtpsplit.SaT("sat-3l-sm")
                        self._available = True
                    except Exception:
                        logger.debug("wtpsplit model not available")
                        self._available = False
            except ImportError:
                logger.debug("wtpsplit not installed — WtpsplitProvider unavailable")
                self._available = False
            except Exception as e:
                logger.warning(f"Failed to initialize wtpsplit: {e}")
                self._available = False
            self._loaded = True

    def is_available(self) -> bool:
        """Check if wtpsplit is importable, model exists, and feature is enabled."""
        env_sentences = os.environ.get("MEMPALACE_NLP_SENTENCES")
        backend = os.environ.get("MEMPALACE_NLP_BACKEND", "legacy")
        feature_enabled = env_sentences in ("1", "true", "yes", "on") or backend in ("full",)

        if not feature_enabled:
            return False

        self._ensure_loaded()
        return self._available is True

    def split_sentences(self, text: str) -> List[str]:
        """Split text into sentences using wtpsplit SaT model."""
        self._ensure_loaded()
        if not self._available or self._model is None:
            return []
        try:
            # Limit input size to avoid memory issues
            if len(text) > 50000:
                text = text[:50000]
            segments = self._model.split(text)
            return [s.strip() for s in segments if s.strip()]
        except Exception as e:
            logger.warning(f"wtpsplit segmentation failed: {e}")
            return []

    def extract_entities(self, text: str) -> List[Dict]:
        """Not supported by wtpsplit provider."""
        return []

    def extract_triples(self, text: str) -> List[Dict]:
        """Not supported by wtpsplit provider."""
        return []

    def classify_text(self, text: str, labels: List[str]) -> Optional[Dict]:
        """Not supported by wtpsplit provider."""
        return None

    def resolve_coreferences(self, text: str) -> List[Dict]:
        """Not supported by wtpsplit provider."""
        return []

    def analyze_sentiment(self, text: str) -> str:
        """Not supported by wtpsplit provider."""
        return "neutral"
