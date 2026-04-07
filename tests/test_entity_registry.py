from unittest.mock import patch

from mempalace.entity_registry import EntityRegistry, _wikipedia_lookup


def test_load_empty(tmp_dir):
    reg = EntityRegistry.load(config_dir=tmp_dir)
    assert reg.people == {}
    assert reg.projects == []


def test_seed_and_save(tmp_dir):
    reg = EntityRegistry.load(config_dir=tmp_dir)
    reg.seed(
        mode="personal",
        people=[
            {"name": "Alice", "relationship": "creator", "context": "personal"},
            {"name": "Max", "relationship": "son", "context": "personal"},
        ],
        projects=["MemPalace"],
    )
    assert "Alice" in reg.people
    assert "Max" in reg.people
    assert "MemPalace" in reg.projects
    assert "max" in reg.ambiguous_flags


def test_save_and_reload(tmp_dir):
    reg = EntityRegistry.load(config_dir=tmp_dir)
    reg.seed(mode="personal", people=[{"name": "Alice"}], projects=["Acme"])
    reg.save()

    reg2 = EntityRegistry.load(config_dir=tmp_dir)
    assert "Alice" in reg2.people
    assert "Acme" in reg2.projects


def test_lookup_known_person(tmp_dir):
    reg = EntityRegistry.load(config_dir=tmp_dir)
    reg.seed(mode="personal", people=[{"name": "Riley", "relationship": "daughter"}], projects=[])
    result = reg.lookup("Riley")
    assert result["type"] == "person"
    assert result["confidence"] == 1.0


def test_lookup_project(tmp_dir):
    reg = EntityRegistry.load(config_dir=tmp_dir)
    reg.seed(mode="personal", people=[], projects=["MemPalace"])
    result = reg.lookup("MemPalace")
    assert result["type"] == "project"


def test_lookup_unknown(tmp_dir):
    reg = EntityRegistry.load(config_dir=tmp_dir)
    result = reg.lookup("Zxywvut")
    assert result["type"] == "unknown"


def test_disambiguate_person_context(tmp_dir):
    reg = EntityRegistry.load(config_dir=tmp_dir)
    reg.seed(mode="personal", people=[{"name": "Max", "relationship": "son"}], projects=[])
    result = reg.lookup("Max", context="Max said hello to everyone")
    assert result["type"] == "person"


def test_disambiguate_concept_context(tmp_dir):
    reg = EntityRegistry.load(config_dir=tmp_dir)
    reg.seed(mode="personal", people=[{"name": "Ever", "relationship": "friend"}], projects=[])
    result = reg.lookup("Ever", context="have you ever since then")
    assert result["type"] == "concept"


def test_extract_people_from_query(tmp_dir):
    reg = EntityRegistry.load(config_dir=tmp_dir)
    reg.seed(
        mode="personal",
        people=[{"name": "Alice"}, {"name": "Bob"}],
        projects=[],
    )
    found = reg.extract_people_from_query("What did Alice say to Bob yesterday?")
    assert "Alice" in found
    assert "Bob" in found


def test_extract_unknown_candidates(tmp_dir):
    reg = EntityRegistry.load(config_dir=tmp_dir)
    unknowns = reg.extract_unknown_candidates("Did Zephyr meet Quorra at the park?")
    assert "Zephyr" in unknowns or "Quorra" in unknowns


def test_seed_with_aliases(tmp_dir):
    reg = EntityRegistry.load(config_dir=tmp_dir)
    reg.seed(
        mode="personal",
        people=[{"name": "Maxwell", "relationship": "son"}],
        projects=[],
        aliases={"Max": "Maxwell"},
    )
    result_canonical = reg.lookup("Maxwell")
    result_alias = reg.lookup("Max")
    assert result_canonical["type"] == "person"
    assert result_alias["type"] == "person"


# ── New tests ─────────────────────────────────────────────────────────────────


def test_learn_from_text_auto_discovers_person(tmp_dir):
    """learn_from_text should detect a person mentioned many times via dialogue + verbs."""
    reg = EntityRegistry.load(config_dir=tmp_dir)

    # Build text with "Zephira" appearing 3+ times with dialogue markers and person-verb signals
    text = (
        "Zephira said she would come over later.\n"
        "Zephira: Sure, let me check my calendar.\n"
        "Zephira asked about the project.\n"
        "I heard Zephira laughed at the story.\n"
        "She told me that Zephira knows everything.\n"
    )

    candidates = reg.learn_from_text(text, min_confidence=0.75)

    # "Zephira" should have been added to the registry as a learned person
    assert "Zephira" in reg.people
    entry = reg.people["Zephira"]
    assert entry["source"] == "learned"
    assert entry["confidence"] >= 0.75

    # The returned list should mention Zephira
    names = [c["name"] for c in candidates]
    assert "Zephira" in names


def test_disambiguate_tie_returns_none_falls_through_to_person(tmp_dir):
    """When person_score == concept_score (both > 0), _disambiguate returns None,
    so lookup falls through to the registered person result."""
    reg = EntityRegistry.load(config_dir=tmp_dir)
    # "Grace" is in COMMON_ENGLISH_WORDS → it will be flagged as ambiguous
    reg.seed(mode="personal", people=[{"name": "Grace", "relationship": "friend"}], projects=[])
    assert "grace" in reg.ambiguous_flags

    # Craft context that fires exactly one person pattern AND one concept pattern:
    #   "Grace was ..."        → PERSON: r"\b{name}\s+was\b"
    #   "the grace of ..."     → CONCEPT: r"(?:the\s+)?{name}\s+(?:of|in|at|for|to)\b"
    context = "Grace was beautiful; the grace of her movement was stunning."

    # _disambiguate should return None (tie), so lookup falls through to person
    result = reg.lookup("Grace", context=context)
    assert result["type"] == "person"
    assert result["name"] == "Grace"


def test_research_with_mock_wikipedia(tmp_dir):
    """research() should call _wikipedia_lookup, cache the result, and allow confirmation."""
    reg = EntityRegistry.load(config_dir=tmp_dir)

    fake_result = {
        "inferred_type": "person",
        "confidence": 0.90,
        "wiki_summary": "Rowan is a given name of Irish origin.",
        "wiki_title": "Rowan (name)",
    }

    with patch("mempalace.entity_registry._wikipedia_lookup", return_value=fake_result):
        result = reg.research("Rowan", auto_confirm=False)

    # Result should be cached
    assert "Rowan" in reg._data["wiki_cache"]
    cached = reg._data["wiki_cache"]["Rowan"]
    assert cached["inferred_type"] == "person"
    assert cached["confirmed"] is False

    # Confirm it as a person
    reg.confirm_research("Rowan", entity_type="person", relationship="colleague")
    assert "Rowan" in reg.people
    assert reg.people["Rowan"]["source"] == "wiki"

    # lookup should now resolve via wiki cache
    lookup_result = reg.lookup("Rowan")
    assert lookup_result["type"] == "person"
    assert lookup_result["source"] == "wiki"
