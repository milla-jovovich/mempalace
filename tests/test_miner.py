import os
import tempfile
import shutil
import yaml
import chromadb
from mempalace.miner import mine


def test_project_mining():
    tmpdir = tempfile.mkdtemp()
    # Create a mini project
    os.makedirs(os.path.join(tmpdir, "backend"))
    with open(os.path.join(tmpdir, "backend", "app.py"), "w") as f:
        f.write("def main():\n    print('hello world')\n" * 20)
    with open(os.path.join(tmpdir, "backend", "index.php"), "w") as f:
        f.write("<?php\nfunction hello() {\n    echo 'hello world';\n}\n" * 20)
    # Create config
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
    mine(tmpdir, palace_path)

    # Verify
    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_collection("mempalace_drawers")
    assert col.count() > 0

    shutil.rmtree(tmpdir)
