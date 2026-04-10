import os
import json
import tempfile

import pytest

from mempalace.config import (
    MempalaceConfig,
    sanitize_name,
    sanitize_content,
    MAX_NAME_LENGTH,
)


# ── MempalaceConfig basic behaviour ───────────────────────────────────


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


def test_env_override():
    os.environ["MEMPALACE_PALACE_PATH"] = "/env/palace"
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    assert cfg.palace_path == "/env/palace"
    del os.environ["MEMPALACE_PALACE_PATH"]


def test_init():
    tmpdir = tempfile.mkdtemp()
    cfg = MempalaceConfig(config_dir=tmpdir)
    cfg.init()
    assert os.path.exists(os.path.join(tmpdir, "config.json"))


# ── Precedence chain: defaults < file < env ────────────────────────────


def test_env_overrides_file(tmp_path):
    """Env var takes precedence over config file value."""
    (tmp_path / "config.json").write_text(
        json.dumps({"palace_path": "/from/file"}), encoding="utf-8"
    )
    os.environ["MEMPALACE_PALACE_PATH"] = "/from/env"
    try:
        cfg = MempalaceConfig(config_dir=str(tmp_path))
        assert cfg.palace_path == "/from/env"
    finally:
        del os.environ["MEMPALACE_PALACE_PATH"]


def test_file_overrides_default(tmp_path):
    """Config file value takes precedence over default."""
    os.environ.pop("MEMPALACE_PALACE_PATH", None)
    os.environ.pop("MEMPAL_PALACE_PATH", None)
    (tmp_path / "config.json").write_text(
        json.dumps({"palace_path": "/custom"}), encoding="utf-8"
    )
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    assert cfg.palace_path == "/custom"


# ── Invalid / edge-case config files ──────────────────────────────────


def test_empty_config_file_uses_defaults(tmp_path):
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    assert cfg.collection_name == "mempalace_drawers"
    assert isinstance(cfg.topic_wings, list)


def test_missing_config_dir_uses_defaults(tmp_path):
    cfg = MempalaceConfig(config_dir=str(tmp_path / "nonexistent"))
    assert cfg.palace_path  # returns default, no crash


def test_binary_garbage_config_file(tmp_path):
    (tmp_path / "config.json").write_text("\x80NOT_JSON\xff", encoding="utf-8", errors="replace")
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    assert cfg.palace_path  # falls back to default


def test_nested_values_in_config(tmp_path):
    (tmp_path / "config.json").write_text(
        json.dumps({
            "palace_path": "/nested",
            "hall_keywords": {"custom": ["kw1", "kw2"]},
            "topic_wings": ["wing_a"],
        }),
        encoding="utf-8",
    )
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    assert cfg.hall_keywords == {"custom": ["kw1", "kw2"]}
    assert cfg.topic_wings == ["wing_a"]


def test_init_writes_valid_json(tmp_path):
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    cfg.init()
    with open(tmp_path / "config.json") as f:
        data = json.load(f)
    assert "palace_path" in data
    assert "collection_name" in data
    assert "topic_wings" in data
    assert "hall_keywords" in data


# ── sanitize_name ─────────────────────────────────────────────────────


def test_sanitize_name_valid():
    assert sanitize_name("my_wing") == "my_wing"


def test_sanitize_name_strips_whitespace():
    assert sanitize_name("  my_wing  ") == "my_wing"


def test_sanitize_name_empty_raises():
    with pytest.raises(ValueError, match="non-empty"):
        sanitize_name("")


def test_sanitize_name_whitespace_only_raises():
    with pytest.raises(ValueError, match="non-empty"):
        sanitize_name("   ")


def test_sanitize_name_too_long_raises():
    with pytest.raises(ValueError, match="maximum length"):
        sanitize_name("a" * (MAX_NAME_LENGTH + 1))


def test_sanitize_name_path_traversal_raises():
    with pytest.raises(ValueError, match="path characters"):
        sanitize_name("../etc/passwd")


def test_sanitize_name_backslash_raises():
    with pytest.raises(ValueError, match="path characters"):
        sanitize_name("wing\\room")


def test_sanitize_name_null_byte_raises():
    with pytest.raises(ValueError, match="null bytes"):
        sanitize_name("wing\x00name")


def test_sanitize_name_not_string_raises():
    with pytest.raises(ValueError, match="non-empty"):
        sanitize_name(123)


# ── sanitize_content ──────────────────────────────────────────────────


def test_sanitize_content_valid():
    assert sanitize_content("hello world") == "hello world"


def test_sanitize_content_empty_raises():
    with pytest.raises(ValueError, match="non-empty"):
        sanitize_content("")


def test_sanitize_content_too_long_raises():
    with pytest.raises(ValueError, match="maximum length"):
        sanitize_content("x" * 100_001)


def test_sanitize_content_null_byte_raises():
    with pytest.raises(ValueError, match="null bytes"):
        sanitize_content("content\x00here")


def test_sanitize_content_custom_max_length():
    with pytest.raises(ValueError, match="maximum length"):
        sanitize_content("abcdef", max_length=5)
