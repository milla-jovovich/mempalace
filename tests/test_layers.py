"""Tests for layers.py — Layer1 essential story generation.

Layer1.generate() previously called col.get() without a limit, which could
return truncated results on large palaces.
"""

import shutil
import tempfile
from pathlib import Path

import chromadb
import yaml

from mempalace.layers import Layer1
from mempalace.miner import mine


def _write_file(path, content):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(content, encoding="utf-8")


def test_layer1_returns_content_from_all_rooms():
    """Layer1 should pull drawers from every room in the palace."""
    tmpdir = tempfile.mkdtemp()
    try:
        project = Path(tmpdir) / "project"
        project.mkdir()

        # Create files in two directories to trigger two rooms
        _write_file(
            project / "backend" / "api.py",
            "def handle_request():\n    return 'ok'\n" * 20,
        )
        _write_file(
            project / "docs" / "guide.md",
            "# User Guide\nThis is the documentation.\n" * 20,
        )

        with open(project / "mempalace.yaml", "w") as f:
            yaml.dump(
                {
                    "wing": "test_wing",
                    "rooms": [
                        {"name": "backend", "description": "Backend API code"},
                        {"name": "docs", "description": "Documentation"},
                    ],
                },
                f,
            )

        palace_path = str(Path(tmpdir) / "palace")
        mine(str(project), palace_path)

        layer1 = Layer1(palace_path=palace_path)
        output = layer1.generate()

        assert "L1" in output
        assert output != "## L1 — No drawers found."
        assert output != "## L1 — No memories yet."
        # Verify content from both rooms is represented
        output_lower = output.lower()
        assert "backend" in output_lower or "api" in output_lower, "backend room content missing"
        assert "docs" in output_lower or "guide" in output_lower, "docs room content missing"
    finally:
        shutil.rmtree(tmpdir)


def test_layer1_with_wing_filter():
    """Layer1 with a wing filter should only return drawers from that wing."""
    tmpdir = tempfile.mkdtemp()
    try:
        palace_path = str(Path(tmpdir) / "palace")
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_or_create_collection("mempalace_drawers")

        # Insert drawers across two wings
        ids = []
        docs = []
        metas = []
        for i in range(20):
            wing = "alpha" if i < 10 else "beta"
            ids.append(f"d_{i}")
            docs.append(f"content from {wing} drawer {i}")
            metas.append({"wing": wing, "room": "general", "source_file": f"f{i}.py"})
        col.add(ids=ids, documents=docs, metadatas=metas)

        layer1 = Layer1(palace_path=palace_path, wing="alpha")
        output = layer1.generate()

        assert "L1" in output
        assert output != "## L1 — No memories yet."
        # Verify the filter excluded "beta" wing content
        assert "content from beta" not in output
    finally:
        shutil.rmtree(tmpdir)
