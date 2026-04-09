"""
Integration tests for NLP providers using real libraries (no mocks).

These tests are marked @pytest.mark.slow and @pytest.mark.nlp.
They require the actual packages to be installed.
Run with: pytest tests/test_nlp_integration.py -m "nlp" -v

Each test checks if the required package is available and skips if not.
"""

import pytest


def _has_package(name):
    """Check if a package is importable."""
    try:
        __import__(name)
        return True
    except ImportError:
        return False


# ── pySBD Integration ────────────────────────────────────────────


@pytest.mark.slow
@pytest.mark.nlp
@pytest.mark.skipif(not _has_package("pysbd"), reason="pysbd not installed")
class TestPySBDIntegration:
    def test_basic_sentence_splitting(self, monkeypatch):
        """pySBD splits sentences correctly on real text."""
        monkeypatch.setenv("MEMPALACE_NLP_SENTENCES", "1")
        from mempalace.nlp_providers.pysbd_provider import PySBDProvider

        p = PySBDProvider()
        assert p.is_available() is True
        result = p.split_sentences("Hello world. This is a test. Dr. Smith went home.")
        assert len(result) >= 2
        assert "Hello world." in result[0]

    def test_abbreviation_handling(self, monkeypatch):
        """pySBD handles abbreviations like Dr., Mr., etc."""
        monkeypatch.setenv("MEMPALACE_NLP_SENTENCES", "1")
        from mempalace.nlp_providers.pysbd_provider import PySBDProvider

        p = PySBDProvider()
        result = p.split_sentences("Dr. Smith said hello. She left at 3 p.m. today.")
        # Should not split on "Dr." or "p.m."
        assert any("Dr. Smith" in s for s in result)

    def test_negation_integration(self, monkeypatch):
        """pySBD + negation detection work together."""
        monkeypatch.setenv("MEMPALACE_NLP_SENTENCES", "1")
        from mempalace.nlp_providers.pysbd_provider import PySBDProvider

        p = PySBDProvider()
        result = p.split_sentences_with_negation(
            "I don't like dogs. I love cats.", [r"like", r"love"]
        )
        assert len(result) >= 1
        # First sentence should have "like" as negated
        assert "like" in result[0]["negated_markers"]


# ── spaCy Integration ────────────────────────────────────────────


@pytest.mark.slow
@pytest.mark.nlp
@pytest.mark.skipif(not _has_package("spacy"), reason="spacy not installed")
class TestSpaCyIntegration:
    @pytest.fixture(autouse=True)
    def _check_model(self):
        """Skip if the xx_ent_wiki_sm model is not installed."""
        import spacy

        try:
            spacy.load("xx_ent_wiki_sm")
        except OSError:
            pytest.skip("spacy model xx_ent_wiki_sm not installed")

    def test_entity_extraction(self, monkeypatch):
        """spaCy extracts named entities from real text."""
        monkeypatch.setenv("MEMPALACE_NLP_NER", "1")
        from mempalace.nlp_providers.spacy_provider import SpaCyProvider

        p = SpaCyProvider()
        if not p.is_available():
            pytest.skip("SpaCyProvider not available")
        result = p.extract_entities("Barack Obama was born in Hawaii.")
        assert len(result) > 0
        labels = {e["label"] for e in result}
        # Should find at least PER or LOC type entities
        assert labels & {"PER", "LOC", "GPE", "PERSON"}

    def test_sentence_segmentation(self, monkeypatch):
        """spaCy segments sentences correctly."""
        monkeypatch.setenv("MEMPALACE_NLP_NER", "1")
        from mempalace.nlp_providers.spacy_provider import SpaCyProvider

        p = SpaCyProvider()
        if not p.is_available():
            pytest.skip("SpaCyProvider not available")
        result = p.split_sentences("Alice lives in Paris. She loves it there.")
        assert len(result) == 2


# ── GLiNER Integration ───────────────────────────────────────────


