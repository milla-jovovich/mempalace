import os
import tempfile
import shutil
from pathlib import Path
import sys
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parent.parent))

# Mock chromadb before importing miner
sys.modules["chromadb"] = Mock()
import chromadb

from mempalace.miner import scan_project


def test_scan_project_excludes_build_artifacts():
    tmpdir = tempfile.mkdtemp()

    os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
    with open(os.path.join(tmpdir, "src", "main.py"), "w") as f:
        f.write("print('hello')")

    os.makedirs(os.path.join(tmpdir, "target"), exist_ok=True)
    with open(os.path.join(tmpdir, "target", "binary.exe"), "w") as f:
        f.write("binary content")

    os.makedirs(os.path.join(tmpdir, "dist"), exist_ok=True)
    with open(os.path.join(tmpdir, "dist", "bundle.js"), "w") as f:
        f.write("minified content")

    os.makedirs(os.path.join(tmpdir, "build"), exist_ok=True)
    with open(os.path.join(tmpdir, "build", "output.log"), "w") as f:
        f.write("log content")

    os.makedirs(os.path.join(tmpdir, "tmp"), exist_ok=True)
    with open(os.path.join(tmpdir, "tmp", "temp.txt"), "w") as f:
        f.write("temp content")

    with open(os.path.join(tmpdir, "package-lock.json"), "w") as f:
        f.write("{}")
    with open(os.path.join(tmpdir, "Cargo.lock"), "w") as f:
        f.write("lock content")

    files = scan_project(tmpdir)
    file_names = [f.name for f in files]

    assert "main.py" in file_names

    assert "binary.exe" not in file_names
    assert "bundle.js" not in file_names
    assert "output.log" not in file_names
    assert "temp.txt" not in file_names

    assert "package-lock.json" not in file_names
    assert "Cargo.lock" not in file_names

    shutil.rmtree(tmpdir)


def test_scan_project_excludes_generated_file_patterns():
    tmpdir = tempfile.mkdtemp()

    with open(os.path.join(tmpdir, "app.min.js"), "w") as f:
        f.write("minified js")
    with open(os.path.join(tmpdir, "style.min.css"), "w") as f:
        f.write("minified css")
    with open(os.path.join(tmpdir, "bundle.bundle.js"), "w") as f:
        f.write("bundle js")

    with open(os.path.join(tmpdir, "normal.js"), "w") as f:
        f.write("normal source")

    files = scan_project(tmpdir)
    file_names = [f.name for f in files]

    assert "app.min.js" not in file_names
    assert "style.min.css" not in file_names
    assert "bundle.bundle.js" not in file_names

    assert "normal.js" in file_names

    shutil.rmtree(tmpdir)
