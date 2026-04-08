"""
test_searcher.py — Tests for the programmatic search_memories API.

Tests the library-facing search interface (not the CLI print variant),
and the vocabulary map / query expansion machinery.
"""

import os
import textwrap

import pytest

from mempalace.searcher import expand_query, load_vocab_map, search_memories


# ---------------------------------------------------------------------------
# Vocabulary map helpers
# ---------------------------------------------------------------------------


SAMPLE_YAML = textwrap.dedent("""\
    # comment line
    concepts:
      - natural_language:
          - "what camera should I get"
          - "camera recommendation"
        corpus_terms:
          - "Sony A7R V"
          - "mirrorless"
          - "61MP"
      - natural_language:
          - "my medication tracker"
          - "health app"
        corpus_terms:
          - "MedicationLogger"
          - "HealthKit"
          - "intake.jsonl"
""")


@pytest.fixture
def vocab_file(tmp_path):
    """Write sample YAML to a temp palace directory and return the palace path."""
    palace = tmp_path / "palace"
    palace.mkdir()
    (palace / "vocabulary_map.yaml").write_text(SAMPLE_YAML, encoding="utf-8")
    return str(palace)


@pytest.fixture
def empty_palace(tmp_path):
    """Palace directory with no vocabulary_map.yaml."""
    palace = tmp_path / "palace"
    palace.mkdir()
    return str(palace)


class TestLoadVocabMap:
    def test_returns_empty_for_missing_file(self, empty_palace):
        result = load_vocab_map(empty_palace)
        assert result == {}

    def test_parses_concepts(self, vocab_file):
        result = load_vocab_map(vocab_file)
        assert "concepts" in result
        assert len(result["concepts"]) == 2

    def test_parses_natural_language(self, vocab_file):
        concepts = load_vocab_map(vocab_file)["concepts"]
        assert "what camera should I get" in concepts[0]["natural_language"]
        assert "camera recommendation" in concepts[0]["natural_language"]

    def test_parses_corpus_terms(self, vocab_file):
        concepts = load_vocab_map(vocab_file)["concepts"]
        assert "Sony A7R V" in concepts[0]["corpus_terms"]
        assert "mirrorless" in concepts[0]["corpus_terms"]
        assert "61MP" in concepts[0]["corpus_terms"]

    def test_parses_second_concept(self, vocab_file):
        concepts = load_vocab_map(vocab_file)["concepts"]
        assert "MedicationLogger" in concepts[1]["corpus_terms"]
        assert "HealthKit" in concepts[1]["corpus_terms"]

    def test_returns_empty_for_unreadable_file(self, tmp_path):
        palace = str(tmp_path / "palace")
        os.makedirs(palace)
        # Write a file but make it an empty map
        (tmp_path / "palace" / "vocabulary_map.yaml").write_text("", encoding="utf-8")
        result = load_vocab_map(palace)
        assert result == {}


class TestExpandQuery:
    def test_no_expansion_empty_map(self):
        query = "what camera should I get"
        assert expand_query(query, {}) == query

    def test_no_expansion_no_match(self, vocab_file):
        vocab_map = load_vocab_map(vocab_file)
        query = "tell me about databases"
        assert expand_query(query, vocab_map) == query

    def test_expands_on_phrase_match(self, vocab_file):
        vocab_map = load_vocab_map(vocab_file)
        query = "what camera should I get for travel"
        expanded = expand_query(query, vocab_map)
        assert "Sony A7R V" in expanded
        assert "mirrorless" in expanded
        assert "61MP" in expanded

    def test_expansion_preserves_original(self, vocab_file):
        vocab_map = load_vocab_map(vocab_file)
        query = "camera recommendation for street photography"
        expanded = expand_query(query, vocab_map)
        assert expanded.startswith(query)

    def test_case_insensitive_match(self, vocab_file):
        vocab_map = load_vocab_map(vocab_file)
        query = "CAMERA RECOMMENDATION"
        expanded = expand_query(query, vocab_map)
        assert "Sony A7R V" in expanded

    def test_no_duplicate_terms_on_double_match(self, vocab_file):
        # Both "what camera" and "camera recommendation" match — terms should appear once
        vocab_map = load_vocab_map(vocab_file)
        query = "what camera recommendation"
        expanded = expand_query(query, vocab_map)
        assert expanded.count("Sony A7R V") == 1

    def test_second_concept_match(self, vocab_file):
        vocab_map = load_vocab_map(vocab_file)
        query = "show me my medication tracker history"
        expanded = expand_query(query, vocab_map)
        assert "MedicationLogger" in expanded
        assert "HealthKit" in expanded

    def test_no_cross_contamination(self, vocab_file):
        vocab_map = load_vocab_map(vocab_file)
        # A camera query should not include medication terms
        query = "camera recommendation"
        expanded = expand_query(query, vocab_map)
        assert "MedicationLogger" not in expanded

    def test_both_concepts_match(self, vocab_file):
        vocab_map = load_vocab_map(vocab_file)
        query = "camera recommendation and health app"
        expanded = expand_query(query, vocab_map)
        assert "Sony A7R V" in expanded
        assert "MedicationLogger" in expanded


class TestSearchMemoriesWithVocab:
    def test_search_returns_expanded_query_key(self, palace_path, seeded_collection, vocab_file):
        """When a vocab map matches, search_memories includes expanded_query in result."""
        # Point the vocab-file palace at the seeded collection palace by writing a
        # vocabulary_map.yaml directly into it.
        vmap = SAMPLE_YAML
        import pathlib

        (pathlib.Path(palace_path) / "vocabulary_map.yaml").write_text(vmap, encoding="utf-8")
        result = search_memories("camera recommendation", palace_path)
        # The expanded query key should be present (camera concept matched)
        assert "expanded_query" in result
        assert "Sony A7R V" in result["expanded_query"]

    def test_search_without_vocab_no_expanded_key(self, palace_path, seeded_collection):
        """When no vocab map exists, search_memories has no expanded_query key."""
        result = search_memories("JWT authentication", palace_path)
        assert "expanded_query" not in result


class TestSearchMemories:
    def test_basic_search(self, palace_path, seeded_collection):
        result = search_memories("JWT authentication", palace_path)
        assert "results" in result
        assert len(result["results"]) > 0
        assert result["query"] == "JWT authentication"

    def test_wing_filter(self, palace_path, seeded_collection):
        result = search_memories("planning", palace_path, wing="notes")
        assert all(r["wing"] == "notes" for r in result["results"])

    def test_room_filter(self, palace_path, seeded_collection):
        result = search_memories("database", palace_path, room="backend")
        assert all(r["room"] == "backend" for r in result["results"])

    def test_wing_and_room_filter(self, palace_path, seeded_collection):
        result = search_memories("code", palace_path, wing="project", room="frontend")
        assert all(r["wing"] == "project" and r["room"] == "frontend" for r in result["results"])

    def test_n_results_limit(self, palace_path, seeded_collection):
        result = search_memories("code", palace_path, n_results=2)
        assert len(result["results"]) <= 2

    def test_no_palace_returns_error(self, tmp_path):
        result = search_memories("anything", str(tmp_path / "missing"))
        assert "error" in result

    def test_result_fields(self, palace_path, seeded_collection):
        result = search_memories("authentication", palace_path)
        hit = result["results"][0]
        assert "text" in hit
        assert "wing" in hit
        assert "room" in hit
        assert "source_file" in hit
        assert "similarity" in hit
        assert isinstance(hit["similarity"], float)
