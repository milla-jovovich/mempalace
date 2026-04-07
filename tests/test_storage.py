import json
import os
import tempfile
from pathlib import Path

import yaml

from mempalace.layers import Layer3
from mempalace.miner import mine
from mempalace.searcher import search_memories
from mempalace.storage import build_where, get_collection


def test_build_where_variants():
    assert build_where() is None
    assert build_where(wing="alpha") == {"wing": "alpha"}
    assert build_where(room="backend") == {"room": "backend"}
    assert build_where(wing="alpha", room="backend") == {
        "$and": [{"wing": "alpha"}, {"room": "backend"}]
    }


def test_configured_collection_name_is_used_across_mine_and_search(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    home = os.path.join(tmpdir, "home")
    os.makedirs(os.path.join(home, ".mempalace"), exist_ok=True)

    config = {
        "palace_path": os.path.join(tmpdir, "palace-from-config"),
        "collection_name": "custom_drawers",
    }
    with open(os.path.join(home, ".mempalace", "config.json"), "w") as f:
        json.dump(config, f)

    monkeypatch.setenv("HOME", home)

    project_dir = os.path.join(tmpdir, "project")
    os.makedirs(os.path.join(project_dir, "backend"), exist_ok=True)
    with open(os.path.join(project_dir, "backend", "app.py"), "w") as f:
        f.write("def main():\n    return 'memory palace'\n" * 20)
    with open(os.path.join(project_dir, "mempalace.yaml"), "w") as f:
        yaml.dump(
            {
                "wing": "test_project",
                "rooms": [
                    {"name": "backend", "description": "Backend code"},
                    {"name": "general", "description": "General"},
                ],
            },
            f,
        )

    palace_path = os.path.join(tmpdir, "custom-palace")
    mine(project_dir, palace_path)

    custom_collection = get_collection(palace_path=palace_path)
    assert custom_collection.count() > 0

    results = search_memories("memory palace", palace_path=palace_path)
    assert results["results"]

    layer_results = Layer3(palace_path=palace_path).search_raw("memory palace")
    assert layer_results
    assert layer_results[0]["source_file"] == Path(results["results"][0]["source_file"]).name
