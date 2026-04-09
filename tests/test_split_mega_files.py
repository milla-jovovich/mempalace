import json

from mempalace import split_mega_files as smf


def test_load_known_people_falls_back_when_config_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(smf, "_KNOWN_NAMES_PATH", tmp_path / "missing.json")
    smf._KNOWN_NAMES_CACHE = None

    assert smf._load_known_people() == smf._FALLBACK_KNOWN_PEOPLE
    assert smf._load_username_map() == {}


def test_load_known_people_from_list_config(monkeypatch, tmp_path):
    config_path = tmp_path / "known_names.json"
    config_path.write_text(json.dumps(["Alice", "Ben"]))
    monkeypatch.setattr(smf, "_KNOWN_NAMES_PATH", config_path)
    smf._KNOWN_NAMES_CACHE = None

    assert smf._load_known_people() == ["Alice", "Ben"]
    assert smf._load_username_map() == {}


def test_load_known_people_from_dict_config(monkeypatch, tmp_path):
    config_path = tmp_path / "known_names.json"
    config_path.write_text(json.dumps({"names": ["Alice"], "username_map": {"jdoe": "John"}}))
    monkeypatch.setattr(smf, "_KNOWN_NAMES_PATH", config_path)
    smf._KNOWN_NAMES_CACHE = None

    assert smf._load_known_people() == ["Alice"]
    assert smf._load_username_map() == {"jdoe": "John"}


def test_extract_people_uses_username_map(monkeypatch, tmp_path):
    config_path = tmp_path / "known_names.json"
    config_path.write_text(json.dumps({"names": ["Alice"], "username_map": {"jdoe": "John"}}))
    monkeypatch.setattr(smf, "_KNOWN_NAMES_PATH", config_path)
    monkeypatch.setattr(smf, "KNOWN_PEOPLE", ["Alice"])
    smf._KNOWN_NAMES_CACHE = None

    people = smf.extract_people(["Working in /Users/jdoe/project\n"])
    assert "John" in people


def test_extract_people_detects_names_from_content(monkeypatch):
    monkeypatch.setattr(smf, "KNOWN_PEOPLE", ["Alice", "Ben"])
    people = smf.extract_people(["> Alice reviewed the change with Ben\n"])
    assert people == ["Alice", "Ben"]
