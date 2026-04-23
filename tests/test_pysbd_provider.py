"""Tests for PySBDProvider -- pySBD is fully mocked, no real install needed."""

import sys
import types
from unittest.mock import MagicMock, patch


# ── Helpers ──────────────────────────────────────────────────────


def _make_mock_pysbd(segments=None):
    """Create a mock pysbd module with a mock Segmenter."""
    mock_pysbd = types.ModuleType("pysbd")
    mock_segmenter_instance = MagicMock()
    mock_segmenter_instance.segment.return_value = segments or [
        "Hello world.",
        "This is a test.",
    ]
    mock_pysbd.Segmenter = MagicMock(return_value=mock_segmenter_instance)
    return mock_pysbd, mock_segmenter_instance


def _fresh_provider():
    """Import a fresh PySBDProvider (no cached state)."""
    # Clear any cached module to get a fresh import
    mod_name = "mempalace.nlp_providers.pysbd_provider"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    from mempalace.nlp_providers.pysbd_provider import PySBDProvider

    return PySBDProvider()


# ── Properties ───────────────────────────────────────────────────


class TestPySBDProviderProperties:
    def test_name(self):
        from mempalace.nlp_providers.pysbd_provider import PySBDProvider

        p = PySBDProvider()
        assert p.name == "pysbd"

    def test_capabilities(self):
        from mempalace.nlp_providers.pysbd_provider import PySBDProvider

        p = PySBDProvider()
        assert p.capabilities == {"sentences", "negation"}

    def test_implements_nlp_provider(self):
        from mempalace.nlp_providers.base import NLPProvider
        from mempalace.nlp_providers.pysbd_provider import PySBDProvider

        p = PySBDProvider()
        assert isinstance(p, NLPProvider)


# ── is_available ─────────────────────────────────────────────────


class TestPySBDIsAvailable:
    def test_unavailable_when_feature_disabled(self, monkeypatch):
        """Without feature flag, provider is not available."""
        monkeypatch.delenv("MEMPALACE_NLP_SENTENCES", raising=False)
        monkeypatch.delenv("MEMPALACE_NLP_BACKEND", raising=False)
        p = _fresh_provider()
        assert p.is_available() is False

    def test_available_when_env_enabled_and_pysbd_installed(self, monkeypatch):
        """With MEMPALACE_NLP_SENTENCES=1 and pysbd importable, is_available is True."""
        monkeypatch.setenv("MEMPALACE_NLP_SENTENCES", "1")
        mock_pysbd, _ = _make_mock_pysbd()
        p = _fresh_provider()
        with patch.dict(sys.modules, {"pysbd": mock_pysbd}):
            # Force reload
            p._loaded = False
            p._available = None
            assert p.is_available() is True

    def test_unavailable_when_pysbd_not_installed(self, monkeypatch):
        """With feature flag on but pysbd not importable, is_available is False."""
        monkeypatch.setenv("MEMPALACE_NLP_SENTENCES", "1")
        p = _fresh_provider()
        # Ensure pysbd is not in sys.modules and import fails
        with patch.dict(sys.modules, {"pysbd": None}):
            p._loaded = False
            p._available = None
            # Importing None from sys.modules raises ImportError
            assert p.is_available() is False

    def test_available_with_backend_pysbd(self, monkeypatch):
        """Backend=pysbd also activates."""
        monkeypatch.delenv("MEMPALACE_NLP_SENTENCES", raising=False)
        monkeypatch.setenv("MEMPALACE_NLP_BACKEND", "pysbd")
        mock_pysbd, _ = _make_mock_pysbd()
        p = _fresh_provider()
        with patch.dict(sys.modules, {"pysbd": mock_pysbd}):
            p._loaded = False
            p._available = None
            assert p.is_available() is True

    def test_available_with_backend_spacy(self, monkeypatch):
        """Backend=spacy (higher than pysbd) also activates."""
        monkeypatch.delenv("MEMPALACE_NLP_SENTENCES", raising=False)
        monkeypatch.setenv("MEMPALACE_NLP_BACKEND", "spacy")
        mock_pysbd, _ = _make_mock_pysbd()
        p = _fresh_provider()
        with patch.dict(sys.modules, {"pysbd": mock_pysbd}):
            p._loaded = False
            p._available = None
            assert p.is_available() is True


# ── split_sentences ──────────────────────────────────────────────


