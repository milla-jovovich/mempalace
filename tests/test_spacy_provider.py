"""Tests for SpaCyProvider -- spaCy is fully mocked, no real install needed."""

import sys
import types
import threading
from unittest.mock import MagicMock, patch, PropertyMock

from mempalace.nlp_providers.spacy_provider import SpaCyProvider


# ── Helpers ──────────────────────────────────────────────────────


def _make_mock_spacy(entities=None, sentences=None):
    """Create a mock spacy module with mock nlp, Doc, entities, and sentences."""
    mock_spacy = types.ModuleType("spacy")

    # Mock entity (Span-like)
    def _make_ent(text, label, start_char, end_char):
        ent = MagicMock()
        ent.text = text
        ent.label_ = label
        ent.start_char = start_char
        ent.end_char = end_char
        return ent

    # Mock sentence (Span-like)
    def _make_sent(text):
        sent = MagicMock()
        sent.text = text
        return sent

    # Default entities
    if entities is None:
        entities = [
            _make_ent("Alice", "PER", 0, 5),
            _make_ent("Paris", "LOC", 14, 19),
        ]

    # Default sentences
    if sentences is None:
        sentences = [_make_sent("Alice lives in Paris."), _make_sent("She loves it.")]

    # Mock Doc
    mock_doc = MagicMock()
    mock_doc.ents = entities
    type(mock_doc).sents = PropertyMock(return_value=iter(sentences))

    # Mock nlp callable
    mock_nlp = MagicMock(return_value=mock_doc)

    # spacy.load returns mock_nlp
    mock_spacy.load = MagicMock(return_value=mock_nlp)

    return mock_spacy, mock_nlp, mock_doc


def _fresh_provider():
    """Get a fresh SpaCyProvider (no cached state)."""
    return SpaCyProvider()


def _setup_provider_with_mock(monkeypatch, mock_spacy):
    """Set up a provider with mocked spacy and ModelManager."""
    monkeypatch.setenv("MEMPALACE_NLP_NER", "1")
    p = _fresh_provider()

    # Mock ModelManager.get().ensure_model() to return a fake path
    mock_mm_instance = MagicMock()
    mock_mm_instance.ensure_model.return_value = None  # triggers direct load

    with (
        patch.dict(sys.modules, {"spacy": mock_spacy}),
        patch(
            "mempalace.nlp_providers.model_manager.ModelManager.get",
            return_value=mock_mm_instance,
        ),
    ):
        p._loaded = False
        p._available = None
        p._ensure_loaded()
    return p


# ── Properties ───────────────────────────────────────────────────


class TestSpaCyProviderProperties:
    def test_name(self):
        p = _fresh_provider()
        assert p.name == "spacy"

    def test_capabilities(self):
        p = _fresh_provider()
        assert p.capabilities == {"ner", "sentences", "coref"}

    def test_implements_nlp_provider(self):
        from mempalace.nlp_providers.base import NLPProvider

        p = _fresh_provider()
        assert isinstance(p, NLPProvider)


# ── is_available ─────────────────────────────────────────────────


class TestSpaCyIsAvailable:
    def test_unavailable_when_feature_disabled(self, monkeypatch):
        """Without feature flag, provider is not available."""
        monkeypatch.delenv("MEMPALACE_NLP_NER", raising=False)
        monkeypatch.delenv("MEMPALACE_NLP_SENTENCES", raising=False)
        monkeypatch.delenv("MEMPALACE_NLP_BACKEND", raising=False)
        p = _fresh_provider()
        assert p.is_available() is False

    def test_available_when_ner_enabled_and_spacy_installed(self, monkeypatch):
        """With MEMPALACE_NLP_NER=1 and spacy importable, is_available is True."""
        mock_spacy, _, _ = _make_mock_spacy()
        p = _setup_provider_with_mock(monkeypatch, mock_spacy)
        assert p.is_available() is True

    def test_unavailable_when_spacy_not_installed(self, monkeypatch):
        """With feature flag on but spacy not importable, is_available is False."""
        monkeypatch.setenv("MEMPALACE_NLP_NER", "1")
        p = _fresh_provider()
        with patch.dict(sys.modules, {"spacy": None}):
            p._loaded = False
            p._available = None
            assert p.is_available() is False

    def test_available_with_backend_spacy(self, monkeypatch):
        """Backend=spacy also activates."""
        monkeypatch.delenv("MEMPALACE_NLP_NER", raising=False)
        monkeypatch.setenv("MEMPALACE_NLP_BACKEND", "spacy")
        mock_spacy, _, _ = _make_mock_spacy()
        p = _fresh_provider()

        mock_mm = MagicMock()
        mock_mm.ensure_model.return_value = None

        with (
            patch.dict(sys.modules, {"spacy": mock_spacy}),
            patch(
                "mempalace.nlp_providers.model_manager.ModelManager.get",
                return_value=mock_mm,
            ),
        ):
            p._loaded = False
            p._available = None
            assert p.is_available() is True

    def test_available_with_sentences_env(self, monkeypatch):
        """MEMPALACE_NLP_SENTENCES=1 also enables spacy provider."""
        monkeypatch.delenv("MEMPALACE_NLP_NER", raising=False)
        monkeypatch.setenv("MEMPALACE_NLP_SENTENCES", "1")
        mock_spacy, _, _ = _make_mock_spacy()
        p = _fresh_provider()

        mock_mm = MagicMock()
        mock_mm.ensure_model.return_value = None

        with (
            patch.dict(sys.modules, {"spacy": mock_spacy}),
            patch(
                "mempalace.nlp_providers.model_manager.ModelManager.get",
                return_value=mock_mm,
            ),
        ):
            p._loaded = False
            p._available = None
            assert p.is_available() is True

    def test_unavailable_when_model_not_found(self, monkeypatch):
        """When spacy is installed but model can't load, unavailable."""
        monkeypatch.setenv("MEMPALACE_NLP_NER", "1")
        mock_spacy = types.ModuleType("spacy")
        mock_spacy.load = MagicMock(side_effect=OSError("model not found"))
        p = _fresh_provider()

        mock_mm = MagicMock()
        mock_mm.ensure_model.return_value = None

        with (
            patch.dict(sys.modules, {"spacy": mock_spacy}),
            patch(
                "mempalace.nlp_providers.model_manager.ModelManager.get",
                return_value=mock_mm,
            ),
        ):
            p._loaded = False
            p._available = None
            assert p.is_available() is False


