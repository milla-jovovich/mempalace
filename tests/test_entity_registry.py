"""Tests for mempalace.entity_registry — entity lookup and disambiguation."""

import json

import pytest

from mempalace.entity_registry import EntityRegistry


@pytest.fixture()
def registry(tmp_path):
    reg = EntityRegistry.load(config_dir=tmp_path)
    reg.seed(
        mode="personal",
        people=[
            {"name": "Alice", "relationship": "self", "context": "personal"},
            {"name": "Max", "relationship": "son", "context": "personal"},
            {"name": "Riley", "relationship": "daughter", "context": "personal"},
            {"name": "Grace", "relationship": "friend", "context": "personal"},
        ],
        projects=["MemPalace", "Acme"],
        aliases={"Maxwell": "Max"},
    )
    return reg


class TestLoad:
    def test_empty_registry(self, tmp_path):
        reg = EntityRegistry.load(config_dir=tmp_path)
        assert reg.mode == "personal"
        assert reg.people == {}

    def test_load_existing(self, tmp_path):
        data = {
            "version": 1,
            "mode": "work",
            "people": {"Bob": {"source": "onboarding", "confidence": 1.0}},
            "projects": [],
            "ambiguous_flags": [],
            "wiki_cache": {},
        }
        (tmp_path / "entity_registry.json").write_text(json.dumps(data))
        reg = EntityRegistry.load(config_dir=tmp_path)
        assert reg.mode == "work"
        assert "Bob" in reg.people


class TestSeed:
    def test_seed_people(self, registry):
        assert "Alice" in registry.people
        assert "Max" in registry.people
        assert registry.people["Alice"]["source"] == "onboarding"

    def test_seed_projects(self, registry):
        assert "MemPalace" in registry.projects

    def test_aliases_registered(self, registry):
        assert "Maxwell" in registry.people
        assert registry.people["Maxwell"].get("canonical") == "Max"

    def test_ambiguous_flags(self, registry):
        assert "grace" in registry.ambiguous_flags
        assert "max" in registry.ambiguous_flags

    def test_save_creates_file(self, tmp_path):
        reg = EntityRegistry.load(config_dir=tmp_path)
        reg.seed(mode="personal", people=[{"name": "Test"}], projects=[])
        assert (tmp_path / "entity_registry.json").exists()


class TestLookup:
    def test_known_person(self, registry):
        result = registry.lookup("Alice")
        assert result["type"] == "person"
        assert result["confidence"] == 1.0
        assert result["source"] == "onboarding"

    def test_alias_lookup(self, registry):
        result = registry.lookup("Maxwell")
        assert result["type"] == "person"

    def test_project_lookup(self, registry):
        result = registry.lookup("MemPalace")
        assert result["type"] == "project"
        assert result["confidence"] == 1.0

    def test_unknown_word(self, registry):
        result = registry.lookup("Xyzzy")
        assert result["type"] == "unknown"
        assert result["confidence"] == 0.0

    def test_case_insensitive(self, registry):
        result = registry.lookup("alice")
        assert result["type"] == "person"


class TestDisambiguation:
    def test_grace_as_person(self, registry):
        result = registry.lookup("Grace", context="I saw Grace at the park yesterday")
        assert result["type"] == "person"

    def test_grace_as_concept(self, registry):
        result = registry.lookup("Grace", context="the grace of the movement was beautiful")
        assert result["type"] == "concept"

    def test_max_as_person(self, registry):
        result = registry.lookup("Max", context="Max said he wants pizza for dinner")
        assert result["type"] == "person"


class TestExtractPeopleFromQuery:
    def test_finds_known_people(self, registry):
        found = registry.extract_people_from_query("What did Alice and Riley do yesterday?")
        assert "Alice" in found
        assert "Riley" in found

    def test_empty_query(self, registry):
        assert registry.extract_people_from_query("") == []

    def test_no_people(self, registry):
        assert registry.extract_people_from_query("What is the weather?") == []


class TestExtractUnknownCandidates:
    def test_finds_capitalized_unknowns(self, registry):
        candidates = registry.extract_unknown_candidates("I met Zephyr at the park")
        assert "Zephyr" in candidates

    def test_ignores_known_people(self, registry):
        candidates = registry.extract_unknown_candidates("Alice went to the store")
        assert "Alice" not in candidates


class TestSummary:
    def test_summary_format(self, registry):
        s = registry.summary()
        assert "Mode: personal" in s
        assert "People:" in s
        assert "Projects:" in s