class TestPySBDSplitSentences:
    def test_splits_basic_text(self, monkeypatch):
        """Segments text correctly via mocked pySBD."""
        monkeypatch.setenv("MEMPALACE_NLP_SENTENCES", "1")
        mock_pysbd, mock_seg = _make_mock_pysbd(["Hello world.", "This is a test."])
        p = _fresh_provider()
        with patch.dict(sys.modules, {"pysbd": mock_pysbd}):
            p._loaded = False
            p._available = None
            p._ensure_loaded()
            result = p.split_sentences("Hello world. This is a test.")
        assert result == ["Hello world.", "This is a test."]

    def test_strips_whitespace(self, monkeypatch):
        """Strips whitespace from segments."""
        monkeypatch.setenv("MEMPALACE_NLP_SENTENCES", "1")
        mock_pysbd, mock_seg = _make_mock_pysbd(["  Hello. ", " ", "World. "])
        p = _fresh_provider()
        with patch.dict(sys.modules, {"pysbd": mock_pysbd}):
            p._loaded = False
            result_after_load = None
            p._ensure_loaded()
            result_after_load = p.split_sentences("  Hello.  World. ")
        assert result_after_load == ["Hello.", "World."]

    def test_empty_list_when_not_loaded(self):
        """Returns empty list when pysbd not loaded."""
        p = _fresh_provider()
        p._loaded = True
        p._available = False
        assert p.split_sentences("test") == []

    def test_handles_segmenter_exception(self, monkeypatch):
        """Returns empty list if segmenter raises."""
        monkeypatch.setenv("MEMPALACE_NLP_SENTENCES", "1")
        mock_pysbd, mock_seg = _make_mock_pysbd()
        mock_seg.segment.side_effect = RuntimeError("boom")
        p = _fresh_provider()
        with patch.dict(sys.modules, {"pysbd": mock_pysbd}):
            p._loaded = False
            p._ensure_loaded()
            result = p.split_sentences("Hello world.")
        assert result == []


# ── split_sentences_with_negation ────────────────────────────────


class TestPySBDNegation:
    def test_detects_negation_in_sentence(self, monkeypatch):
        """Negated markers are identified correctly."""
        monkeypatch.setenv("MEMPALACE_NLP_SENTENCES", "1")
        text = "I don't like dogs. I love cats."
        mock_pysbd, mock_seg = _make_mock_pysbd(["I don't like dogs.", "I love cats."])
        p = _fresh_provider()
        with patch.dict(sys.modules, {"pysbd": mock_pysbd}):
            p._loaded = False
            p._ensure_loaded()
            result = p.split_sentences_with_negation(text, [r"like", r"love"])
        assert len(result) == 2
        assert result[0]["sentence"] == "I don't like dogs."
        assert "like" in result[0]["negated_markers"]
        assert result[1]["negated_markers"] == []

    def test_no_negation_markers(self, monkeypatch):
        """No negation found when none present."""
        monkeypatch.setenv("MEMPALACE_NLP_SENTENCES", "1")
        mock_pysbd, _ = _make_mock_pysbd(["I enjoy coding."])
        p = _fresh_provider()
        with patch.dict(sys.modules, {"pysbd": mock_pysbd}):
            p._loaded = False
            p._ensure_loaded()
            result = p.split_sentences_with_negation("I enjoy coding.", [r"enjoy"])
        assert result[0]["negated_markers"] == []


# ── Lazy loading ─────────────────────────────────────────────────


class TestPySBDLazyLoading:
    def test_loads_only_once(self, monkeypatch):
        """Segmenter is created only once even if called multiple times."""
        monkeypatch.setenv("MEMPALACE_NLP_SENTENCES", "1")
        mock_pysbd, _ = _make_mock_pysbd()
        p = _fresh_provider()
        with patch.dict(sys.modules, {"pysbd": mock_pysbd}):
            p._ensure_loaded()
            p._ensure_loaded()
            p._ensure_loaded()
        # Segmenter called only once
        assert mock_pysbd.Segmenter.call_count == 1

    def test_init_exception_marks_unavailable(self, monkeypatch):
        """If pysbd.Segmenter() raises, provider is marked unavailable."""
        monkeypatch.setenv("MEMPALACE_NLP_SENTENCES", "1")
        mock_pysbd, _ = _make_mock_pysbd()
        mock_pysbd.Segmenter.side_effect = RuntimeError("init fail")
        p = _fresh_provider()
        with patch.dict(sys.modules, {"pysbd": mock_pysbd}):
            p._loaded = False
            p._ensure_loaded()
        assert p._available is False


# ── Unsupported methods ──────────────────────────────────────────


class TestPySBDUnsupported:
    def test_extract_entities_returns_empty(self):
        p = _fresh_provider()
        assert p.extract_entities("test") == []

    def test_extract_triples_returns_empty(self):
        p = _fresh_provider()
        assert p.extract_triples("test") == []

    def test_classify_text_returns_none(self):
        p = _fresh_provider()
        assert p.classify_text("test", ["a"]) is None

    def test_resolve_coreferences_returns_empty(self):
        p = _fresh_provider()
        assert p.resolve_coreferences("test") == []

    def test_analyze_sentiment_returns_neutral(self):
        p = _fresh_provider()
        assert p.analyze_sentiment("test") == "neutral"
