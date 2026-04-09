import os
import shutil
import tempfile
from pathlib import Path

import chromadb
import yaml

from mempalace.miner import mine, scan_project


def write_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def scanned_files(project_root: Path, **kwargs):
    files = scan_project(str(project_root), **kwargs)
    return sorted(path.relative_to(project_root).as_posix() for path in files)


def test_project_mining():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        os.makedirs(project_root / "backend")

        write_file(
            project_root / "backend" / "app.py", "def main():\n    print('hello world')\n" * 20
        )
        with open(project_root / "mempalace.yaml", "w") as f:
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

        palace_path = project_root / "palace"
        mine(str(project_root), str(palace_path))

        client = chromadb.PersistentClient(path=str(palace_path))
        col = client.get_collection("mempalace_drawers")
        assert col.count() > 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_scan_project_respects_gitignore():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "ignored.py\ngenerated/\n")
        write_file(project_root / "src" / "app.py", "print('hello')\n" * 20)
        write_file(project_root / "ignored.py", "print('ignore me')\n" * 20)
        write_file(project_root / "generated" / "artifact.py", "print('artifact')\n" * 20)

        assert scanned_files(project_root) == ["src/app.py"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_respects_nested_gitignore():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "*.log\n")
        write_file(project_root / "subrepo" / ".gitignore", "tasks/\n")
        write_file(project_root / "subrepo" / "src" / "main.py", "print('main')\n" * 20)
        write_file(project_root / "subrepo" / "tasks" / "task.py", "print('task')\n" * 20)
        write_file(project_root / "subrepo" / "debug.log", "debug\n" * 20)

        assert scanned_files(project_root) == ["subrepo/src/main.py"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_allows_nested_gitignore_override():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "*.csv\n")
        write_file(project_root / "subrepo" / ".gitignore", "!keep.csv\n")
        write_file(project_root / "drop.csv", "a,b,c\n" * 20)
        write_file(project_root / "subrepo" / "keep.csv", "a,b,c\n" * 20)

        assert scanned_files(project_root) == ["subrepo/keep.csv"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_allows_gitignore_negation_when_parent_dir_is_visible():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "generated/*\n!generated/keep.py\n")
        write_file(project_root / "generated" / "drop.py", "print('drop')\n" * 20)
        write_file(project_root / "generated" / "keep.py", "print('keep')\n" * 20)

        assert scanned_files(project_root) == ["generated/keep.py"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_does_not_reinclude_file_from_ignored_directory():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "generated/\n!generated/keep.py\n")
        write_file(project_root / "generated" / "drop.py", "print('drop')\n" * 20)
        write_file(project_root / "generated" / "keep.py", "print('keep')\n" * 20)

        assert scanned_files(project_root) == []
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_can_disable_gitignore():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "data/\n")
        write_file(project_root / "data" / "stuff.csv", "a,b,c\n" * 20)

        assert scanned_files(project_root, respect_gitignore=False) == ["data/stuff.csv"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_can_include_ignored_directory():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "docs/\n")
        write_file(project_root / "docs" / "guide.md", "# Guide\n" * 20)

        assert scanned_files(project_root, include_ignored=["docs"]) == ["docs/guide.md"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_can_include_specific_ignored_file():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "generated/\n")
        write_file(project_root / "generated" / "drop.py", "print('drop')\n" * 20)
        write_file(project_root / "generated" / "keep.py", "print('keep')\n" * 20)

        assert scanned_files(project_root, include_ignored=["generated/keep.py"]) == [
            "generated/keep.py"
        ]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_can_include_exact_file_without_known_extension():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "README\n")
        write_file(project_root / "README", "hello\n" * 20)

        assert scanned_files(project_root, include_ignored=["README"]) == ["README"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_include_override_beats_skip_dirs():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".pytest_cache" / "cache.py", "print('cache')\n" * 20)

        assert scanned_files(
            project_root,
            respect_gitignore=False,
            include_ignored=[".pytest_cache"],
        ) == [".pytest_cache/cache.py"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_skip_dirs_still_apply_without_override():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".pytest_cache" / "cache.py", "print('cache')\n" * 20)
        write_file(project_root / "main.py", "print('main')\n" * 20)

        assert scanned_files(project_root, respect_gitignore=False) == ["main.py"]
    finally:
        shutil.rmtree(tmpdir)


