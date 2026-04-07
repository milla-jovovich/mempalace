"""Tests for miner.status() — palace status display.

The status function previously used a hardcoded limit=10000, which caused it
to miss wings and rooms filed after the first 10k drawers.  The fix uses
get_all() which reads in batches with no cap.
"""

import shutil
import tempfile
from pathlib import Path

import chromadb
import yaml

from mempalace.miner import mine, status


def _write_file(path, content):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(content, encoding="utf-8")


def test_status_counts_all_drawers(capsys):
    """status() must report the total drawer count accurately."""
    tmpdir = tempfile.mkdtemp()
    try:
        project = Path(tmpdir) / "project"
        project.mkdir()

        # Create enough content to generate multiple drawers
        _write_file(
            project / "src" / "app.py",
            "def main():\n    print('hello world')\n" * 30,
        )
        _write_file(
            project / "src" / "utils.py",
            "def helper():\n    return 42\n" * 30,
        )

        with open(project / "mempalace.yaml", "w") as f:
            yaml.dump(
                {
                    "wing": "my_project",
                    "rooms": [{"name": "src", "description": "Source code"}],
                },
                f,
            )

        palace_path = str(Path(tmpdir) / "palace")
        mine(str(project), palace_path)

        # Verify the drawer count matches what ChromaDB reports
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
        expected_count = col.count()

        status(palace_path)
        output = capsys.readouterr().out

        assert f"{expected_count} drawers" in output
        assert "WING: my_project" in output
    finally:
        shutil.rmtree(tmpdir)


def test_status_reports_multiple_wings(capsys):
    """status() must list all wings when palace has drawers in multiple wings."""
    tmpdir = tempfile.mkdtemp()
    try:
        palace_path = str(Path(tmpdir) / "palace")
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_or_create_collection("mempalace_drawers")

        # Insert drawers across 3 wings
        ids = []
        docs = []
        metas = []
        for i in range(90):
            wing = f"wing_{i % 3}"
            ids.append(f"d_{i}")
            docs.append(f"content {i}")
            metas.append({"wing": wing, "room": "general"})
        col.add(ids=ids, documents=docs, metadatas=metas)

        status(palace_path)
        output = capsys.readouterr().out

        assert "90 drawers" in output
        assert "WING: wing_0" in output
        assert "WING: wing_1" in output
        assert "WING: wing_2" in output
    finally:
        shutil.rmtree(tmpdir)
