"""
base.py -- NLP provider abstraction layer.

Defines the Protocol interface that all NLP providers implement.
Providers are registered, selected, lazily loaded, and gracefully degrade.
"""

from typing import Protocol, List, Dict, Optional, runtime_checkable


@runtime_checkable
class NLPProvider(Protocol):
    """Protocol for NLP providers. Each method is optional -- providers
    implement only the capabilities they support."""

    @property
    def name(self) -> str:
        """Provider identifier (e.g., 'spacy', 'gliner', 'legacy')."""
        ...

    @property
    def capabilities(self) -> set:
        """Set of capability strings this provider supports.
        E.g., {'ner', 'sentences', 'coref'}"""
        ...

    def extract_entities(self, text: str) -> List[Dict]:
        """Extract named entities. Returns [{"text", "label", "start", "end"}]"""
        ...

    def split_sentences(self, text: str) -> List[str]:
        """Split text into sentences."""
        ...

    def extract_triples(self, text: str) -> List[Dict]:
        """Extract KG triples. Returns [{"subject", "predicate", "object", "confidence"}]"""
        ...

    def classify_text(self, text: str, labels: List[str]) -> Optional[Dict]:
        """Classify text. Returns {"label": str, "confidence": float}"""
        ...

    def resolve_coreferences(self, text: str) -> List[Dict]:
        """Resolve pronouns. Returns [{"pronoun", "referent"}]"""
        ...

    def analyze_sentiment(self, text: str) -> str:
        """Returns 'positive', 'negative', or 'neutral'."""
        ...

    def is_available(self) -> bool:
        """Check if this provider's dependencies are installed and models loaded."""
        ...