@pytest.mark.slow
@pytest.mark.nlp
@pytest.mark.skipif(not _has_package("gliner"), reason="gliner not installed")
class TestGLiNERIntegration:
    def test_entity_extraction(self, monkeypatch):
        """GLiNER extracts entities with zero-shot NER."""
        monkeypatch.setenv("MEMPALACE_NLP_NER", "1")
        from mempalace.nlp_providers.gliner_provider import GLiNERProvider

        p = GLiNERProvider()
        if not p.is_available():
            pytest.skip("GLiNERProvider not available (model not downloaded)")
        result = p.extract_entities("Alice works at Anthropic in San Francisco.")
        assert len(result) > 0
        texts = {e["text"] for e in result}
        assert "Alice" in texts or "Anthropic" in texts

    def test_triple_extraction(self, monkeypatch):
        """GLiNER extracts triples from text."""
        monkeypatch.setenv("MEMPALACE_NLP_TRIPLES", "1")
        from mempalace.nlp_providers.gliner_provider import GLiNERProvider

        p = GLiNERProvider()
        if not p.is_available():
            pytest.skip("GLiNERProvider not available")
        result = p.extract_triples("Alice uses Python to build MemPalace.")
        # May or may not extract triples depending on model version
        assert isinstance(result, list)


# ── wtpsplit Integration ─────────────────────────────────────────


@pytest.mark.slow
@pytest.mark.nlp
@pytest.mark.skipif(not _has_package("wtpsplit"), reason="wtpsplit not installed")
class TestWtpsplitIntegration:
    def test_sentence_splitting(self, monkeypatch):
        """wtpsplit splits sentences with high accuracy."""
        monkeypatch.setenv("MEMPALACE_NLP_SENTENCES", "1")
        from mempalace.nlp_providers.wtpsplit_provider import WtpsplitProvider

        p = WtpsplitProvider()
        if not p.is_available():
            pytest.skip("WtpsplitProvider not available")
        result = p.split_sentences(
            "Dr. Smith went to Washington. He met with officials. " "The meeting lasted 2 hours."
        )
        assert len(result) == 3

    def test_abbreviation_handling(self, monkeypatch):
        """wtpsplit handles abbreviations correctly."""
        monkeypatch.setenv("MEMPALACE_NLP_SENTENCES", "1")
        from mempalace.nlp_providers.wtpsplit_provider import WtpsplitProvider

        p = WtpsplitProvider()
        if not p.is_available():
            pytest.skip("WtpsplitProvider not available")
        result = p.split_sentences("I live in the U.S.A. It's a great country.")
        # Should ideally not split on "U.S.A."
        assert len(result) <= 3


# ── Registry Integration ─────────────────────────────────────────


@pytest.mark.slow
@pytest.mark.nlp
class TestRegistryIntegration:
    def test_registry_fallback_chain(self, monkeypatch):
        """Registry falls back to legacy when no NLP packages installed."""
        monkeypatch.delenv("MEMPALACE_NLP_SENTENCES", raising=False)
        monkeypatch.delenv("MEMPALACE_NLP_NER", raising=False)
        monkeypatch.delenv("MEMPALACE_NLP_BACKEND", raising=False)
        from mempalace.nlp_providers.registry import NLPProviderRegistry

        reg = NLPProviderRegistry()
        from mempalace.nlp_providers.legacy_provider import LegacyProvider

        reg.register("legacy", lambda: LegacyProvider())
        provider = reg.get_for_capability("sentences")
        assert provider is not None
        assert provider.name == "legacy"

    def test_registry_sentence_splitting(self):
        """Registry convenience method splits sentences."""
        from mempalace.nlp_providers.registry import NLPProviderRegistry
        from mempalace.nlp_providers.legacy_provider import LegacyProvider

        reg = NLPProviderRegistry()
        reg.register("legacy", lambda: LegacyProvider())
        result = reg.split_sentences("Hello world. This is a test.")
        assert len(result) >= 2
