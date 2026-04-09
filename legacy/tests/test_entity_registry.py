"""Tests for mempalace.entity_registry."""

from unittest.mock import patch

from mempalace.entity_registry import (
    COMMON_ENGLISH_WORDS,
    PERSON_CONTEXT_PATTERNS,
    EntityRegistry,
)


# ── COMMON_ENGLISH_WORDS ────────────────────────────────────────────────


def test_common_english_words_has_expected_entries():
    assert "ever" in COMMON_ENGLISH_WORDS
    assert "grace" in COMMON_ENGLISH_WORDS
    assert "will" in COMMON_ENGLISH_WORDS
    assert "may" in COMMON_ENGLISH_WORDS
    assert "monday" in COMMON_ENGLISH_WORDS


def test_common_english_words_is_lowercase():
    for word in COMMON_ENGLISH_WORDS:
        assert word == word.lower(), f"{word} should be lowercase"


# ── PERSON_CONTEXT_PATTERNS ─────────────────────────────────────────────


def test_person_context_patterns_is_nonempty():
    assert len(PERSON_CONTEXT_PATTERNS) > 0


# ── EntityRegistry creation and empty state ─────────────────────────────


def test_load_from_nonexistent_dir(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    assert registry.people == {}
    assert registry.projects == []
    assert registry.mode == "personal"
    assert registry.ambiguous_flags == []


def test_save_and_load_roundtrip(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(
        mode="work",
        people=[{"name": "Alice", "relationship": "colleague", "context": "work"}],
        projects=["MemPalace"],
    )
    # Load again from same dir
    loaded = EntityRegistry.load(config_dir=tmp_path)
    assert loaded.mode == "work"
    assert "Alice" in loaded.people
    assert "MemPalace" in loaded.projects


def test_save_creates_file(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.save()
    assert (tmp_path / "entity_registry.json").exists()


# ── seed ────────────────────────────────────────────────────────────────


def test_seed_registers_people(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(
        mode="personal",
        people=[
            {"name": "Riley", "relationship": "daughter", "context": "personal"},
            {"name": "Devon", "relationship": "friend", "context": "personal"},
        ],
        projects=["MemPalace"],
    )
    assert "Riley" in registry.people
    assert "Devon" in registry.people
    assert registry.people["Riley"]["relationship"] == "daughter"
    assert registry.people["Riley"]["source"] == "onboarding"
    assert registry.people["Riley"]["confidence"] == 1.0


def test_seed_registers_projects(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(mode="work", people=[], projects=["Acme", "Widget"])
    assert registry.projects == ["Acme", "Widget"]


def test_seed_sets_mode(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(mode="combo", people=[], projects=[])
    assert registry.mode == "combo"


def test_seed_flags_ambiguous_names(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(
        mode="personal",
        people=[
            {"name": "Grace", "relationship": "friend", "context": "personal"},
            {"name": "Riley", "relationship": "daughter", "context": "personal"},
        ],
        projects=[],
    )
    assert "grace" in registry.ambiguous_flags
    # Riley is not a common English word
    assert "riley" not in registry.ambiguous_flags


def test_seed_with_aliases(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(
        mode="personal",
        people=[{"name": "Maxwell", "relationship": "friend", "context": "personal"}],
        projects=[],
        aliases={"Max": "Maxwell"},
    )
    assert "Maxwell" in registry.people
    assert "Max" in registry.people
    assert registry.people["Max"].get("canonical") == "Maxwell"


def test_seed_skips_empty_names(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(
        mode="personal",
        people=[{"name": "", "relationship": "", "context": "personal"}],
        projects=[],
    )
    assert len(registry.people) == 0


# ── lookup ──────────────────────────────────────────────────────────────


def test_lookup_known_person(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(
        mode="personal",
        people=[{"name": "Riley", "relationship": "daughter", "context": "personal"}],
        projects=[],
    )
    result = registry.lookup("Riley")
    assert result["type"] == "person"
    assert result["confidence"] == 1.0
    assert result["name"] == "Riley"


def test_lookup_known_project(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(mode="work", people=[], projects=["MemPalace"])
    result = registry.lookup("MemPalace")
    assert result["type"] == "project"
    assert result["confidence"] == 1.0


def test_lookup_unknown_word(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(mode="personal", people=[], projects=[])
    result = registry.lookup("Xyzzy")
    assert result["type"] == "unknown"
    assert result["confidence"] == 0.0


def test_lookup_case_insensitive(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(
        mode="personal",
        people=[{"name": "Riley", "relationship": "daughter", "context": "personal"}],
        projects=[],
    )
    result = registry.lookup("riley")
    assert result["type"] == "person"


def test_lookup_alias(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(
        mode="personal",
        people=[{"name": "Maxwell", "relationship": "friend", "context": "personal"}],
        projects=[],
        aliases={"Max": "Maxwell"},
    )
    result = registry.lookup("Max")
    assert result["type"] == "person"


# ── disambiguation ──────────────────────────────────────────────────────


def test_lookup_ambiguous_word_as_person(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(
        mode="personal",
        people=[{"name": "Grace", "relationship": "friend", "context": "personal"}],
        projects=[],
    )
    result = registry.lookup("Grace", context="I went with Grace today")
    assert result["type"] == "person"


def test_lookup_ambiguous_word_as_concept(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(
        mode="personal",
        people=[{"name": "Ever", "relationship": "friend", "context": "personal"}],
        projects=[],
    )
    result = registry.lookup("Ever", context="have you ever tried this")
    assert result["type"] == "concept"


# ── research (Wikipedia) — mocked ──────────────────────────────────────


def test_research_caches_result(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(mode="personal", people=[], projects=[])

    mock_result = {
        "inferred_type": "person",
        "confidence": 0.80,
        "wiki_summary": "Saoirse is an Irish given name.",
        "wiki_title": "Saoirse",
    }

    with patch("mempalace.entity_registry._wikipedia_lookup", return_value=mock_result):
        result = registry.research("Saoirse", auto_confirm=True)
    assert result["inferred_type"] == "person"

    # Second call should use cache, not call Wikipedia again
    with patch(
        "mempalace.entity_registry._wikipedia_lookup",
        side_effect=AssertionError("should not be called"),
    ):
        cached = registry.research("Saoirse")
    assert cached["inferred_type"] == "person"


def test_confirm_research_adds_to_people(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(mode="personal", people=[], projects=[])

    mock_result = {
        "inferred_type": "person",
        "confidence": 0.80,
        "wiki_summary": "Saoirse is a name",
        "wiki_title": "Saoirse",
    }
    with patch("mempalace.entity_registry._wikipedia_lookup", return_value=mock_result):
        registry.research("Saoirse", auto_confirm=False)

    registry.confirm_research("Saoirse", entity_type="person", relationship="friend")
    assert "Saoirse" in registry.people
    assert registry.people["Saoirse"]["source"] == "wiki"


# ── extract_people_from_query ───────────────────────────────────────────


def test_extract_people_from_query(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(
        mode="personal",
        people=[
            {"name": "Riley", "relationship": "daughter", "context": "personal"},
            {"name": "Devon", "relationship": "friend", "context": "personal"},
        ],
        projects=[],
    )
    found = registry.extract_people_from_query("What did Riley say about the weather?")
    assert "Riley" in found
    assert "Devon" not in found


# ── extract_unknown_candidates ──────────────────────────────────────────


def test_extract_unknown_candidates(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(mode="personal", people=[], projects=[])
    unknowns = registry.extract_unknown_candidates("Saoirse went to the store")
    assert "Saoirse" in unknowns


def test_extract_unknown_candidates_skips_known(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(
        mode="personal",
        people=[{"name": "Riley", "relationship": "daughter", "context": "personal"}],
        projects=[],
    )
    unknowns = registry.extract_unknown_candidates("Riley went to the store")
    assert "Riley" not in unknowns


# ── summary ─────────────────────────────────────────────────────────────


def test_summary(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(
        mode="personal",
        people=[{"name": "Riley", "relationship": "daughter", "context": "personal"}],
        projects=["MemPalace"],
    )
    s = registry.summary()
    assert "personal" in s
    assert "Riley" in s
    assert "MemPalace" in s
