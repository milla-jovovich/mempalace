"""
legacy_provider.py -- Wraps the existing regex/heuristic code as an NLP provider.

This provider is always available and requires no extra dependencies.
It delegates to entity_detector.extract_candidates, general_extractor, etc.
"""

import re
from typing import List, Dict, Optional


class LegacyProvider:
    """NLP provider wrapping current regex/heuristic pipeline."""

    @property
    def name(self) -> str:
        return "legacy"

    @property
    def capabilities(self) -> set:
        return {"ner", "sentences", "classify", "sentiment"}

    def extract_entities(self, text: str) -> List[Dict]:
        """Extract named entities using regex-based candidate extraction."""
        from mempalace.entity_detector import extract_candidates

        candidates = extract_candidates(text)
        return [{"text": name, "label": "UNKNOWN", "start": 0, "end": 0} for name in candidates]

    def split_sentences(self, text: str) -> List[str]:
        """Split text into sentences using regex."""
        return [s for s in re.split(r"[.!?\n]+", text) if s.strip()]

    def extract_triples(self, text: str) -> List[Dict]:
        """Legacy has no triple extraction."""
        return []

    def classify_text(self, text: str, labels: List[str]) -> Optional[Dict]:
        """Classify text using general_extractor marker scoring."""
        from mempalace.general_extractor import extract_memories

        memories = extract_memories(text)
        if memories:
            return {"label": memories[0]["memory_type"], "confidence": 0.5}
        return None

    def resolve_coreferences(self, text: str) -> List[Dict]:
        """Legacy has no coreference resolution."""
        return []

    def analyze_sentiment(self, text: str) -> str:
        """Analyze sentiment using bag-of-words heuristic."""
        from mempalace.general_extractor import _get_sentiment

        return _get_sentiment(text)

    def is_available(self) -> bool:
        """Legacy provider is always available."""
        return True