# ── extract_entities ─────────────────────────────────────────────


class TestSpaCyExtractEntities:
    def test_extracts_entities_correctly(self, monkeypatch):
        """Entities are returned in the correct format."""
        mock_spacy, mock_nlp, _ = _make_mock_spacy()
        p = _setup_provider_with_mock(monkeypatch, mock_spacy)
        result = p.extract_entities("Alice lives in Paris.")
        assert len(result) == 2
        assert result[0] == {"text": "Alice", "label": "PER", "start": 0, "end": 5}
        assert result[1] == {"text": "Paris", "label": "LOC", "start": 14, "end": 19}

    def test_returns_empty_when_not_loaded(self):
        """Returns empty list when spacy not loaded."""
        p = _fresh_provider()
        p._loaded = True
        p._available = False
        assert p.extract_entities("test") == []

    def test_handles_nlp_exception(self, monkeypatch):
        """Returns empty list if nlp() raises."""
        mock_spacy, mock_nlp, _ = _make_mock_spacy()
        p = _setup_provider_with_mock(monkeypatch, mock_spacy)
        mock_nlp.side_effect = RuntimeError("NLP error")
        assert p.extract_entities("test") == []


# ── split_sentences ──────────────────────────────────────────────


class TestSpaCySplitSentences:
    def test_splits_sentences(self, monkeypatch):
        """Sentences are split correctly."""
        mock_spacy, _, _ = _make_mock_spacy()
        p = _setup_provider_with_mock(monkeypatch, mock_spacy)
        result = p.split_sentences("Alice lives in Paris. She loves it.")
        assert len(result) == 2
        assert result[0] == "Alice lives in Paris."
        assert result[1] == "She loves it."

    def test_strips_whitespace(self, monkeypatch):
        """Strips whitespace from sentences."""

        def _make_sent(text):
            sent = MagicMock()
            sent.text = text
            return sent

        mock_spacy, _, mock_doc = _make_mock_spacy(
            sentences=[_make_sent("  Hello. "), _make_sent(" "), _make_sent("World. ")]
        )
        p = _setup_provider_with_mock(monkeypatch, mock_spacy)
        result = p.split_sentences("  Hello.  World. ")
        assert result == ["Hello.", "World."]

    def test_returns_empty_when_not_loaded(self):
        """Returns empty list when spacy not loaded."""
        p = _fresh_provider()
        p._loaded = True
        p._available = False
        assert p.split_sentences("test") == []


# ── Lazy loading ─────────────────────────────────────────────────


class TestSpaCyLazyLoading:
    def test_loads_only_once(self, monkeypatch):
        """Model is loaded only once even if called multiple times."""
        mock_spacy, _, _ = _make_mock_spacy()
        monkeypatch.setenv("MEMPALACE_NLP_NER", "1")
        p = _fresh_provider()

        mock_mm = MagicMock()
        mock_mm.ensure_model.return_value = None

        with (
            patch.dict(sys.modules, {"spacy": mock_spacy}),
            patch(
                "mempalace.nlp_providers.model_manager.ModelManager.get",
                return_value=mock_mm,
            ),
        ):
            p._ensure_loaded()
            p._ensure_loaded()
            p._ensure_loaded()

        # spacy.load called only once
        assert mock_spacy.load.call_count == 1

    def test_thread_safe_loading(self, monkeypatch):
        """Concurrent _ensure_loaded calls don't cause multiple loads."""
        mock_spacy, _, _ = _make_mock_spacy()
        monkeypatch.setenv("MEMPALACE_NLP_NER", "1")
        p = _fresh_provider()

        mock_mm = MagicMock()
        mock_mm.ensure_model.return_value = None

        load_count = {"n": 0}
        original_load = mock_spacy.load

        def slow_load(name):
            load_count["n"] += 1
            return original_load(name)

        mock_spacy.load = MagicMock(side_effect=slow_load)

        with (
            patch.dict(sys.modules, {"spacy": mock_spacy}),
            patch(
                "mempalace.nlp_providers.model_manager.ModelManager.get",
                return_value=mock_mm,
            ),
        ):
            threads = [threading.Thread(target=p._ensure_loaded) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        # Should only load once despite concurrent calls
        assert load_count["n"] == 1


# ── resolve_coreferences ────────────────────────────────────────


class TestSpaCyCoreference:
    def test_placeholder_returns_empty(self):
        """Coreference placeholder returns empty list."""
        p = _fresh_provider()
        assert p.resolve_coreferences("He went to the store.") == []


# ── Unsupported methods ──────────────────────────────────────────


class TestSpaCyUnsupported:
    def test_extract_triples_returns_empty(self):
        p = _fresh_provider()
        assert p.extract_triples("test") == []

    def test_classify_text_returns_none(self):
        p = _fresh_provider()
        assert p.classify_text("test", ["a"]) is None

    def test_analyze_sentiment_returns_neutral(self):
        p = _fresh_provider()
        assert p.analyze_sentiment("test") == "neutral"
