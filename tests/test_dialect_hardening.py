"""Additional AAAK dialect coverage for file and layer generation paths."""

import json

from mempalace.dialect import Dialect


def test_from_config_and_save_config_round_trip(tmp_path):
    config_path = tmp_path / "entities.json"
    config_path.write_text(
        json.dumps({"entities": {"Alice": "ALC"}, "skip_names": ["SkipMe"]}),
        encoding="utf-8",
    )

    dialect = Dialect.from_config(str(config_path))
    saved_path = tmp_path / "saved.json"
    dialect.save_config(str(saved_path))

    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    assert saved["entities"]["Alice"] == "ALC"
    assert saved["skip_names"] == ["skipme"]


def test_encode_entity_prefers_lowercase_aliases_and_falls_back_to_autocode():
    dialect = Dialect(entities={"Alice": "ALC", "GraphQL": "GQL"}, skip_names=["skip"])

    assert dialect.encode_entity("alice") == "ALC"
    assert dialect.encode_entity("GraphQL subsystem") == "GQL"
    assert dialect.encode_entity("Skip Person") is None
    assert dialect.encode_entity("Zed") == "ZED"


def test_encode_emotions_and_flags_cover_dedupes_and_fallbacks():
    dialect = Dialect()
    zettel = {
        "origin_moment": True,
        "sensitivity": "MAXIMUM privacy",
        "notes": "Foundational pillar with pivot and genesis energy.",
        "origin_label": "Genesis event",
    }

    assert dialect.encode_emotions(["joy", "joy", "mystery"]) == "joy+myst"
    assert dialect.get_flags(zettel) == "ORIGIN+SENSITIVE+CORE+GENESIS+PIVOT"


def test_detect_flags_and_entities_fallback_cap_at_three():
    dialect = Dialect()
    flags = dialect._detect_flags("This critical breakthrough changed the roadmap and became a core milestone.")
    entities = dialect._detect_entities_in_text("I met Alice Bob Carol Dave during review.")

    assert len(flags) <= 3
    assert len(entities) == 3


def test_extract_key_quote_handles_apostrophes_and_title_fallback():
    dialect = Dialect()
    zettel_with_quote = {
        "content": "He admitted: 'I was wrong about the deploy plan.'",
        "origin_label": "",
        "notes": "",
        "title": "Deploy - Review",
    }
    zettel_with_title_only = {
        "content": "No quotes here at all.",
        "origin_label": "",
        "notes": "",
        "title": "Deploy - Review Notes",
    }

    assert "wrong about the deploy plan" in dialect.extract_key_quote(zettel_with_quote)
    assert dialect.extract_key_quote(zettel_with_title_only) == "Review Notes"


def test_encode_zettel_uses_unknown_entity_fallback_and_flags():
    dialect = Dialect(skip_names=["alice"])
    zettel = {
        "id": "zettel-999",
        "people": ["Alice"],
        "topics": [],
        "content": "No quoted material here.",
        "emotional_weight": 0.4,
        "emotional_tone": [],
        "origin_moment": False,
        "sensitivity": "",
        "notes": "genesis pivot",
        "origin_label": "",
        "title": "Deploy Notes",
    }

    encoded = dialect.encode_zettel(zettel)

    assert encoded.startswith("999:???|misc|0.4")
    assert "GENESIS+PIVOT" in encoded


def test_encode_file_and_decode_include_arc_and_tunnels():
    dialect = Dialect(entities={"Alice": "ALC"})
    payload = {
        "source_file": "001-memory.txt",
        "emotional_arc": "journey",
        "zettels": [
            {
                "id": "zettel-001",
                "people": ["Alice"],
                "topics": ["memory", "ai"],
                "content": '"I want to remember everything."',
                "emotional_weight": 0.9,
                "emotional_tone": ["joy"],
                "origin_moment": False,
                "sensitivity": "",
                "notes": "",
                "origin_label": "",
                "title": "Memory - Discussion",
                "date_context": "2026-03-01",
            }
        ],
        "tunnels": [{"from": "zettel-001", "to": "zettel-002", "label": "follows: temporal"}],
    }

    encoded = dialect.encode_file(payload)
    decoded = dialect.decode(encoded)

    assert "ARC:journey" in encoded
    assert decoded["arc"] == "journey"
    assert decoded["tunnels"] == ["T:001<->002|follows"]


