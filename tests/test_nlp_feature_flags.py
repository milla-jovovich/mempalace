"""
Tests that NLP feature flags correctly gate provider usage in wired modules.

Each test:
1. Sets the relevant MEMPALACE_NLP_* env var
2. Mocks the registry to return a fake provider
3. Calls the production function
4. Asserts the NLP path was taken (or not, when disabled)
"""

import os
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_registry(**capabilities):
    """Create a mock registry that returns mock results for given capabilities."""
    registry = MagicMock()

    if "sentences" in capabilities:
        registry.split_sentences.return_value = capabilities["sentences"]
    else:
        registry.split_sentences.return_value = []

    if "ner" in capabilities:
        registry.extract_entities.return_value = capabilities["ner"]
    else:
        registry.extract_entities.return_value = []

    if "classify" in capabilities:
        registry.classify_text.return_value = capabilities["classify"]
    else:
        registry.classify_text.return_value = None

    if "triples" in capabilities:
        registry.extract_triples.return_value = capabilities["triples"]
    else:
        registry.extract_triples.return_value = []

    return registry


def _make_mock_config(*enabled_caps):
    """Create a mock NLPConfig that reports given capabilities as enabled."""
    config = MagicMock()
    config.has.side_effect = lambda cap: cap in enabled_caps
    return config


# ---------------------------------------------------------------------------
# dialect.py — sentence splitting with NLP
# ---------------------------------------------------------------------------


class TestDialectNLPFlags:
    """Test NLP feature flag wiring in dialect.py."""

    def test_sentences_flag_enabled_uses_nlp(self):
        """When MEMPALACE_NLP_SENTENCES=1, dialect uses NLP sentence splitter."""
        from mempalace.dialect import Dialect

        mock_config = _make_mock_config("sentences")
        mock_registry = _make_mock_registry(sentences=["Hello.", "World."])

        with (
            patch.dict(os.environ, {"MEMPALACE_NLP_SENTENCES": "1"}),
            patch("mempalace.nlp_config.NLPConfig.resolve", return_value=mock_config),
            patch("mempalace.nlp_providers.registry.get_registry", return_value=mock_registry),
        ):
            d = Dialect()
            result = d._split_sentences("Hello. World.")

        assert result == ["Hello.", "World."]
        mock_registry.split_sentences.assert_called_once()

    def test_sentences_flag_disabled_uses_regex(self):
        """When no NLP flag set, dialect uses regex sentence splitting."""
        from mempalace.dialect import Dialect

        mock_config = _make_mock_config()  # no caps enabled
        mock_registry = _make_mock_registry()

        with (
            patch.dict(os.environ, {}, clear=False),
            patch("mempalace.nlp_config.NLPConfig.resolve", return_value=mock_config),
            patch("mempalace.nlp_providers.registry.get_registry", return_value=mock_registry),
        ):
            d = Dialect()
            result = d._split_sentences("Hello. World.")

        # Should have fallen back to regex
        mock_registry.split_sentences.assert_not_called()
        assert len(result) >= 2

    def test_sentences_nlp_exception_falls_back(self):
        """If NLP provider raises, dialect falls back to regex."""
        from mempalace.dialect import Dialect

        with patch("mempalace.nlp_config.NLPConfig.resolve", side_effect=RuntimeError("boom")):
            d = Dialect()
            result = d._split_sentences("Hello. World.")

        assert len(result) >= 2  # regex fallback worked


# ---------------------------------------------------------------------------
# entity_detector.py — NER with NLP
# ---------------------------------------------------------------------------


class TestEntityDetectorNLPFlags:
    """Test NLP feature flag wiring in entity_detector.py."""

    def test_ner_flag_enabled_uses_nlp(self):
        """When MEMPALACE_NLP_NER=1, entity_detector uses NLP NER."""
        from mempalace.entity_detector import extract_candidates

        mock_config = _make_mock_config("ner")
        mock_registry = _make_mock_registry(ner=[{"text": "Python", "label": "TECH"}])

        with (
            patch.dict(os.environ, {"MEMPALACE_NLP_NER": "1"}),
            patch("mempalace.nlp_config.NLPConfig.resolve", return_value=mock_config),
            patch("mempalace.nlp_providers.registry.get_registry", return_value=mock_registry),
        ):
            counts = extract_candidates("Python is great for data science.")

        mock_registry.extract_entities.assert_called_once()
        # NLP entities get count boost of 3
        assert "Python" in counts

    def test_ner_flag_disabled_uses_regex(self):
        """When no NLP flag set, entity_detector uses regex only."""
        from mempalace.entity_detector import extract_candidates

        mock_config = _make_mock_config()
        mock_registry = _make_mock_registry()

        with (
            patch.dict(os.environ, {}, clear=False),
            patch("mempalace.nlp_config.NLPConfig.resolve", return_value=mock_config),
            patch("mempalace.nlp_providers.registry.get_registry", return_value=mock_registry),
        ):
            extract_candidates("Python is great.")

        mock_registry.extract_entities.assert_not_called()

    def test_ner_nlp_exception_falls_back(self):
        """If NLP provider raises, entity_detector falls back to regex."""
        from mempalace.entity_detector import extract_candidates

        with patch("mempalace.nlp_config.NLPConfig.resolve", side_effect=RuntimeError("boom")):
            # Should not raise
            counts = extract_candidates("Python is great.")

        assert isinstance(counts, dict)


# ---------------------------------------------------------------------------
# general_extractor.py — classification with NLP
# ---------------------------------------------------------------------------


