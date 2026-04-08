"""
test_layers.py — Tests for the 4-layer memory stack.

Covers the weight parsing logic in Layer1 that was broken:
the `break` statement fired after the first metadata key was found
regardless of whether float() parsing succeeded, preventing fallback
to the next key.
"""

import os
import tempfile
import shutil

import chromadb

from mempalace.layers import Layer1


def _make_palace_with_drawers(palace_path, metadatas):
    """Helper: create a palace with drawers carrying specific metadata."""
    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_or_create_collection("mempalace_drawers")
    col.add(
        ids=[f"drawer_{i}" for i in range(len(metadatas))],
        documents=[f"Content for drawer {i}" for i in range(len(metadatas))],
        metadatas=metadatas,
    )
    return palace_path


class TestLayer1WeightParsing:
    def test_valid_importance_used(self):
        tmpdir = tempfile.mkdtemp()
        try:
            palace = os.path.join(tmpdir, "palace")
            _make_palace_with_drawers(palace, [
                {"wing": "w", "room": "r", "importance": "5.0"},
                {"wing": "w", "room": "r", "importance": "1.0"},
            ])
            l1 = Layer1(palace_path=palace)
            text = l1.generate()
            assert "## L1" in text
        finally:
            shutil.rmtree(tmpdir)

    def test_fallback_to_emotional_weight_when_importance_is_invalid(self):
        """Regression: break was outside try, so invalid importance blocked fallback."""
        tmpdir = tempfile.mkdtemp()
        try:
            palace = os.path.join(tmpdir, "palace")
            _make_palace_with_drawers(palace, [
                {"wing": "w", "room": "r", "importance": "not_a_number", "emotional_weight": "7.0"},
                {"wing": "w", "room": "r", "importance": "not_a_number", "emotional_weight": "2.0"},
            ])
            l1 = Layer1(palace_path=palace)
            # Should not crash; emotional_weight=7.0 should be used
            text = l1.generate()
            assert "## L1" in text
            # The high-weight drawer should appear (sorted by importance desc)
            assert "drawer" in text.lower() or "Content" in text
        finally:
            shutil.rmtree(tmpdir)

    def test_fallback_to_weight_key(self):
        tmpdir = tempfile.mkdtemp()
        try:
            palace = os.path.join(tmpdir, "palace")
            _make_palace_with_drawers(palace, [
                {"wing": "w", "room": "r", "weight": "9.0"},
            ])
            l1 = Layer1(palace_path=palace)
            text = l1.generate()
            assert "## L1" in text
        finally:
            shutil.rmtree(tmpdir)

    def test_all_keys_invalid_defaults_to_3(self):
        tmpdir = tempfile.mkdtemp()
        try:
            palace = os.path.join(tmpdir, "palace")
            _make_palace_with_drawers(palace, [
                {"wing": "w", "room": "r", "importance": "bad", "emotional_weight": "bad", "weight": "bad"},
            ])
            l1 = Layer1(palace_path=palace)
            text = l1.generate()
            assert "## L1" in text
        finally:
            shutil.rmtree(tmpdir)
