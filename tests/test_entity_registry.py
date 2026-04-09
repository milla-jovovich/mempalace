"""Tests for entity_registry.py — verifies Wikipedia opt-in guard."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from mempalace.entity_registry import _wikipedia_lookup, EntityRegistry


def test_wikipedia_lookup_disabled_by_default():
    """_wikipedia_lookup returns unknown when MEMPALACE_WIKIPEDIA is not set."""
    os.environ.pop("MEMPALACE_WIKIPEDIA", None)
    result = _wikipedia_lookup("Paris")
    assert result["inferred_type"] == "unknown"
    assert result["confidence"] == 0.0
    assert "disabled" in result.get("note", "").lower() or result["wiki_summary"] is None


def test_wikipedia_lookup_respects_env_var():
    """_wikipedia_lookup attempts HTTP when MEMPALACE_WIKIPEDIA=1."""
    os.environ["MEMPALACE_WIKIPEDIA"] = "1"
    try:
        with patch("mempalace.entity_registry.urllib.request.urlopen") as mock_urlopen:
            import json
            mock_response = type("MockResponse", (), {
                "read": lambda self: json.dumps({
                    "type": "standard",
                    "title": "Paris",
                    "extract": "Paris is the capital of France.",
                }).encode(),
                "__enter__": lambda self: self,
                "__exit__": lambda self, *a: None,
            })()
            mock_urlopen.return_value = mock_response
            result = _wikipedia_lookup("Paris")
            mock_urlopen.assert_called_once()
    finally:
        del os.environ["MEMPALACE_WIKIPEDIA"]


def test_entity_registry_load():
    """EntityRegistry.load() initializes from a temp directory without errors."""
    with tempfile.TemporaryDirectory() as tmpdir:
        reg = EntityRegistry.load(config_dir=Path(tmpdir))
        assert reg is not None
        assert hasattr(reg, "research")