class TestGeneralExtractorNLPFlags:
    """Test NLP feature flag wiring in general_extractor.py."""

    def test_classify_flag_enabled_uses_nlp(self):
        """When MEMPALACE_NLP_CLASSIFY=1, extractor uses NLP classification."""
        from mempalace.general_extractor import extract_memories

        mock_config = _make_mock_config("classify")
        mock_registry = _make_mock_registry(classify={"label": "decision", "confidence": 0.9})

        text = "We decided to go with PostgreSQL because it handles JSON well and has great tooling support for our use case."

        with (
            patch.dict(os.environ, {"MEMPALACE_NLP_CLASSIFY": "1"}),
            patch("mempalace.nlp_config.NLPConfig.resolve", return_value=mock_config),
            patch("mempalace.nlp_providers.registry.get_registry", return_value=mock_registry),
        ):
            memories = extract_memories(text)

        mock_registry.classify_text.assert_called()
        assert len(memories) > 0
        assert memories[0]["memory_type"] == "decision"

    def test_classify_flag_disabled_uses_regex(self):
        """When no NLP flag set, extractor uses regex markers."""
        from mempalace.general_extractor import extract_memories

        mock_config = _make_mock_config()
        mock_registry = _make_mock_registry()

        text = "We decided to go with PostgreSQL because it handles JSON well and has great tooling support for our use case."

        with (
            patch.dict(os.environ, {}, clear=False),
            patch("mempalace.nlp_config.NLPConfig.resolve", return_value=mock_config),
            patch("mempalace.nlp_providers.registry.get_registry", return_value=mock_registry),
        ):
            memories = extract_memories(text)

        mock_registry.classify_text.assert_not_called()
        # Regex should still pick up "decided" + "because" as decision markers
        assert len(memories) > 0

    def test_classify_low_confidence_falls_back_to_regex(self):
        """NLP classification with low confidence falls back to regex."""
        from mempalace.general_extractor import extract_memories

        mock_config = _make_mock_config("classify")
        mock_registry = _make_mock_registry(
            classify={"label": "emotional", "confidence": 0.2}  # below 0.5 threshold
        )

        text = "We decided to go with PostgreSQL because it handles JSON well and has great tooling support for our use case."

        with (
            patch.dict(os.environ, {"MEMPALACE_NLP_CLASSIFY": "1"}),
            patch("mempalace.nlp_config.NLPConfig.resolve", return_value=mock_config),
            patch("mempalace.nlp_providers.registry.get_registry", return_value=mock_registry),
        ):
            memories = extract_memories(text)

        # Should fall back to regex and still find decision markers
        assert len(memories) > 0

    def test_classify_nlp_exception_falls_back(self):
        """If NLP provider raises, extractor falls back to regex."""
        from mempalace.general_extractor import extract_memories

        with patch("mempalace.nlp_config.NLPConfig.resolve", side_effect=RuntimeError("boom")):
            text = "We decided to go with PostgreSQL because of its JSON support."
            memories = extract_memories(text)

        assert len(memories) > 0  # regex fallback worked


# ---------------------------------------------------------------------------
# miner.py — triple extraction with NLP
# ---------------------------------------------------------------------------


class TestMinerNLPFlags:
    """Test NLP feature flag wiring in miner.py."""

    def test_triples_flag_enabled_extracts(self):
        """When MEMPALACE_NLP_TRIPLES=1, miner extracts KG triples."""
        from mempalace.miner import _extract_triples_if_enabled

        mock_config = _make_mock_config("triples")
        mock_registry = _make_mock_registry(
            triples=[
                {"subject": "Python", "predicate": "is", "object": "language", "confidence": 0.9}
            ]
        )
        mock_kg = MagicMock()

        with (
            patch.dict(os.environ, {"MEMPALACE_NLP_TRIPLES": "1"}),
            patch("mempalace.nlp_config.NLPConfig.resolve", return_value=mock_config),
            patch("mempalace.nlp_providers.registry.get_registry", return_value=mock_registry),
            patch("mempalace.knowledge_graph.KnowledgeGraph", return_value=mock_kg),
        ):
            _extract_triples_if_enabled("Python is a language", "test.py", palace_path="/tmp/test")

        mock_registry.extract_triples.assert_called_once()
        mock_kg.add_triple.assert_called_once()

    def test_triples_flag_disabled_skips(self):
        """When no NLP flag set, miner skips triple extraction."""
        from mempalace.miner import _extract_triples_if_enabled

        mock_config = _make_mock_config()
        mock_registry = _make_mock_registry()

        with (
            patch.dict(os.environ, {}, clear=False),
            patch("mempalace.nlp_config.NLPConfig.resolve", return_value=mock_config),
            patch("mempalace.nlp_providers.registry.get_registry", return_value=mock_registry),
        ):
            _extract_triples_if_enabled("Python is a language", "test.py")

        mock_registry.extract_triples.assert_not_called()

    def test_triples_nlp_exception_silent(self):
        """If NLP provider raises, miner silently continues."""
        from mempalace.miner import _extract_triples_if_enabled

        with patch("mempalace.nlp_config.NLPConfig.resolve", side_effect=RuntimeError("boom")):
            # Should not raise
            _extract_triples_if_enabled("Python is a language", "test.py")

    def test_triples_empty_result_skips_kg(self):
        """When NLP returns empty triples, KG is not touched."""
        from mempalace.miner import _extract_triples_if_enabled

        mock_config = _make_mock_config("triples")
        mock_registry = _make_mock_registry(triples=[])

        with (
            patch.dict(os.environ, {"MEMPALACE_NLP_TRIPLES": "1"}),
            patch("mempalace.nlp_config.NLPConfig.resolve", return_value=mock_config),
            patch("mempalace.nlp_providers.registry.get_registry", return_value=mock_registry),
            patch("mempalace.knowledge_graph.KnowledgeGraph") as MockKG,
        ):
            _extract_triples_if_enabled("Hello world", "test.py")

        MockKG.assert_not_called()
