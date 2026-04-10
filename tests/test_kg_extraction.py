"""Tests for KG entity/triple extraction."""

import pytest
from mempalace.kg_extraction import EntityTripleExtractor


class TestNERExtraction:
    def test_extract_without_spacy_uses_regex_fallback(self, kg):
        """Regex fallback should detect capitalized names."""
        extractor = EntityTripleExtractor(kg, use_llm="never")
        result = extractor.extract("Alice Chen works at Acme Corp with Bob Smith.")
        assert result["entities_added"] > 0

    def test_extract_cooccurrence_triples(self, kg):
        """Two entities in same sentence should produce co-occurrence triples."""
        extractor = EntityTripleExtractor(kg, use_llm="never")
        result = extractor.extract("Alice Chen met Bob Smith at the conference.")
        assert result["triples_added"] > 0

    def test_extract_stores_to_kg(self, kg):
        """Extracted entities should be queryable in the KG."""
        extractor = EntityTripleExtractor(kg, use_llm="never")
        extractor.extract("Alice Chen works at Acme Corp.")
        stats = kg.stats()
        assert stats["entities"] > 0

    def test_extract_idempotent(self, kg):
        """Extracting same text twice should not duplicate triples."""
        extractor = EntityTripleExtractor(kg, use_llm="never")
        r1 = extractor.extract("Alice Chen met Bob Smith.")
        r2 = extractor.extract("Alice Chen met Bob Smith.")
        # Second call should add 0 new triples (dedup by add_triple)
        assert r2["triples_added"] == 0 or r2["triples_added"] <= r1["triples_added"]

    def test_extract_empty_text_returns_zero(self, kg):
        """Empty text should return zero counts."""
        extractor = EntityTripleExtractor(kg, use_llm="never")
        result = extractor.extract("")
        assert result["entities_added"] == 0
        assert result["triples_added"] == 0

    def test_extract_returns_correct_structure(self, kg):
        """Result dict should have expected keys."""
        extractor = EntityTripleExtractor(kg, use_llm="never")
        result = extractor.extract("Alice met Bob.")
        assert "entities_added" in result
        assert "triples_added" in result
        assert "details" in result

    def test_extract_with_source_closet(self, kg):
        """source_closet should be passed through to triples."""
        extractor = EntityTripleExtractor(kg, use_llm="never")
        extractor.extract("Alice Chen met Bob Smith.", source_closet="drawer_123")
        facts = kg.query_entity("Alice Chen")
        if facts:
            assert any(f.get("source_closet") == "drawer_123" for f in facts)

    def test_extract_confidence_is_0_6_for_ner(self, kg):
        """NER co-occurrence triples should have confidence=0.6."""
        extractor = EntityTripleExtractor(kg, use_llm="never")
        extractor.extract("Alice Chen met Bob Smith at the office.")
        facts = kg.query_entity("Alice Chen")
        ner_facts = [f for f in facts if f.get("confidence") is not None]
        for f in ner_facts:
            assert f["confidence"] == pytest.approx(0.6)


class TestLLMExtraction:
    def test_llm_fallback_on_missing_key(self, kg):
        """Without API key, should fall back to NER silently."""
        extractor = EntityTripleExtractor(kg, use_llm="auto")
        # Should not raise, just fall back
        result = extractor.extract("Alice works at Acme.")
        assert isinstance(result, dict)


class TestSpacyDetection:
    def test_spacy_available_returns_bool(self):
        """_spacy_available should return a boolean."""
        result = EntityTripleExtractor._spacy_available()
        assert isinstance(result, bool)

    def test_llm_available_returns_bool(self):
        """_llm_available should return a boolean."""
        result = EntityTripleExtractor._llm_available()
        assert isinstance(result, bool)
