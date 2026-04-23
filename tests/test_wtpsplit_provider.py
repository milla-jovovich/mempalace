"""Tests for WtpsplitProvider -- wtpsplit is fully mocked, no real install needed."""

import sys
import types
from unittest.mock import MagicMock, patch

from mempalace.nlp_providers.wtpsplit_provider import WtpsplitProvider


# ── Helpers ──────────────────────────────────────────────────────


def _make_mock_wtpsplit(sentences=None):
    """Create a mock wtpsplit module."""
    mock_wtpsplit = types.ModuleType("wtpsplit")
    mock_model = MagicMock()
    mock_model.split.return_value = sentences or ["Hello world.", "This is a test."]
    mock_wtpsplit.SaT = MagicMock(return_value=mock_model)
    return mock_wtpsplit, mock_model


def _fresh_provider():
    return WtpsplitProvider()


def _setup_provider_with_mock(monkeypatch, mock_wtpsplit):
    monkeypatch.setenv("MEMPALACE_NLP_SENTENCES", "1")
    p = _fresh_provider()
    mock_mm = MagicMock()
    mock_mm.ensure_model.return_value = None
    with (
        patch.dict(sys.modules, {"wtpsplit": mock_wtpsplit}),
        patch(
            "mempalace.nlp_providers.model_manager.ModelManager.get",
            return_value=mock_mm,
        ),
    ):
        p._loaded = False
        p._available = None
        p._ensure_loaded()
    return p


# ── Properties ───────────────────────────────────────────────────


class TestWtpsplitProperties:
    def test_name(self):
        p = _fresh_provider()
        assert p.name == "wtpsplit"

    def test_capabilities(self):
        p = _fresh_provider()
        assert p.capabilities == {"sentences"}

    def test_implements_nlp_provider(self):
        from mempalace.nlp_providers.base import NLPProvider

        p = _fresh_provider()
        assert isinstance(p, NLPProvider)


# ── is_available ─────────────────────────────────────────────────


class TestWtpsplitIsAvailable:
    def test_unavailable_when_feature_disabled(self, monkeypatch):
        monkeypatch.delenv("MEMPALACE_NLP_SENTENCES", raising=False)
        monkeypatch.delenv("MEMPALACE_NLP_BACKEND", raising=False)
        p = _fresh_provider()
        assert p.is_available() is False

    def test_available_when_sentences_enabled(self, monkeypatch):
        mock_wtpsplit, _ = _make_mock_wtpsplit()
        p = _setup_provider_with_mock(monkeypatch, mock_wtpsplit)
        assert p.is_available() is True

    def test_unavailable_when_not_installed(self, monkeypatch):
        monkeypatch.setenv("MEMPALACE_NLP_SENTENCES", "1")
        p = _fresh_provider()
        with patch.dict(sys.modules, {"wtpsplit": None}):
            p._loaded = False
            p._available = None
            assert p.is_available() is False

    def test_available_with_backend_full(self, monkeypatch):
        monkeypatch.delenv("MEMPALACE_NLP_SENTENCES", raising=False)
        monkeypatch.setenv("MEMPALACE_NLP_BACKEND", "full")
        mock_wtpsplit, _ = _make_mock_wtpsplit()
        p = _fresh_provider()
        mock_mm = MagicMock()
        mock_mm.ensure_model.return_value = None
        with (
            patch.dict(sys.modules, {"wtpsplit": mock_wtpsplit}),
            patch(
                "mempalace.nlp_providers.model_manager.ModelManager.get",
                return_value=mock_mm,
            ),
        ):
            p._loaded = False
            p._available = None
            assert p.is_available() is True

    def test_unavailable_when_model_not_found(self, monkeypatch):
        monkeypatch.setenv("MEMPALACE_NLP_SENTENCES", "1")
        mock_wtpsplit = types.ModuleType("wtpsplit")
        mock_wtpsplit.SaT = MagicMock(side_effect=RuntimeError("no model"))
        p = _fresh_provider()
        mock_mm = MagicMock()
        mock_mm.ensure_model.return_value = None
        with (
            patch.dict(sys.modules, {"wtpsplit": mock_wtpsplit}),
            patch(
                "mempalace.nlp_providers.model_manager.ModelManager.get",
                return_value=mock_mm,
            ),
        ):
            p._loaded = False
            p._available = None
            assert p.is_available() is False


