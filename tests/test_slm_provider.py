"""Tests for SLMProvider -- onnxruntime_genai is fully mocked, no real install needed."""

import sys
import types
from unittest.mock import MagicMock, patch

from mempalace.nlp_providers.slm_provider import SLMProvider


# ── Helpers ──────────────────────────────────────────────────────


def _make_mock_og(generated_text="positive"):
    """Create a mock onnxruntime_genai module."""
    import numpy as np

    mock_og = types.ModuleType("onnxruntime_genai")

    mock_model = MagicMock()
    mock_tokenizer = MagicMock()
    mock_tokenizer.encode.return_value = np.array([1, 2, 3])
    mock_tokenizer.decode.return_value = generated_text

    # Mock the Generator class (new onnxruntime-genai API)
    mock_generator = MagicMock()
    # Simulate generating tokens then stopping
    mock_generator.is_done.side_effect = [False, True]
    mock_generator.get_next_tokens.return_value = [4]
    mock_og.Generator = MagicMock(return_value=mock_generator)

    mock_og.Model = MagicMock(return_value=mock_model)
    mock_og.Tokenizer = MagicMock(return_value=mock_tokenizer)
    mock_og.GeneratorParams = MagicMock()

    return mock_og, mock_model, mock_tokenizer


def _fresh_provider():
    return SLMProvider()


def _setup_provider_with_mock(monkeypatch, mock_og, model_path="/fake/model"):
    monkeypatch.setenv("MEMPALACE_NLP_SLM", "1")
    p = _fresh_provider()
    mock_mm = MagicMock()
    mock_mm.ensure_model.return_value = model_path
    with (
        patch.dict(sys.modules, {"onnxruntime_genai": mock_og}),
        patch(
            "mempalace.nlp_providers.model_manager.ModelManager.get",
            return_value=mock_mm,
        ),
        patch.object(
            SLMProvider,
            "_find_genai_dir",
            return_value=model_path if model_path else "/fake/model",
        ),
        patch.object(
            SLMProvider,
            "_detect_model_type",
            return_value="phi3",
        ),
    ):
        p._loaded = False
        p._available = None
        p._ensure_loaded()
    return p


# ── Properties ───────────────────────────────────────────────────


class TestSLMProperties:
    def test_name(self):
        assert _fresh_provider().name == "slm"

    def test_capabilities(self):
        assert _fresh_provider().capabilities == {"sentiment", "triples", "coref"}

    def test_implements_nlp_provider(self):
        from mempalace.nlp_providers.base import NLPProvider

        assert isinstance(_fresh_provider(), NLPProvider)


# ── is_available ─────────────────────────────────────────────────


class TestSLMIsAvailable:
    def test_unavailable_when_feature_disabled(self, monkeypatch):
        monkeypatch.delenv("MEMPALACE_NLP_SLM", raising=False)
        assert _fresh_provider().is_available() is False

    def test_available_when_slm_enabled(self, monkeypatch):
        mock_og, _, _ = _make_mock_og()
        p = _setup_provider_with_mock(monkeypatch, mock_og)
        assert p.is_available() is True

    def test_unavailable_when_not_installed(self, monkeypatch):
        monkeypatch.setenv("MEMPALACE_NLP_SLM", "1")
        p = _fresh_provider()
        with patch.dict(sys.modules, {"onnxruntime_genai": None}):
            p._loaded = False
            p._available = None
            assert p.is_available() is False

    def test_unavailable_when_no_model_path(self, monkeypatch):
        monkeypatch.setenv("MEMPALACE_NLP_SLM", "1")
        mock_og, _, _ = _make_mock_og()
        p = _setup_provider_with_mock(monkeypatch, mock_og, model_path=None)
        assert p.is_available() is False


# ── analyze_sentiment ────────────────────────────────────────────


