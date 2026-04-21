import os
import json
import tempfile

import pytest
from mempalace.config import MempalaceConfig, sanitize_kg_value, sanitize_name


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


# --- hooks config ---


def test_hooks_save_interval_default():
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    assert cfg.hooks_save_interval == 15


def test_hooks_save_interval_from_config():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"hooks": {"save_interval": 50}}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.hooks_save_interval == 50


def test_hooks_save_interval_zero_disables():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"hooks": {"save_interval": 0}}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.hooks_save_interval == 0


def test_hooks_save_interval_env_override():
    os.environ["MEMPALACE_HOOKS_SAVE_INTERVAL"] = "30"
    try:
        cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
        assert cfg.hooks_save_interval == 30
    finally:
        del os.environ["MEMPALACE_HOOKS_SAVE_INTERVAL"]


def test_hooks_save_interval_env_zero():
    os.environ["MEMPALACE_HOOKS_SAVE_INTERVAL"] = "0"
    try:
        cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
        assert cfg.hooks_save_interval == 0
    finally:
        del os.environ["MEMPALACE_HOOKS_SAVE_INTERVAL"]


def test_hooks_save_interval_negative_clamped():
    os.environ["MEMPALACE_HOOKS_SAVE_INTERVAL"] = "-5"
    try:
        cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
        assert cfg.hooks_save_interval == 0
    finally:
        del os.environ["MEMPALACE_HOOKS_SAVE_INTERVAL"]


def test_hooks_precompact_default():
    cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
    assert cfg.hooks_precompact is True


def test_hooks_precompact_disabled():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"hooks": {"precompact": False}}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.hooks_precompact is False


def test_hooks_precompact_env_override():
    os.environ["MEMPALACE_HOOKS_PRECOMPACT"] = "false"
    try:
        cfg = MempalaceConfig(config_dir=tempfile.mkdtemp())
        assert cfg.hooks_precompact is False
    finally:
        del os.environ["MEMPALACE_HOOKS_PRECOMPACT"]


def test_hooks_save_interval_and_precompact_independent():
    """Disabling stop hook doesn't affect precompact and vice versa."""
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"hooks": {"save_interval": 0, "precompact": True}}, f)
    cfg = MempalaceConfig(config_dir=tmpdir)
    assert cfg.hooks_save_interval == 0
    assert cfg.hooks_precompact is True