def test_compress_file_and_compress_all_write_outputs(tmp_path):
    dialect = Dialect(entities={"Alice": "ALC"})
    payload = {
        "source_file": "001-memory.txt",
        "zettels": [
            {
                "id": "zettel-001",
                "people": ["Alice"],
                "topics": ["memory"],
                "content": '"Remember this moment."',
                "emotional_weight": 0.8,
                "emotional_tone": ["joy"],
                "origin_moment": False,
                "sensitivity": "",
                "notes": "",
                "origin_label": "",
                "title": "Memory - Discussion",
                "date_context": "2026-03-01",
            }
        ],
        "tunnels": [],
    }
    input_file = tmp_path / "file_001.json"
    input_file.write_text(json.dumps(payload), encoding="utf-8")
    second_file = tmp_path / "file_002.json"
    second_file.write_text(json.dumps(payload | {"source_file": "002-memory.txt"}), encoding="utf-8")

    single_out = tmp_path / "single.aaak"
    all_out = tmp_path / "all.aaak"

    single = dialect.compress_file(str(input_file), output_path=str(single_out))
    combined = dialect.compress_all(str(tmp_path), output_path=str(all_out))

    assert single_out.read_text(encoding="utf-8") == single
    assert all_out.read_text(encoding="utf-8") == combined
    assert "---" in combined


def test_generate_layer1_groups_identity_moments_and_tunnels(tmp_path):
    dialect = Dialect(entities={"Alice": "ALC", "Bob": "BOB", "Cara": "CAR"})
    zettel_dir = tmp_path / "zettels"
    zettel_dir.mkdir()
    (zettel_dir / "notes.txt").write_text("noise", encoding="utf-8")

    file_one = {
        "zettels": [
            {
                "id": "zettel-001",
                "people": ["Alice"],
                "topics": ["memory", "identity"],
                "content": '"I chose to keep building despite the risk."',
                "emotional_weight": 0.95,
                "emotional_tone": ["joy"],
                "origin_moment": False,
                "sensitivity": "private",
                "notes": "",
                "origin_label": "",
                "title": "Memory - Building",
                "date_context": "2026-03-01, afternoon",
            }
        ],
        "tunnels": [{"from": "zettel-001", "to": "zettel-002", "label": "bridges: story"}],
    }
    file_two = {
        "zettels": [
            {
                "id": "zettel-002",
                "people": ["Bob", "Cara"],
                "topics": ["core", "story"],
                "content": "No direct quote here.",
                "emotional_weight": 0.20,
                "emotional_tone": [],
                "origin_moment": True,
                "sensitivity": "",
                "notes": "foundational pillar",
                "origin_label": "Genesis scene",
                "title": "Story - Origins",
                "date_context": "2026-03-02, morning",
            }
        ],
        "tunnels": [],
    }
    (zettel_dir / "file_001.json").write_text(json.dumps(file_one), encoding="utf-8")
    (zettel_dir / "file_002.json").write_text(json.dumps(file_two), encoding="utf-8")

    output_path = tmp_path / "layer1.txt"
    result = dialect.generate_layer1(
        str(zettel_dir),
        output_path=str(output_path),
        identity_sections={"IDENTITY": ["ALC|builder", "BOB|ally"]},
        weight_threshold=0.9,
    )

    assert output_path.read_text(encoding="utf-8") == result
    assert "## LAYER 1 -- ESSENTIAL STORY" in result
    assert "=IDENTITY=" in result
    assert "=MOMENTS[2026-03-01]=" in result
    assert "=MOMENTS[2026-03-02]=" in result
    assert "SENSITIVE" in result
    assert "ORIGIN+CORE+GENESIS" in result
    assert "=TUNNELS=" in result
