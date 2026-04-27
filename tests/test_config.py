import os
import json
import tempfile

import pytest
from mempalace.config import (
    DEFAULT_CLOSETS,
    MempalaceConfig,
    sanitize_kg_value,
    sanitize_name,
)


def test_default_config():
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    assert "palace" in cfg.palace_path
    assert cfg.collection_name == "mempalace_drawers"


def test_config_from_file():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"palace_path": "/custom/palace"}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.palace_path == "/custom/palace"


def test_embedding_device_defaults_to_auto(monkeypatch):
    monkeypatch.delenv("MEMPALACE_EMBEDDING_DEVICE", raising=False)
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    assert cfg.embedding_device == "auto"


def test_embedding_device_from_config_is_normalized(tmp_path, monkeypatch):
    monkeypatch.delenv("MEMPALACE_EMBEDDING_DEVICE", raising=False)
    with open(tmp_path / "config.json", "w") as f:
        json.dump({"embedding_device": "  CUDA  "}, f)

    cfg = MempalaceConfig(config_dir=str(tmp_path))
    assert cfg.embedding_device == "cuda"


def test_embedding_device_env_overrides_config(tmp_path, monkeypatch):
    with open(tmp_path / "config.json", "w") as f:
        json.dump({"embedding_device": "cpu"}, f)
    monkeypatch.setenv("MEMPALACE_EMBEDDING_DEVICE", "  CoreML  ")

    cfg = MempalaceConfig(config_dir=str(tmp_path))
    assert cfg.embedding_device == "coreml"


def test_env_override():
    raw = "/env/palace"
    os.environ["MEMPALACE_PALACE_PATH"] = raw
    try:
        cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
        # palace_path normalizes with abspath + expanduser to match the
        # --palace CLI code path. On Unix that's a no-op for "/env/palace";
        # on Windows abspath prepends the current drive letter.
        assert cfg.palace_path == os.path.abspath(os.path.expanduser(raw))
    finally:
        del os.environ["MEMPALACE_PALACE_PATH"]


def test_env_path_expanduser():
    # Tilde must be expanded to match the --palace CLI code path. We don't
    # assert "~" is absent from the final string because Windows 8.3 short
    # paths (e.g. C:\Users\RUNNER~1\...) legitimately contain tildes — the
    # equality check is authoritative.
    raw = os.path.join("~", "mempalace-test")
    os.environ["MEMPALACE_PALACE_PATH"] = raw
    try:
        cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
        assert cfg.palace_path == os.path.abspath(os.path.expanduser(raw))
        assert cfg.palace_path.endswith("mempalace-test")
    finally:
        del os.environ["MEMPALACE_PALACE_PATH"]


def test_env_path_abspath_collapses_traversal():
    # Build a raw path with a .. segment using the platform separator so
    # the assertion is portable (Windows uses \, POSIX uses /).
    raw = os.path.join(tempfile.gettempdir(), "palace", "..", "mempalace-test")
    expected = os.path.abspath(os.path.expanduser(raw))
    os.environ["MEMPALACE_PALACE_PATH"] = raw
    try:
        cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
        # .. segments must be collapsed, not preserved literally.
        assert ".." not in cfg.palace_path
        assert cfg.palace_path == expected
    finally:
        del os.environ["MEMPALACE_PALACE_PATH"]


def test_env_path_legacy_alias_normalized():
    # Legacy MEMPAL_PALACE_PATH gets the same normalization treatment as
    # MEMPALACE_PALACE_PATH. We don't assert "~" is absent from the final
    # string because Windows 8.3 short paths (e.g. C:\Users\RUNNER~1\...)
    # legitimately contain tildes — the equality check below is authoritative.
    os.environ.pop("MEMPALACE_PALACE_PATH", None)
    raw = os.path.join("~", "legacy-alias", "..", "mempalace-test")
    os.environ["MEMPAL_PALACE_PATH"] = raw
    try:
        cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
        assert ".." not in cfg.palace_path
        assert cfg.palace_path == os.path.abspath(os.path.expanduser(raw))
    finally:
        del os.environ["MEMPAL_PALACE_PATH"]


def test_init():
    tmpdir = tempfile.mkdtemp()
    cfg = MempalaceConfig(config_dir=tmpdir)
    cfg.init()
    assert os.path.exists(os.path.join(tmpdir, "config.json"))


# --- sanitize_name ---


def test_sanitize_name_ascii():
    assert sanitize_name("hello") == "hello"


def test_sanitize_name_latvian():
    assert sanitize_name("Jānis") == "Jānis"


def test_sanitize_name_cjk():
    assert sanitize_name("太郎") == "太郎"


def test_sanitize_name_cyrillic():
    assert sanitize_name("Алексей") == "Алексей"


def test_sanitize_name_rejects_leading_underscore():
    with pytest.raises(ValueError):
        sanitize_name("_foo")


def test_sanitize_name_rejects_path_traversal():
    with pytest.raises(ValueError):
        sanitize_name("../etc/passwd")


def test_sanitize_name_rejects_empty():
    with pytest.raises(ValueError):
        sanitize_name("")


# --- sanitize_kg_value ---


