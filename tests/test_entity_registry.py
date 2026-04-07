from mempalace.entity_registry import EntityRegistry


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
    # max is in COMMON_ENGLISH_WORDS
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
    reg.seed(mode="personal", people=[{"name": "Max", "relationship": "son"}], projects=[])
    result = reg.lookup("Max", context="Max said something")
    assert result["type"] == "person"


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
