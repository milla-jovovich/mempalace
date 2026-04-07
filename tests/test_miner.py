import json
import os
import tempfile
import shutil
import yaml
from mempalace.miner import mine
from mempalace.storage import get_collection


def test_project_mining():
    tmpdir = tempfile.mkdtemp()
    os.makedirs(os.path.join(tmpdir, "backend"))
    with open(os.path.join(tmpdir, "backend", "app.py"), "w") as f:
        f.write("def main():\n    print('hello world')\n" * 20)
    with open(os.path.join(tmpdir, "mempalace.yaml"), "w") as f:
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

    palace_path = os.path.join(tmpdir, "palace")

    # Force chromadb backend for test isolation
    old_env = os.environ.get("MEMPALACE_STORAGE_BACKEND")
    os.environ["MEMPALACE_STORAGE_BACKEND"] = "chromadb"
    try:
        mine(tmpdir, palace_path)
        col = get_collection("mempalace_drawers", palace_path=palace_path)
        assert col.count() > 0
    finally:
        if old_env is not None:
            os.environ["MEMPALACE_STORAGE_BACKEND"] = old_env
        else:
            os.environ.pop("MEMPALACE_STORAGE_BACKEND", None)
        shutil.rmtree(tmpdir)
