"""
gliner_provider.py -- Triple extraction, zero-shot NER, and classification via GLiNER2.

Feature-gated: only active when MEMPALACE_NLP_TRIPLES=1 or MEMPALACE_NLP_CLASSIFY=1
(or backend >= gliner). GLiNER is lazily imported and model loaded on first use.
Thread-safe model loading with lock.
"""

import logging
import os
import threading
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Default entity types for zero-shot NER
DEFAULT_ENTITY_TYPES = ["person", "organization", "location", "event", "date", "technology"]

# Memory type labels for classification
MEMORY_TYPE_LABELS = ["decision", "preference", "milestone", "problem", "emotional"]

# Minimum confidence threshold for entity/triple inclusion
CONFIDENCE_THRESHOLD = 0.5


# GLiNER ONNX model token limit — texts longer than this get chunked
_MAX_CHARS = 1200  # ~384 tokens ≈ 1200 chars with headroom


def _chunk_text(text: str, max_chars: int = _MAX_CHARS) -> List[str]:
    """Split text into chunks that fit within GLiNER's token window.

    Splits on sentence boundaries to avoid cutting entities in half.
    """
    if len(text) <= max_chars:
        return [text]
    import re

    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks = []
    current = ""
    for sent in sentences:
        if current and len(current) + len(sent) + 1 > max_chars:
            chunks.append(current)
            current = sent
        else:
            current = f"{current} {sent}".strip() if current else sent
    if current:
        chunks.append(current)
    return chunks


