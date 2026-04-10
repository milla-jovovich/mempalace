"""
Tests for mempalace.synapse_profiles — RetrievalProfile / ProfileManager.
"""

import json
import os

import pytest

from mempalace.synapse_profiles import HARDCODED_DEFAULTS, ProfileManager


@pytest.fixture
def palace_dir(tmp_path):
    return str(tmp_path)


def test_no_config_returns_hardcoded_defaults(palace_dir):
    pm = ProfileManager(palace_dir)
    profile = pm.resolve()
    assert profile.name == "default"
    assert profile.half_life_days == 90
    assert profile.ltp_enabled is True
    assert profile.ltp_window_days == 30
    assert profile.ltp_max_boost == 2.0
    assert profile.tagging_enabled is True


def test_config_json_default_overrides_hardcoded(palace_dir):
    config = {"synapse_profiles": {"default": {"half_life_days": 120, "ltp_max_boost": 1.5}}}
    with open(os.path.join(palace_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f)
    pm = ProfileManager(palace_dir)
    profile = pm.resolve()
    assert profile.half_life_days == 120
    assert profile.ltp_max_boost == 1.5
    assert profile.ltp_window_days == 30


def test_synapse_profiles_json_overrides_config_json(palace_dir):
    config = {"synapse_profiles": {"default": {"half_life_days": 120}}}
    with open(os.path.join(palace_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f)
    profiles = {"default": {"half_life_days": 200}}
    with open(os.path.join(palace_dir, "synapse_profiles.json"), "w", encoding="utf-8") as f:
        json.dump(profiles, f)
    pm = ProfileManager(palace_dir)
    profile = pm.resolve()
    assert profile.half_life_days == 200


def test_named_profile_inherits_from_default(palace_dir):
    config = {
        "synapse_profiles": {
            "default": {"half_life_days": 90, "ltp_max_boost": 2.0},
            "orient": {"half_life_days": 180, "tagging_enabled": False},
        }
    }
    with open(os.path.join(palace_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f)
    pm = ProfileManager(palace_dir)
    profile = pm.resolve("orient")
    assert profile.half_life_days == 180
    assert profile.tagging_enabled is False
    assert profile.ltp_max_boost == 2.0


def test_unknown_profile_falls_back_to_default(palace_dir):
    pm = ProfileManager(palace_dir)
    profile = pm.resolve("nonexistent")
    assert profile.name == "default"
    assert profile.half_life_days == 90


def test_per_query_overrides_beat_profile(palace_dir):
    config = {
        "synapse_profiles": {
            "default": {"half_life_days": 90},
            "orient": {"half_life_days": 180},
        }
    }
    with open(os.path.join(palace_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f)
    pm = ProfileManager(palace_dir)
    profile = pm.resolve("orient", per_query_overrides={"half_life_days": 45})
    assert profile.half_life_days == 45


def test_per_query_none_values_ignored(palace_dir):
    config = {"synapse_profiles": {"default": {"half_life_days": 90}}}
    with open(os.path.join(palace_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f)
    pm = ProfileManager(palace_dir)
    profile = pm.resolve("default", per_query_overrides={"half_life_days": None})
    assert profile.half_life_days == 90


def test_axes_enabled_disables_missing_axes(palace_dir):
    config = {
        "synapse_profiles": {
            "evaluate": {
                "axes_enabled": ["tagging"],
                "ltp_enabled": True,
            }
        }
    }
    with open(os.path.join(palace_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f)
    pm = ProfileManager(palace_dir)
    profile = pm.resolve("evaluate")
    assert profile.tagging_enabled is True
    assert profile.ltp_enabled is False
    assert profile.association_enabled is False


def test_get_known_profiles(palace_dir):
    config = {
        "synapse_profiles": {
            "default": {},
            "orient": {},
            "decide": {},
        }
    }
    with open(os.path.join(palace_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f)
    profiles = {"evaluate": {}, "custom_agi": {}}
    with open(os.path.join(palace_dir, "synapse_profiles.json"), "w", encoding="utf-8") as f:
        json.dump(profiles, f)
    pm = ProfileManager(palace_dir)
    names = pm.get_known_profiles()
    assert "default" in names
    assert "orient" in names
    assert "evaluate" in names
    assert "custom_agi" in names


def test_to_dict_includes_name(palace_dir):
    pm = ProfileManager(palace_dir)
    profile = pm.resolve()
    d = profile.to_dict()
    assert d["name"] == "default"
    assert "half_life_days" in d


def test_file_profiles_override_named_profile(palace_dir):
    config = {"synapse_profiles": {"orient": {"half_life_days": 180}}}
    with open(os.path.join(palace_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f)
    profiles = {"orient": {"half_life_days": 365}}
    with open(os.path.join(palace_dir, "synapse_profiles.json"), "w", encoding="utf-8") as f:
        json.dump(profiles, f)
    pm = ProfileManager(palace_dir)
    profile = pm.resolve("orient")
    assert profile.half_life_days == 365


def test_malformed_config_json_handled(palace_dir):
    with open(os.path.join(palace_dir, "config.json"), "w", encoding="utf-8") as f:
        f.write("not valid json")
    pm = ProfileManager(palace_dir)
    profile = pm.resolve()
    assert profile.half_life_days == 90


def test_malformed_profiles_json_handled(palace_dir):
    with open(os.path.join(palace_dir, "synapse_profiles.json"), "w", encoding="utf-8") as f:
        f.write("{broken")
    pm = ProfileManager(palace_dir)
    profile = pm.resolve()
    assert profile.half_life_days == 90


def test_hardcoded_defaults_association_off_matches_legacy():
    assert HARDCODED_DEFAULTS["association_enabled"] is False


def test_sources_track_hardcoded(palace_dir):
    pm = ProfileManager(palace_dir)
    profile = pm.resolve()
    assert profile.get_source("half_life_days") == "hardcoded"


def test_sources_track_profile_override(palace_dir):
    config = {"synapse_profiles": {"orient": {"half_life_days": 180}}}
    with open(os.path.join(palace_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f)
    pm = ProfileManager(palace_dir)
    profile = pm.resolve("orient")
    assert profile.get_source("half_life_days") == "profile (config.json)"
    assert profile.get_source("ltp_max_boost") == "hardcoded"


def test_sources_track_per_query(palace_dir):
    pm = ProfileManager(palace_dir)
    profile = pm.resolve("default", per_query_overrides={"half_life_days": 45})
    assert profile.get_source("half_life_days") == "per-query override"


def test_to_annotated_dict(palace_dir):
    config = {"synapse_profiles": {"default": {"half_life_days": 120}}}
    with open(os.path.join(palace_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f)
    pm = ProfileManager(palace_dir)
    profile = pm.resolve()
    annotated = profile.to_annotated_dict()
    assert annotated["half_life_days"]["value"] == 120
    assert annotated["half_life_days"]["source"] == "default (config.json)"