class TestSLMSentiment:
    def test_positive(self, monkeypatch):
        mock_og, _, _ = _make_mock_og("positive")
        p = _setup_provider_with_mock(monkeypatch, mock_og)
        assert p.analyze_sentiment("I love this!") == "positive"

    def test_negative(self, monkeypatch):
        mock_og, _, _ = _make_mock_og("This is terrible. negative")
        p = _setup_provider_with_mock(monkeypatch, mock_og)
        assert p.analyze_sentiment("I hate this") == "negative"

    def test_neutral_default(self, monkeypatch):
        mock_og, _, _ = _make_mock_og("unclear response")
        p = _setup_provider_with_mock(monkeypatch, mock_og)
        assert p.analyze_sentiment("test") == "neutral"

    def test_returns_neutral_when_unavailable(self):
        p = _fresh_provider()
        p._loaded = True
        p._available = False
        assert p.analyze_sentiment("test") == "neutral"


# ── extract_triples ──────────────────────────────────────────────


class TestSLMTriples:
    def test_extracts_triples(self, monkeypatch):
        json_output = '[{"subject": "Alice", "predicate": "uses", "object": "Python"}]'
        mock_og, _, _ = _make_mock_og(json_output)
        p = _setup_provider_with_mock(monkeypatch, mock_og)
        result = p.extract_triples("Alice uses Python.")
        assert len(result) == 1
        assert result[0]["subject"] == "Alice"
        assert result[0]["predicate"] == "uses"

    def test_returns_empty_on_invalid_json(self, monkeypatch):
        mock_og, _, _ = _make_mock_og("not json at all")
        p = _setup_provider_with_mock(monkeypatch, mock_og)
        assert p.extract_triples("test") == []

    def test_returns_empty_when_unavailable(self):
        p = _fresh_provider()
        p._loaded = True
        p._available = False
        assert p.extract_triples("test") == []


# ── resolve_coreferences ────────────────────────────────────────


class TestSLMCoreference:
    def test_resolves_pronouns(self, monkeypatch):
        json_output = '[{"pronoun": "She", "referent": "Alice"}]'
        mock_og, _, _ = _make_mock_og(json_output)
        p = _setup_provider_with_mock(monkeypatch, mock_og)
        result = p.resolve_coreferences("Alice went home. She was tired.")
        assert len(result) == 1
        assert result[0]["pronoun"] == "She"
        assert result[0]["referent"] == "Alice"

    def test_returns_empty_when_unavailable(self):
        p = _fresh_provider()
        p._loaded = True
        p._available = False
        assert p.resolve_coreferences("test") == []


# ── generate ─────────────────────────────────────────────────────


class TestSLMGenerate:
    def test_returns_empty_when_unavailable(self):
        p = _fresh_provider()
        p._loaded = True
        p._available = False
        assert p.generate("test") == ""

    def test_handles_generation_exception(self, monkeypatch):
        mock_og, mock_model, _ = _make_mock_og()
        p = _setup_provider_with_mock(monkeypatch, mock_og)
        # New API uses Generator class — make it raise
        mock_og.Generator.side_effect = RuntimeError("generation failed")
        assert p.generate("test") == ""


# ── JSON parsing ─────────────────────────────────────────────────


class TestSLMJsonParsing:
    def test_parses_valid_json(self):
        result = SLMProvider._parse_json_list('Some text [{"a": 1, "b": 2}] more text', ["a", "b"])
        assert len(result) == 1
        assert result[0] == {"a": 1, "b": 2}

    def test_filters_missing_keys(self):
        result = SLMProvider._parse_json_list('[{"a": 1}, {"a": 1, "b": 2}]', ["a", "b"])
        assert len(result) == 1

    def test_returns_empty_for_no_array(self):
        assert SLMProvider._parse_json_list("no json here", ["a"]) == []

    def test_returns_empty_for_invalid_json(self):
        assert SLMProvider._parse_json_list("[invalid", ["a"]) == []


# ── Unsupported ──────────────────────────────────────────────────


class TestSLMUnsupported:
    def test_extract_entities(self):
        assert _fresh_provider().extract_entities("test") == []

    def test_split_sentences(self):
        assert _fresh_provider().split_sentences("test") == []

    def test_classify_text(self):
        assert _fresh_provider().classify_text("test", ["a"]) is None
