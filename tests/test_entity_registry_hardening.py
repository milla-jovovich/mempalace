"""Additional coverage for entity-registry research and learning paths."""

import io
import json
import urllib.error
from unittest.mock import patch

from mempalace.entity_registry import EntityRegistry, _wikipedia_lookup


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_wikipedia_lookup_disambiguation_name():
    payload = {
        "type": "disambiguation",
        "description": "given name and surname",
        "extract": "Grace may refer to people, places, or ideas.",
        "title": "Grace",
    }

    with patch("mempalace.entity_registry.urllib.request.urlopen", return_value=_FakeResponse(payload)):
        result = _wikipedia_lookup("Grace")

    assert result["inferred_type"] == "person"
    assert result["note"] == "disambiguation page with name entries"


def test_wikipedia_lookup_disambiguation_ambiguous():
    payload = {
        "type": "disambiguation",
        "description": "multiple uses",
        "extract": "Mercury may refer to many things.",
        "title": "Mercury",
    }

    with patch("mempalace.entity_registry.urllib.request.urlopen", return_value=_FakeResponse(payload)):
        result = _wikipedia_lookup("Mercury")

    assert result["inferred_type"] == "ambiguous"


def test_wikipedia_lookup_name_indicator_high_confidence():
    payload = {
        "type": "standard",
        "extract": "alice is a given name used across several cultures.",
        "title": "Alice",
    }

    with patch("mempalace.entity_registry.urllib.request.urlopen", return_value=_FakeResponse(payload)):
        result = _wikipedia_lookup("Alice")

    assert result["inferred_type"] == "person"
    assert result["confidence"] == 0.9


def test_wikipedia_lookup_name_indicator_lower_confidence():
    payload = {
        "type": "standard",
        "extract": "An Irish name found in several folk stories.",
        "title": "Example",
    }

    with patch("mempalace.entity_registry.urllib.request.urlopen", return_value=_FakeResponse(payload)):
        result = _wikipedia_lookup("Example")

    assert result["inferred_type"] == "person"
    assert result["confidence"] == 0.8


def test_wikipedia_lookup_place_indicator():
    payload = {
        "type": "standard",
        "extract": "Paris is a city in France known for art and fashion.",
        "title": "Paris",
    }

    with patch("mempalace.entity_registry.urllib.request.urlopen", return_value=_FakeResponse(payload)):
        result = _wikipedia_lookup("Paris")

    assert result["inferred_type"] == "place"


def test_wikipedia_lookup_concept_when_summary_has_no_name_or_place_signal():
    payload = {
        "type": "standard",
        "extract": "Entropy is a measure of disorder in thermodynamics.",
        "title": "Entropy",
    }

    with patch("mempalace.entity_registry.urllib.request.urlopen", return_value=_FakeResponse(payload)):
        result = _wikipedia_lookup("Entropy")

    assert result["inferred_type"] == "concept"


def test_wikipedia_lookup_404_falls_back_to_person():
    error = urllib.error.HTTPError("http://example", 404, "missing", {}, io.BytesIO())
    with patch("mempalace.entity_registry.urllib.request.urlopen", side_effect=error):
        result = _wikipedia_lookup("Xyzzy")

    assert result["inferred_type"] == "person"
    assert "not found" in result["note"]


def test_wikipedia_lookup_non_404_http_error_returns_unknown():
    error = urllib.error.HTTPError("http://example", 500, "boom", {}, io.BytesIO())
    with patch("mempalace.entity_registry.urllib.request.urlopen", side_effect=error):
        result = _wikipedia_lookup("Xyzzy")

    assert result["inferred_type"] == "unknown"


def test_wikipedia_lookup_transport_error_returns_unknown():
    with patch(
        "mempalace.entity_registry.urllib.request.urlopen",
        side_effect=urllib.error.URLError("offline"),
    ):
        result = _wikipedia_lookup("Xyzzy")

    assert result["inferred_type"] == "unknown"


def test_load_falls_back_to_empty_registry_on_invalid_json(tmp_path):
    (tmp_path / "entity_registry.json").write_text("not json", encoding="utf-8")

    registry = EntityRegistry.load(config_dir=tmp_path)

    assert registry.people == {}
    assert registry.projects == []


def test_lookup_uses_confirmed_wiki_cache(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry._data["wiki_cache"]["Saoirse"] = {
        "inferred_type": "person",
        "confidence": 0.88,
        "confirmed": True,
    }

    result = registry.lookup("Saoirse")

    assert result["type"] == "person"
    assert result["source"] == "wiki"


def test_disambiguate_returns_none_for_neutral_context(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    person_info = {"source": "onboarding", "contexts": ["personal"]}

    assert registry._disambiguate("Grace", "Abstract elegance can be difficult to classify here.", person_info) is None


def test_confirm_research_common_word_adds_ambiguous_flag(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(mode="personal", people=[], projects=[])
    registry._data["wiki_cache"]["Grace"] = {"confirmed": False}

    registry.confirm_research("Grace", entity_type="person", relationship="friend")

    assert "Grace" in registry.people
    assert "grace" in registry.ambiguous_flags


def test_learn_from_text_combo_mode_defaults_learned_people_to_personal(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(mode="combo", people=[], projects=[])

    with patch("mempalace.entity_detector.extract_candidates", return_value={"Saoirse": 3}), patch(
        "mempalace.entity_detector.score_entity",
        return_value={"name_like": 0.9},
    ), patch(
        "mempalace.entity_detector.classify_entity",
        return_value={"type": "person", "confidence": 0.91, "name": "Saoirse"},
    ):
        learned = registry.learn_from_text("Saoirse reviewed the migration plan.", min_confidence=0.75)

    assert learned[0]["name"] == "Saoirse"
    assert registry.people["Saoirse"]["contexts"] == ["personal"]


def test_extract_people_from_query_uses_disambiguation_for_ambiguous_names(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(
        mode="personal",
        people=[{"name": "Grace", "relationship": "friend", "context": "personal"}],
        projects=[],
    )

    found = registry.extract_people_from_query("Grace reviewed the release notes yesterday.")

    assert found == ["Grace"]


def test_extract_unknown_candidates_skips_common_english_words(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(mode="personal", people=[], projects=[])

    unknowns = registry.extract_unknown_candidates("Monday met Saoirse in town")

    assert "Saoirse" in unknowns
    assert "Monday" not in unknowns


def test_summary_truncates_long_people_list(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(
        mode="personal",
        people=[{"name": f"Person{i}", "relationship": "friend", "context": "personal"} for i in range(9)],
        projects=["MemPalace"],
    )

    summary = registry.summary()

    assert "..." in summary
