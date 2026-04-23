"""
spacy_provider.py -- NER, sentence segmentation, and coreference via spaCy.

Feature-gated: only active when MEMPALACE_NLP_NER=1 (or backend >= spacy).
spaCy is lazily imported and the model is loaded on first use.
Thread-safe model loading with lock.
"""

import logging
import os
import threading
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class SpaCyProvider:
    """NLP provider using spaCy for NER, sentence segmentation, and coref."""

    def __init__(self):
        self._nlp = None
        self._spacy = None
        self._load_lock = threading.Lock()
        self._loaded = False
        self._available = None

    @property
    def name(self) -> str:
        return "spacy"

    @property
    def capabilities(self) -> set:
        return {"ner", "sentences", "coref"}

    def _ensure_loaded(self):
        """Lazily load spaCy model on first use. Thread-safe."""
        if self._loaded:
            return
        with self._load_lock:
            if self._loaded:
                return
            try:
                import spacy

                self._spacy = spacy

                # Use ModelManager to check model availability
                from .model_manager import ModelManager

                mm = ModelManager.get()
                model_path = mm.ensure_model("spacy-xx-ent-wiki-sm")

                if model_path is None:
                    # Try loading default model directly
                    try:
                        self._nlp = spacy.load("xx_ent_wiki_sm")
                        self._available = True
                    except OSError:
                        logger.debug("spaCy model xx_ent_wiki_sm not available")
                        self._available = False
                else:
                    try:
                        self._nlp = spacy.load("xx_ent_wiki_sm")
                        self._available = True
                    except OSError:
                        self._available = False
            except ImportError:
                logger.debug("spacy not installed — SpaCyProvider unavailable")
                self._available = False
            except Exception as e:
                logger.warning(f"Failed to initialize spaCy: {e}")
                self._available = False
            self._loaded = True

    def is_available(self) -> bool:
        """Check if spaCy is importable, model exists, and feature is enabled."""
        # Check feature gate
        env_ner = os.environ.get("MEMPALACE_NLP_NER")
        env_sentences = os.environ.get("MEMPALACE_NLP_SENTENCES")
        backend = os.environ.get("MEMPALACE_NLP_BACKEND", "legacy")
        feature_enabled = (
            env_ner in ("1", "true", "yes", "on")
            or env_sentences in ("1", "true", "yes", "on")
            or backend in ("spacy", "gliner", "full")
        )

        if not feature_enabled:
            return False

        self._ensure_loaded()
        return self._available is True

    def extract_entities(self, text: str) -> List[Dict]:
        """Extract named entities using spaCy NER.

        Returns list of dicts with text, label, start, end keys.
        """
        self._ensure_loaded()
        if not self._available or self._nlp is None:
            return []
        try:
            doc = self._nlp(text)
            return [
                {
                    "text": ent.text,
                    "label": ent.label_,
                    "start": ent.start_char,
                    "end": ent.end_char,
                }
                for ent in doc.ents
            ]
        except Exception as e:
            logger.warning(f"spaCy NER failed: {e}")
            return []

    def split_sentences(self, text: str) -> List[str]:
        """Split text into sentences using spaCy."""
        self._ensure_loaded()
        if not self._available or self._nlp is None:
            return []
        try:
            doc = self._nlp(text)
            return [sent.text.strip() for sent in doc.sents if sent.text.strip()]
        except Exception as e:
            logger.warning(f"spaCy sentence segmentation failed: {e}")
            return []

    def extract_triples(self, text: str) -> List[Dict]:
        """Not supported by spaCy provider."""
        return []

    def classify_text(self, text: str, labels: List[str]) -> Optional[Dict]:
        """Not supported by spaCy provider."""
        return None

    def resolve_coreferences(self, text: str) -> List[Dict]:
        """Placeholder for coreference resolution (coreferee integration later)."""
        return []

    def analyze_sentiment(self, text: str) -> str:
        """Not supported by spaCy provider."""
        return "neutral"
