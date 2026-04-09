"""Tests for GLiNERProvider -- gliner is fully mocked, no real install needed."""

import sys
import types
from unittest.mock import MagicMock, patch

from mempalace.nlp_providers.gliner_provider import GLiNERProvider, CONFIDENCE_THRESHOLD


# ── Helpers ──────────────────────────────────────────────────────


def _make_mock_gliner(entities=None, relations=None, classification=None):
    """Create a mock gliner module with mock GLiNER class."""
    mock_gliner = types.ModuleType("gliner")

    mock_model = MagicMock()
    mock_model.predict_entities.return_value = entities or [
        {"text": "Alice", "label": "person", "start": 0, "end": 5, "score": 0.95},
        {"text": "Anthropic", "label": "organization", "start": 15, "end": 24, "score": 0.88},
    ]

    if relations is not None:
        mock_model.predict_relations.return_value = relations
    else:
        mock_model.predict_relations.return_value = [
            {
                "subject": "Alice",
                "predicate": "works_at",
                "object": "Anthropic",
                "score": 0.82,
            }
        ]

    if classification is not None:
        mock_model.predict_classification.return_value = classification
    else:
        mock_model.predict_classification.return_value = {
            "label": "decision",
            "score": 0.75,
        }

    mock_gliner_cls = MagicMock()
    mock_gliner_cls.from_pretrained.return_value = mock_model
    mock_gliner.GLiNER = mock_gliner_cls

    return mock_gliner, mock_model


def _fresh_provider():
    """Get a fresh GLiNERProvider."""
    return GLiNERProvider()


def _setup_provider_with_mock(monkeypatch, mock_gliner):
    """Set up a provider with mocked gliner and ModelManager."""
    monkeypatch.setenv("MEMPALACE_NLP_TRIPLES", "1")
    p = _fresh_provider()

    mock_mm = MagicMock()
    mock_mm.ensure_model.return_value = None  # triggers fallback load
    mock_mm_cls = MagicMock()
    mock_mm_cls.get.return_value = mock_mm
    mock_mm_module = types.ModuleType("mempalace.nlp_providers.model_manager")
    mock_mm_module.ModelManager = mock_mm_cls

    with patch.dict(
        sys.modules,
        {
            "gliner": mock_gliner,
            "mempalace.nlp_providers.model_manager": mock_mm_module,
        },
    ):
        p._loaded = False
        p._available = None
        p._ensure_loaded()
    return p


# ── Properties ───────────────────────────────────────────────────


class TestGLiNERProviderProperties:
    def test_name(self):
        p = _fresh_provider()
        assert p.name == "gliner"

    def test_capabilities(self):
        p = _fresh_provider()
        assert p.capabilities == {"ner", "triples", "classify"}

    def test_implements_nlp_provider(self):
        from mempalace.nlp_providers.base import NLPProvider

        p = _fresh_provider()
        assert isinstance(p, NLPProvider)


# ── is_available ─────────────────────────────────────────────────


class TestGLiNERIsAvailable:
    def test_unavailable_when_feature_disabled(self, monkeypatch):
        monkeypatch.delenv("MEMPALACE_NLP_TRIPLES", raising=False)
        monkeypatch.delenv("MEMPALACE_NLP_CLASSIFY", raising=False)
        monkeypatch.delenv("MEMPALACE_NLP_NER", raising=False)
        monkeypatch.delenv("MEMPALACE_NLP_BACKEND", raising=False)
        p = _fresh_provider()
        assert p.is_available() is False

    def test_available_when_triples_enabled(self, monkeypatch):
        mock_gliner, _ = _make_mock_gliner()
        p = _setup_provider_with_mock(monkeypatch, mock_gliner)
        assert p.is_available() is True

    def test_unavailable_when_gliner_not_installed(self, monkeypatch):
        monkeypatch.setenv("MEMPALACE_NLP_TRIPLES", "1")
        p = _fresh_provider()
        with patch.dict(sys.modules, {"gliner": None}):
            p._loaded = False
            p._available = None
            assert p.is_available() is False

    def test_available_with_backend_gliner(self, monkeypatch):
        monkeypatch.delenv("MEMPALACE_NLP_TRIPLES", raising=False)
        monkeypatch.setenv("MEMPALACE_NLP_BACKEND", "gliner")
        mock_gliner, _ = _make_mock_gliner()
        p = _fresh_provider()
        mock_mm = MagicMock()
        mock_mm.ensure_model.return_value = None
        with (
            patch.dict(sys.modules, {"gliner": mock_gliner}),
            patch(
                "mempalace.nlp_providers.model_manager.ModelManager.get",
                return_value=mock_mm,
            ),
        ):
            p._loaded = False
            p._available = None
            assert p.is_available() is True

    def test_available_with_classify_env(self, monkeypatch):
        monkeypatch.delenv("MEMPALACE_NLP_TRIPLES", raising=False)
        monkeypatch.setenv("MEMPALACE_NLP_CLASSIFY", "1")
        mock_gliner, _ = _make_mock_gliner()
        p = _setup_provider_with_mock(monkeypatch, mock_gliner)
        # Re-set env since _setup uses TRIPLES
        monkeypatch.setenv("MEMPALACE_NLP_CLASSIFY", "1")
        assert p.is_available() is True