def test_sync_detects_changes():
    """Test that sync finds new, changed, and deleted files."""
    import time

    from mempalace.miner import sync, get_collection

    tmpdir = tempfile.mkdtemp()
    try:
        with open(os.path.join(tmpdir, "file1.py"), "w") as f:
            f.write("# File 1\n" + "x = 1\n" * 20)
        with open(os.path.join(tmpdir, "file2.py"), "w") as f:
            f.write("# File 2\n" + "y = 2\n" * 20)
        with open(os.path.join(tmpdir, "mempalace.yaml"), "w") as f:
            yaml.dump({"wing": "test", "rooms": [{"name": "general", "description": "all"}]}, f)

        palace = tempfile.mkdtemp()
        mine(tmpdir, palace)

        col = get_collection(palace)
        initial_count = col.count()
        assert initial_count > 0

        # Ensure mtime changes are detectable
        time.sleep(0.1)

        # Modify file1, delete file2, add file3
        with open(os.path.join(tmpdir, "file1.py"), "w") as f:
            f.write("# File 1 MODIFIED\n" + "x = 999\n" * 20)
        os.remove(os.path.join(tmpdir, "file2.py"))
        with open(os.path.join(tmpdir, "file3.py"), "w") as f:
            f.write("# File 3 NEW\n" + "z = 3\n" * 20)

        sync(tmpdir, palace)

        # Verify
        results = col.get(include=["metadatas"], limit=10000)
        source_files = {m["source_file"] for m in results["metadatas"]}
        assert os.path.join(tmpdir, "file2.py") not in source_files
        assert os.path.join(tmpdir, "file3.py") in source_files
        assert os.path.join(tmpdir, "file1.py") in source_files
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_sync_dry_run_does_not_modify():
    """Verify --dry-run reports changes but doesn't touch the collection."""
    import time

    from mempalace.miner import sync, get_collection

    tmpdir = tempfile.mkdtemp()
    try:
        with open(os.path.join(tmpdir, "file1.py"), "w") as f:
            f.write("# File 1\n" + "x = 1\n" * 20)
        with open(os.path.join(tmpdir, "mempalace.yaml"), "w") as f:
            yaml.dump({"wing": "test", "rooms": [{"name": "general", "description": "all"}]}, f)

        palace = tempfile.mkdtemp()
        mine(tmpdir, palace)

        col = get_collection(palace)
        count_before = col.count()

        time.sleep(0.1)

        # Modify the file and add a new one
        with open(os.path.join(tmpdir, "file1.py"), "w") as f:
            f.write("# MODIFIED\n" + "x = 999\n" * 20)
        with open(os.path.join(tmpdir, "file2.py"), "w") as f:
            f.write("# NEW\n" + "y = 2\n" * 20)

        sync(tmpdir, palace, dry_run=True)

        # Collection must be unchanged after dry-run
        assert col.count() == count_before
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_sync_deletion_only():
    """Test sync when only files are deleted (no new or changed)."""
    from mempalace.miner import sync, get_collection

    tmpdir = tempfile.mkdtemp()
    try:
        with open(os.path.join(tmpdir, "file1.py"), "w") as f:
            f.write("# File 1\n" + "x = 1\n" * 20)
        with open(os.path.join(tmpdir, "file2.py"), "w") as f:
            f.write("# File 2\n" + "y = 2\n" * 20)
        with open(os.path.join(tmpdir, "mempalace.yaml"), "w") as f:
            yaml.dump({"wing": "test", "rooms": [{"name": "general", "description": "all"}]}, f)

        palace = tempfile.mkdtemp()
        mine(tmpdir, palace)

        col = get_collection(palace)
        assert col.count() > 0

        # Delete both files
        os.remove(os.path.join(tmpdir, "file1.py"))
        os.remove(os.path.join(tmpdir, "file2.py"))

        sync(tmpdir, palace)

        # All drawers should be gone
        assert col.count() == 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_sync_on_empty_palace():
    """Test sync before any mine — should treat all files as new."""
    from mempalace.miner import sync, get_collection

    tmpdir = tempfile.mkdtemp()
    try:
        with open(os.path.join(tmpdir, "file1.py"), "w") as f:
            f.write("# File 1\n" + "x = 1\n" * 20)
        with open(os.path.join(tmpdir, "mempalace.yaml"), "w") as f:
            yaml.dump({"wing": "test", "rooms": [{"name": "general", "description": "all"}]}, f)

        palace = tempfile.mkdtemp()

        # sync without prior mine
        sync(tmpdir, palace)

        col = get_collection(palace)
        assert col.count() > 0

        results = col.get(include=["metadatas"], limit=10000)
        source_files = {m["source_file"] for m in results["metadatas"]}
        assert os.path.join(tmpdir, "file1.py") in source_files
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