class GLiNERProvider:
    """NLP provider using GLiNER2 for NER, triple extraction, and classification."""

    def __init__(self):
        self._model = None
        self._gliner = None
        self._load_lock = threading.Lock()
        self._loaded = False
        self._available = None

    @property
    def name(self) -> str:
        return "gliner"

    @property
    def capabilities(self) -> set:
        return {"ner", "triples", "classify"}

    def _ensure_loaded(self):
        """Lazily load GLiNER model on first use. Thread-safe."""
        if self._loaded:
            return
        with self._load_lock:
            if self._loaded:
                return
            try:
                import gliner as gliner_mod

                self._gliner = gliner_mod

                from .model_manager import ModelManager

                mm = ModelManager.get()
                model_path = mm.ensure_model("gliner2-onnx")

                if model_path is not None:
                    self._model = gliner_mod.GLiNER.from_pretrained(
                        str(model_path),
                        load_onnx_model=True,
                        onnx_model_file="onnx/model.onnx",
                    )
                    self._available = True
                else:
                    # Try loading from default cache
                    try:
                        self._model = gliner_mod.GLiNER.from_pretrained(
                            "onnx-community/gliner_multi-v2.1",
                            load_onnx_model=True,
                            onnx_model_file="onnx/model.onnx",
                        )
                        self._available = True
                    except Exception:
                        logger.debug("GLiNER model not available")
                        self._available = False
            except ImportError:
                logger.debug("gliner not installed — GLiNERProvider unavailable")
                self._available = False
            except Exception as e:
                logger.warning(f"Failed to initialize GLiNER: {e}")
                self._available = False
            self._loaded = True

    def is_available(self) -> bool:
        """Check if GLiNER is importable, model exists, and feature is enabled."""
        env_triples = os.environ.get("MEMPALACE_NLP_TRIPLES")
        env_classify = os.environ.get("MEMPALACE_NLP_CLASSIFY")
        env_ner = os.environ.get("MEMPALACE_NLP_NER")
        backend = os.environ.get("MEMPALACE_NLP_BACKEND", "legacy")
        feature_enabled = (
            env_triples in ("1", "true", "yes", "on")
            or env_classify in ("1", "true", "yes", "on")
            or env_ner in ("1", "true", "yes", "on")
            or backend in ("gliner", "full")
        )

        if not feature_enabled:
            return False

        self._ensure_loaded()
        return self._available is True

    def extract_entities(self, text: str) -> List[Dict]:
        """Extract named entities using GLiNER zero-shot NER.

        Long texts are chunked to stay within the model's token window.
        Returns list of dicts with text, label, start, end keys.
        """
        self._ensure_loaded()
        if not self._available or self._model is None:
            return []
        try:
            results = []
            offset = 0
            for chunk in _chunk_text(text):
                raw = self._model.predict_entities(chunk, DEFAULT_ENTITY_TYPES)
                for ent in raw:
                    score = ent.get("score", 0)
                    if score >= CONFIDENCE_THRESHOLD:
                        results.append(
                            {
                                "text": ent.get("text", ""),
                                "label": ent.get("label", "UNKNOWN"),
                                "start": ent.get("start", 0) + offset,
                                "end": ent.get("end", 0) + offset,
                            }
                        )
                offset += len(chunk) + 1  # +1 for the split whitespace
            return results
        except Exception as e:
            logger.warning(f"GLiNER NER failed: {e}")
            return []

    def extract_triples(self, text: str) -> List[Dict]:
        """Extract subject-predicate-object triples with confidence scores.

        Uses GLiNER NER to find entities, then extracts the text between
        co-occurring entity pairs within the same sentence as the predicate.
        Long texts are chunked to stay within the model's token window.

        Returns list of dicts with subject, predicate, object, confidence keys.
        """
        self._ensure_loaded()
        if not self._available or self._model is None:
            return []

        chunks = _chunk_text(text)
        if len(chunks) > 1:
            all_triples = []
            for chunk in chunks:
                all_triples.extend(self._extract_triples_single(chunk))
            return all_triples
        return self._extract_triples_single(text)

    def _extract_triples_single(self, text: str) -> List[Dict]:
        """Extract triples from a single chunk of text."""
        try:
            entities = self._model.predict_entities(text, DEFAULT_ENTITY_TYPES)
            if not entities:
                return []

            # Try native relation extraction first
            if hasattr(self._model, "predict_relations"):
                raw = self._model.predict_relations(text, entities)
                results = []
                for rel in raw:
                    confidence = rel.get("score", rel.get("confidence", 0))
                    if confidence >= CONFIDENCE_THRESHOLD:
                        results.append(
                            {
                                "subject": rel.get("subject", ""),
                                "predicate": rel.get("predicate", rel.get("relation", "")),
                                "object": rel.get("object", ""),
                                "confidence": confidence,
                            }
                        )
                if results:
                    return results

            # Fallback: extract triples from entity pairs using inter-entity text
            return self._triples_from_entity_pairs(text, entities)
        except Exception as e:
            logger.warning(f"GLiNER triple extraction failed: {e}")
            return []

    def _triples_from_entity_pairs(self, text: str, entities: list) -> List[Dict]:
        """Build triples from entity pairs by extracting inter-entity text as predicate.

        Pairs entities that are close together (no sentence boundary between them)
        and uses the text between them as the predicate.
        """
        import re

        # Filter and sort entities by position
        entity_positions = []
        for ent in entities:
            score = ent.get("score", 0)
            if score < CONFIDENCE_THRESHOLD:
                continue
            start = ent.get("start", 0)
            ent_text = ent.get("text", "")
            entity_positions.append(
                {
                    "text": ent_text,
                    "label": ent.get("label", "UNKNOWN"),
                    "start": start,
                    "end": ent.get("end", start + len(ent_text)),
                    "score": score,
                }
            )

        entity_positions.sort(key=lambda e: e["start"])

        # Only pair adjacent entities to avoid long, noisy predicates
        results = []
        for i in range(len(entity_positions) - 1):
            e1 = entity_positions[i]
            e2 = entity_positions[i + 1]

            # Extract text between the two entities as the predicate
            between = text[e1["end"] : e2["start"]].strip()

            # Skip if a sentence boundary (. ! ?) sits between them,
            # but tolerate abbreviation dots (e.g. "Dr.", "U.S.")
            if re.search(r"(?<![A-Z])[.!?](\s|$)", between):
                continue

            # Clean up leading/trailing punctuation
            between = re.sub(r"^[,;:\s]+|[,;:\s]+$", "", between)

            if not between or len(between) < 2:
                continue

            confidence = min(e1["score"], e2["score"])
            results.append(
                {
                    "subject": e1["text"],
                    "predicate": between,
                    "object": e2["text"],
                    "confidence": round(confidence, 3),
                }
            )

        return results

    def classify_text(self, text: str, labels: List[str]) -> Optional[Dict]:
        """Classify text into one of the given labels.

        Returns dict with label and confidence keys, or None.
        """
        self._ensure_loaded()
        if not self._available or self._model is None:
            return None
        try:
            use_labels = labels if labels else MEMORY_TYPE_LABELS
            # Use first chunk only for classification
            chunk = _chunk_text(text)[0]
            if hasattr(self._model, "predict_classification"):
                result = self._model.predict_classification(chunk, use_labels)
                if result:
                    label = result.get("label", "")
                    confidence = result.get("score", result.get("confidence", 0))
                    if confidence >= CONFIDENCE_THRESHOLD:
                        return {"label": label, "confidence": confidence}
            # Fallback: use entity prediction to approximate classification
            entities = self._model.predict_entities(chunk, use_labels)
            if entities:
                best = max(entities, key=lambda e: e.get("score", 0))
                score = best.get("score", 0)
                if score >= CONFIDENCE_THRESHOLD:
                    return {"label": best.get("label", ""), "confidence": score}
            return None
        except Exception as e:
            logger.warning(f"GLiNER classification failed: {e}")
            return None

    def split_sentences(self, text: str) -> List[str]:
        """Not supported by GLiNER provider."""
        return []

    def resolve_coreferences(self, text: str) -> List[Dict]:
        """Not supported by GLiNER provider."""
        return []

    def analyze_sentiment(self, text: str) -> str:
        """Not supported by GLiNER provider."""
        return "neutral"
