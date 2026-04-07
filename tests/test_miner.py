import os
import tempfile
import shutil
import yaml
import chromadb
from mempalace.miner import mine, scan_project


def test_project_mining():
    tmpdir = tempfile.mkdtemp()
    # Create a mini project
    os.makedirs(os.path.join(tmpdir, "backend"))
    with open(os.path.join(tmpdir, "backend", "app.py"), "w") as f:
        f.write("def main():\n    print('hello world')\n" * 20)
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


def test_scan_respects_gitignore():
    """Files and dirs matching .gitignore patterns are excluded."""
    tmpdir = tempfile.mkdtemp()

    os.makedirs(os.path.join(tmpdir, "src"))
    os.makedirs(os.path.join(tmpdir, "data"))
    os.makedirs(os.path.join(tmpdir, "build_output"))

    with open(os.path.join(tmpdir, ".gitignore"), "w") as f:
        f.write("data/\nbuild_output/\n")

    with open(os.path.join(tmpdir, "src", "app.py"), "w") as f:
        f.write("print('hello')\n")
    with open(os.path.join(tmpdir, "data", "big.csv"), "w") as f:
        f.write("a,b,c\n1,2,3\n")
    with open(os.path.join(tmpdir, "build_output", "bundle.js"), "w") as f:
        f.write("console.log('built')\n")

    files = scan_project(tmpdir)
    filenames = {f.name for f in files}

    assert "app.py" in filenames
    assert "big.csv" not in filenames
    assert "bundle.js" not in filenames

    shutil.rmtree(tmpdir)


def test_scan_no_gitignore_flag():
    """With respect_gitignore=False, gitignored files ARE included."""
    tmpdir = tempfile.mkdtemp()

    os.makedirs(os.path.join(tmpdir, "data"))
    with open(os.path.join(tmpdir, ".gitignore"), "w") as f:
        f.write("data/\n")
    with open(os.path.join(tmpdir, "data", "stuff.csv"), "w") as f:
        f.write("a,b,c\n")

    files = scan_project(tmpdir, respect_gitignore=False)
    filenames = {f.name for f in files}
    assert "stuff.csv" in filenames

    shutil.rmtree(tmpdir)


def test_scan_nested_gitignore():
    """Nested .gitignore files are honored additively."""
    tmpdir = tempfile.mkdtemp()

    # Root-level gitignore: ignore all .log files
    with open(os.path.join(tmpdir, ".gitignore"), "w") as f:
        f.write("*.log\n")

    # Subrepo with its own gitignore
    subrepo = os.path.join(tmpdir, "subrepo")
    os.makedirs(os.path.join(subrepo, "src"))
    os.makedirs(os.path.join(subrepo, "tasks"))
    with open(os.path.join(subrepo, ".gitignore"), "w") as f:
        f.write("tasks/\n")

    with open(os.path.join(subrepo, "src", "main.py"), "w") as f:
        f.write("print('main')\n")
    with open(os.path.join(subrepo, "tasks", "script.py"), "w") as f:
        f.write("print('task')\n")
    with open(os.path.join(subrepo, "debug.log"), "w") as f:
        f.write("log content here\n")

    files = scan_project(tmpdir)
    filenames = {f.name for f in files}

    assert "main.py" in filenames
    assert "script.py" not in filenames  # tasks/ gitignored by subrepo
    assert "debug.log" not in filenames  # *.log gitignored by root

    shutil.rmtree(tmpdir)


def test_scan_no_gitignore_file():
    """When no .gitignore exists, behavior is unchanged."""
    tmpdir = tempfile.mkdtemp()

    os.makedirs(os.path.join(tmpdir, "src"))
    with open(os.path.join(tmpdir, "src", "app.py"), "w") as f:
        f.write("print('hello')\n")

    files = scan_project(tmpdir)
    filenames = {f.name for f in files}
    assert "app.py" in filenames

    shutil.rmtree(tmpdir)


def test_scan_skip_dirs_still_apply():
    """SKIP_DIRS are respected even with .gitignore support."""
    tmpdir = tempfile.mkdtemp()

    os.makedirs(os.path.join(tmpdir, ".mempalace"))
    with open(os.path.join(tmpdir, ".mempalace", "notes.txt"), "w") as f:
        f.write("palace notes here\n")
    with open(os.path.join(tmpdir, "readme.txt"), "w") as f:
        f.write("project readme\n")

    files = scan_project(tmpdir)
    filenames = {f.name for f in files}

    assert "readme.txt" in filenames
    assert "notes.txt" not in filenames

    shutil.rmtree(tmpdir)


def test_scan_wildcard_patterns():
    """Wildcard patterns in .gitignore are matched."""
    tmpdir = tempfile.mkdtemp()

    with open(os.path.join(tmpdir, ".gitignore"), "w") as f:
        f.write("test_*.py\n")

    with open(os.path.join(tmpdir, "app.py"), "w") as f:
        f.write("print('app')\n")
    with open(os.path.join(tmpdir, "test_app.py"), "w") as f:
        f.write("print('test')\n")

    files = scan_project(tmpdir)
    filenames = {f.name for f in files}

    assert "app.py" in filenames
    assert "test_app.py" not in filenames

    shutil.rmtree(tmpdir)