# ── extract_entities ─────────────────────────────────────────────


class TestGLiNERExtractEntities:
    def test_extracts_entities(self, monkeypatch):
        mock_gliner, _ = _make_mock_gliner()
        p = _setup_provider_with_mock(monkeypatch, mock_gliner)
        result = p.extract_entities("Alice works at Anthropic.")
        assert len(result) == 2
        assert result[0]["text"] == "Alice"
        assert result[0]["label"] == "person"
        assert result[1]["text"] == "Anthropic"

    def test_filters_low_confidence(self, monkeypatch):
        mock_gliner, mock_model = _make_mock_gliner(
            entities=[
                {"text": "Alice", "label": "person", "start": 0, "end": 5, "score": 0.95},
                {"text": "maybe", "label": "person", "start": 10, "end": 15, "score": 0.2},
            ]
        )
        p = _setup_provider_with_mock(monkeypatch, mock_gliner)
        result = p.extract_entities("Alice maybe something")
        assert len(result) == 1
        assert result[0]["text"] == "Alice"

    def test_returns_empty_when_not_loaded(self):
        p = _fresh_provider()
        p._loaded = True
        p._available = False
        assert p.extract_entities("test") == []


# ── extract_triples ──────────────────────────────────────────────


class TestGLiNERExtractTriples:
    def test_extracts_triples(self, monkeypatch):
        mock_gliner, _ = _make_mock_gliner()
        p = _setup_provider_with_mock(monkeypatch, mock_gliner)
        result = p.extract_triples("Alice works at Anthropic.")
        assert len(result) == 1
        assert result[0]["subject"] == "Alice"
        assert result[0]["predicate"] == "works_at"
        assert result[0]["object"] == "Anthropic"
        assert result[0]["confidence"] >= CONFIDENCE_THRESHOLD

    def test_filters_low_confidence_triples(self, monkeypatch):
        mock_gliner, _ = _make_mock_gliner(
            relations=[
                {"subject": "A", "predicate": "r", "object": "B", "score": 0.9},
                {"subject": "C", "predicate": "r", "object": "D", "score": 0.1},
            ]
        )
        p = _setup_provider_with_mock(monkeypatch, mock_gliner)
        result = p.extract_triples("test")
        assert len(result) == 1

    def test_returns_empty_when_no_entities(self, monkeypatch):
        mock_gliner, mock_model = _make_mock_gliner(entities=[])
        p = _setup_provider_with_mock(monkeypatch, mock_gliner)
        # Ensure model returns no entities for this call
        p._model.predict_entities.return_value = []
        result = p.extract_triples("empty text")
        assert result == []

    def test_returns_empty_when_not_loaded(self):
        p = _fresh_provider()
        p._loaded = True
        p._available = False
        assert p.extract_triples("test") == []


# ── classify_text ────────────────────────────────────────────────


class TestGLiNERClassifyText:
    def test_classifies_text(self, monkeypatch):
        mock_gliner, _ = _make_mock_gliner()
        p = _setup_provider_with_mock(monkeypatch, mock_gliner)
        result = p.classify_text("I decided to use Python.", ["decision", "preference"])
        assert result is not None
        assert result["label"] == "decision"
        assert result["confidence"] >= CONFIDENCE_THRESHOLD

    def test_returns_none_when_low_confidence(self, monkeypatch):
        mock_gliner, _ = _make_mock_gliner(classification={"label": "decision", "score": 0.1})
        p = _setup_provider_with_mock(monkeypatch, mock_gliner)
        # Also mock predict_entities to return low confidence
        p._model.predict_entities.return_value = [{"label": "x", "score": 0.1}]
        result = p.classify_text("unclear", ["decision"])
        assert result is None

    def test_returns_none_when_not_loaded(self):
        p = _fresh_provider()
        p._loaded = True
        p._available = False
        assert p.classify_text("test", ["a"]) is None


# ── Lazy loading ─────────────────────────────────────────────────


class TestGLiNERLazyLoading:
    def test_loads_only_once(self, monkeypatch):
        mock_gliner, _ = _make_mock_gliner()
        monkeypatch.setenv("MEMPALACE_NLP_TRIPLES", "1")
        p = _fresh_provider()
        mock_mm = MagicMock()
        mock_mm.ensure_model.return_value = None
        with (
            patch.dict(sys.modules, {"gliner": mock_gliner}),
            patch(
                "mempalace.nlp_providers.model_manager.ModelManager.get",
                return_value=mock_mm,
            ),
        ):
            p._ensure_loaded()
            p._ensure_loaded()
            p._ensure_loaded()
        assert mock_gliner.GLiNER.from_pretrained.call_count == 1


# ── Error handling / edge cases ──────────────────────────────────