# ── split_sentences ──────────────────────────────────────────────


class TestWtpsplitSplitSentences:
    def test_splits_basic(self, monkeypatch):
        mock_wtpsplit, _ = _make_mock_wtpsplit(["Hello.", "World."])
        p = _setup_provider_with_mock(monkeypatch, mock_wtpsplit)
        result = p.split_sentences("Hello. World.")
        assert result == ["Hello.", "World."]

    def test_strips_whitespace(self, monkeypatch):
        mock_wtpsplit, _ = _make_mock_wtpsplit(["  Hello. ", " ", " World. "])
        p = _setup_provider_with_mock(monkeypatch, mock_wtpsplit)
        result = p.split_sentences("  Hello.  World. ")
        assert result == ["Hello.", "World."]

    def test_returns_empty_when_not_loaded(self):
        p = _fresh_provider()
        p._loaded = True
        p._available = False
        assert p.split_sentences("test") == []

    def test_handles_exception(self, monkeypatch):
        mock_wtpsplit, mock_model = _make_mock_wtpsplit()
        p = _setup_provider_with_mock(monkeypatch, mock_wtpsplit)
        p._model.split.side_effect = RuntimeError("split error")
        assert p.split_sentences("test") == []

    def test_truncates_long_text(self, monkeypatch):
        mock_wtpsplit, mock_model = _make_mock_wtpsplit(["Truncated."])
        p = _setup_provider_with_mock(monkeypatch, mock_wtpsplit)
        long_text = "a" * 60000
        p.split_sentences(long_text)
        # The text passed to split should be truncated
        called_text = mock_model.split.call_args[0][0]
        assert len(called_text) == 50000


# ── Lazy loading ─────────────────────────────────────────────────


class TestWtpsplitLazyLoading:
    def test_loads_only_once(self, monkeypatch):
        mock_wtpsplit, _ = _make_mock_wtpsplit()
        monkeypatch.setenv("MEMPALACE_NLP_SENTENCES", "1")
        p = _fresh_provider()
        mock_mm = MagicMock()
        mock_mm.ensure_model.return_value = None
        with (
            patch.dict(sys.modules, {"wtpsplit": mock_wtpsplit}),
            patch(
                "mempalace.nlp_providers.model_manager.ModelManager.get",
                return_value=mock_mm,
            ),
        ):
            p._ensure_loaded()
            p._ensure_loaded()
        assert mock_wtpsplit.SaT.call_count == 1

    def test_model_path_from_manager(self, monkeypatch):
        mock_wtpsplit, _ = _make_mock_wtpsplit()
        monkeypatch.setenv("MEMPALACE_NLP_SENTENCES", "1")
        p = _fresh_provider()
        mock_mm = MagicMock()
        mock_mm.ensure_model.return_value = "/fake/path"
        with (
            patch.dict(sys.modules, {"wtpsplit": mock_wtpsplit}),
            patch(
                "mempalace.nlp_providers.model_manager.ModelManager.get",
                return_value=mock_mm,
            ),
        ):
            p._ensure_loaded()
        mock_wtpsplit.SaT.assert_called_once_with("/fake/path")


# ── Unsupported ──────────────────────────────────────────────────


class TestWtpsplitUnsupported:
    def test_extract_entities(self):
        assert _fresh_provider().extract_entities("test") == []

    def test_extract_triples(self):
        assert _fresh_provider().extract_triples("test") == []

    def test_classify_text(self):
        assert _fresh_provider().classify_text("test", ["a"]) is None

    def test_resolve_coreferences(self):
        assert _fresh_provider().resolve_coreferences("test") == []

    def test_analyze_sentiment(self):
        assert _fresh_provider().analyze_sentiment("test") == "neutral"
