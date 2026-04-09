"""
registry.py -- Provider registry with selection logic, lazy loading, and graceful degradation.
"""

import logging
import re
from typing import Optional, List, Dict

from .base import NLPProvider

logger = logging.getLogger(__name__)


class NLPProviderRegistry:
    """
    Central registry for NLP providers.

    Selects the best provider for each capability based on the active
    NLP config. Falls back gracefully when providers are unavailable.
    """

    def __init__(self):
        self._providers: Dict[str, object] = {}
        self._loaded: Dict[str, bool] = {}

    def register(self, name: str, provider_factory):
        """Register a provider factory (not the instance -- lazy loading)."""
        self._providers[name] = provider_factory
        self._loaded[name] = False

    def _load_provider(self, name: str) -> Optional[NLPProvider]:
        """Lazily load a provider instance."""
        if self._loaded.get(name):
            return self._providers.get(name)

        factory = self._providers.get(name)
        if factory is None:
            return None

        try:
            if callable(factory) and not isinstance(factory, NLPProvider):
                instance = factory()
                self._providers[name] = instance
            self._loaded[name] = True
            return self._providers[name]
        except Exception as e:
            logger.debug(f"Failed to load provider '{name}': {e}")
            self._loaded[name] = True  # Don't retry
            self._providers[name] = None
            return None

    def get_for_capability(self, capability: str) -> Optional[NLPProvider]:
        """Get the best available provider for a specific capability."""
        # Priority order for each capability
        PRIORITY = {
            "ner": ["gliner", "spacy", "legacy"],
            "sentences": ["wtpsplit", "spacy", "pysbd", "legacy"],
            "triples": ["gliner", "slm"],
            "classify": ["gliner", "slm", "legacy"],
            "coref": ["spacy", "slm"],
            "sentiment": ["slm", "legacy"],
        }

        candidates = PRIORITY.get(capability, [])
        for name in candidates:
            provider = self._load_provider(name)
            if provider and provider.is_available() and capability in provider.capabilities:
                return provider

        return None

    def extract_entities(self, text: str) -> List[Dict]:
        """Convenience: extract entities via best available provider."""
        provider = self.get_for_capability("ner")
        if provider:
            return provider.extract_entities(text)
        return []

    def split_sentences(self, text: str) -> List[str]:
        """Convenience: split sentences via best available provider."""
        provider = self.get_for_capability("sentences")
        if provider:
            return provider.split_sentences(text)
        # Ultimate fallback
        return [s for s in re.split(r"[.!?\n]+", text) if s.strip()]

    def extract_triples(self, text: str) -> List[Dict]:
        """Convenience: extract triples via best available provider."""
        provider = self.get_for_capability("triples")
        if provider:
            return provider.extract_triples(text)
        return []

    def classify_text(self, text: str, labels: List[str]) -> Optional[Dict]:
        """Convenience: classify text via best available provider."""
        provider = self.get_for_capability("classify")
        if provider:
            return provider.classify_text(text, labels)
        return None


# Global registry instance
_registry: Optional[NLPProviderRegistry] = None


def get_registry() -> NLPProviderRegistry:
    """Get or create the global provider registry."""
    global _registry
    if _registry is None:
        _registry = NLPProviderRegistry()
        _register_default_providers(_registry)
    return _registry


def _register_default_providers(registry: NLPProviderRegistry):
    """Register all known providers (lazy -- not loaded until used)."""
    registry.register("legacy", lambda: _make_legacy_provider())
    registry.register("pysbd", lambda: _make_pysbd_provider())
    registry.register("spacy", lambda: _make_spacy_provider())
    registry.register("gliner", lambda: _make_gliner_provider())
    registry.register("wtpsplit", lambda: _make_wtpsplit_provider())
    registry.register("slm", lambda: _make_slm_provider())


def _make_legacy_provider():
    from .legacy_provider import LegacyProvider

    return LegacyProvider()


def _make_pysbd_provider():
    from .pysbd_provider import PySBDProvider

    return PySBDProvider()


def _make_spacy_provider():
    from .spacy_provider import SpaCyProvider

    return SpaCyProvider()


def _make_gliner_provider():
    from .gliner_provider import GLiNERProvider

    return GLiNERProvider()


def _make_wtpsplit_provider():
    from .wtpsplit_provider import WtpsplitProvider

    return WtpsplitProvider()


def _make_slm_provider():
    from .slm_provider import SLMProvider

    return SLMProvider()