class TestGLiNERErrorHandling:
    def test_model_path_loads_from_model_manager(self, monkeypatch):
        """When ModelManager returns a path, load from that path."""
        mock_gliner, _ = _make_mock_gliner()
        monkeypatch.setenv("MEMPALACE_NLP_TRIPLES", "1")
        p = _fresh_provider()
        mock_mm = MagicMock()
        mock_mm.ensure_model.return_value = "/fake/model/path"
        mock_mm_cls = MagicMock(return_value=mock_mm)
        mock_mm_cls.get.return_value = mock_mm
        # Create a mock model_manager module so 'from .model_manager import ModelManager'
        # returns our mock class
        mock_mm_module = types.ModuleType("mempalace.nlp_providers.model_manager")
        mock_mm_module.ModelManager = mock_mm_cls
        with (
            patch.dict(
                sys.modules,
                {
                    "gliner": mock_gliner,
                    "mempalace.nlp_providers.model_manager": mock_mm_module,
                },
            ),
        ):
            p._ensure_loaded()
        assert p._available is True
        mock_gliner.GLiNER.from_pretrained.assert_called_once_with(
            "/fake/model/path", load_onnx_model=True
        )

    def test_fallback_load_exception(self, monkeypatch):
        """When fallback from_pretrained raises, provider is unavailable."""
        mock_gliner = types.ModuleType("gliner")
        mock_cls = MagicMock()
        mock_cls.from_pretrained.side_effect = RuntimeError("no model")
        mock_gliner.GLiNER = mock_cls
        monkeypatch.setenv("MEMPALACE_NLP_TRIPLES", "1")
        p = _fresh_provider()
        mock_mm = MagicMock()
        mock_mm.ensure_model.return_value = None
        mock_mm_cls = MagicMock()
        mock_mm_cls.get.return_value = mock_mm
        mock_mm_module = types.ModuleType("mempalace.nlp_providers.model_manager")
        mock_mm_module.ModelManager = mock_mm_cls
        with patch.dict(
            sys.modules,
            {
                "gliner": mock_gliner,
                "mempalace.nlp_providers.model_manager": mock_mm_module,
            },
        ):
            p._ensure_loaded()
        assert p._available is False

    def test_general_init_exception(self, monkeypatch):
        """General exception during ModelManager.get raises marks unavailable."""
        monkeypatch.setenv("MEMPALACE_NLP_TRIPLES", "1")
        mock_gliner = types.ModuleType("gliner")
        mock_gliner.GLiNER = MagicMock()
        p = _fresh_provider()
        mock_mm_cls = MagicMock()
        mock_mm_cls.get.side_effect = RuntimeError("boom")
        mock_mm_module = types.ModuleType("mempalace.nlp_providers.model_manager")
        mock_mm_module.ModelManager = mock_mm_cls
        with patch.dict(
            sys.modules,
            {
                "gliner": mock_gliner,
                "mempalace.nlp_providers.model_manager": mock_mm_module,
            },
        ):
            p._loaded = False
            p._ensure_loaded()
        assert p._available is False

    def test_extract_entities_exception(self, monkeypatch):
        """NER exception returns empty list."""
        mock_gliner, mock_model = _make_mock_gliner()
        p = _setup_provider_with_mock(monkeypatch, mock_gliner)
        p._model.predict_entities.side_effect = RuntimeError("NER error")
        assert p.extract_entities("test") == []

    def test_extract_triples_exception(self, monkeypatch):
        """Triple extraction exception returns empty list."""
        mock_gliner, mock_model = _make_mock_gliner()
        p = _setup_provider_with_mock(monkeypatch, mock_gliner)
        p._model.predict_entities.side_effect = RuntimeError("error")
        assert p.extract_triples("test") == []

    def test_classify_text_exception(self, monkeypatch):
        """Classification exception returns None."""
        mock_gliner, mock_model = _make_mock_gliner()
        p = _setup_provider_with_mock(monkeypatch, mock_gliner)
        p._model.predict_classification.side_effect = RuntimeError("err")
        p._model.predict_entities.side_effect = RuntimeError("err")
        assert p.classify_text("test", ["a"]) is None

    def test_classify_without_predict_classification(self, monkeypatch):
        """Falls back to entity prediction when predict_classification missing."""
        mock_gliner, mock_model = _make_mock_gliner()
        p = _setup_provider_with_mock(monkeypatch, mock_gliner)
        del p._model.predict_classification
        p._model.predict_entities.return_value = [{"label": "preference", "score": 0.8}]
        result = p.classify_text("I like Python", [])
        assert result is not None
        assert result["label"] == "preference"

    def test_no_relations_method(self, monkeypatch):
        """Returns empty when model has no predict_relations."""
        mock_gliner, mock_model = _make_mock_gliner()
        p = _setup_provider_with_mock(monkeypatch, mock_gliner)
        del p._model.predict_relations
        result = p.extract_triples("test")
        assert result == []


# ── Unsupported methods ──────────────────────────────────────────


class TestGLiNERUnsupported:
    def test_split_sentences_returns_empty(self):
        p = _fresh_provider()
        assert p.split_sentences("test") == []

    def test_resolve_coreferences_returns_empty(self):
        p = _fresh_provider()
        assert p.resolve_coreferences("test") == []

    def test_analyze_sentiment_returns_neutral(self):
        p = _fresh_provider()
        assert p.analyze_sentiment("test") == "neutral"