def test_kg_value_accepts_commas():
    assert sanitize_kg_value("Alice, Bob, and Carol") == "Alice, Bob, and Carol"


def test_kg_value_accepts_colons():
    assert sanitize_kg_value("role: engineer") == "role: engineer"


def test_kg_value_accepts_parentheses():
    assert sanitize_kg_value("Python (programming)") == "Python (programming)"


def test_kg_value_accepts_slashes():
    assert sanitize_kg_value("owner/repo") == "owner/repo"


def test_kg_value_accepts_hash():
    assert sanitize_kg_value("issue #123") == "issue #123"


def test_kg_value_accepts_unicode():
    assert sanitize_kg_value("Jānis Bērziņš") == "Jānis Bērziņš"


def test_kg_value_strips_whitespace():
    assert sanitize_kg_value("  hello  ") == "hello"


def test_kg_value_rejects_empty():
    with pytest.raises(ValueError):
        sanitize_kg_value("")


def test_kg_value_rejects_whitespace_only():
    with pytest.raises(ValueError):
        sanitize_kg_value("   ")


def test_kg_value_rejects_null_bytes():
    with pytest.raises(ValueError):
        sanitize_kg_value("hello\x00world")


def test_kg_value_rejects_over_length():
    with pytest.raises(ValueError):
        sanitize_kg_value("a" * 129)


# --- closets block ---


def test_closets_defaults_when_no_file():
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    c = cfg.closets
    # All documented keys present
    assert set(c.keys()) == set(DEFAULT_CLOSETS.keys())
    # Values match the documented baseline (= current hardcoded constants)
    assert c["char_limit"] == 1500
    assert c["extract_window"] == 5000
    assert c["rank_boosts"] == [0.40, 0.25, 0.15, 0.08, 0.04]
    assert c["distance_cap"] == 1.5
    assert c["max_hydration_chars"] == 10000
    assert c["fallback_min_lines"] == 3
    assert c["enabled"] is True


def test_closets_from_file_partial_override():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"closets": {"char_limit": 2000, "distance_cap": 0.9}}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)
    c = cfg.closets
    # Overridden
    assert c["char_limit"] == 2000
    assert c["distance_cap"] == 0.9
    # Fallback to defaults for keys not in the file
    assert c["rank_boosts"] == DEFAULT_CLOSETS["rank_boosts"]
    assert c["extract_window"] == DEFAULT_CLOSETS["extract_window"]


def test_closets_env_beats_file():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"closets": {"char_limit": 2000}}, f)
    os.environ["MEMPALACE_CLOSET_CHAR_LIMIT"] = "777"
    try:
        cfg = MempalaceConfig(config_dir=tmpdir)
        assert cfg.closets["char_limit"] == 777
    finally:
        del os.environ["MEMPALACE_CLOSET_CHAR_LIMIT"]


def test_closets_env_rank_boosts_csv():
    os.environ["MEMPALACE_CLOSET_RANK_BOOSTS"] = "0.5, 0.3, 0.1"
    try:
        cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
        assert cfg.closets["rank_boosts"] == [0.5, 0.3, 0.1]
    finally:
        del os.environ["MEMPALACE_CLOSET_RANK_BOOSTS"]


def test_closets_env_bool():
    os.environ["MEMPALACE_CLOSET_ENABLED"] = "false"
    try:
        cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
        assert cfg.closets["enabled"] is False
    finally:
        del os.environ["MEMPALACE_CLOSET_ENABLED"]


def test_closets_env_invalid_falls_through_to_default():
    # Malformed env values must not zero out — should fall through to default.
    os.environ["MEMPALACE_CLOSET_CHAR_LIMIT"] = "not-a-number"
    os.environ["MEMPALACE_CLOSET_RANK_BOOSTS"] = "abc,def"
    try:
        cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
        c = cfg.closets
        assert c["char_limit"] == DEFAULT_CLOSETS["char_limit"]
        assert c["rank_boosts"] == DEFAULT_CLOSETS["rank_boosts"]
    finally:
        del os.environ["MEMPALACE_CLOSET_CHAR_LIMIT"]
        del os.environ["MEMPALACE_CLOSET_RANK_BOOSTS"]


def test_closets_malformed_file_rank_boosts_recovers():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"closets": {"rank_boosts": "not a list"}}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.closets["rank_boosts"] == DEFAULT_CLOSETS["rank_boosts"]


def test_closets_source_tracking():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"closets": {"char_limit": 2000}}, f)
    os.environ["MEMPALACE_CLOSET_DISTANCE_CAP"] = "0.9"
    try:
        cfg = MempalaceConfig(config_dir=tmpdir)
        src = cfg.closets_source()
        assert src["distance_cap"] == "env"
        assert src["char_limit"] == "file"
        assert src["rank_boosts"] == "default"
    finally:
        del os.environ["MEMPALACE_CLOSET_DISTANCE_CAP"]


def test_init_emits_closets_block():
    tmpdir = tempfile.mkdtemp()
    cfg = MempalaceConfig(config_dir=tmpdir)
    cfg.init()
    with open(os.path.join(tmpdir, "config.json")) as f:
        written = json.load(f)
    assert "closets" in written
    assert written["closets"]["char_limit"] == DEFAULT_CLOSETS["char_limit"]
