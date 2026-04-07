import gc
import os
import tempfile
import shutil
import yaml
import chromadb
from mempalace.miner import mine


def _force_rmtree(path):
    """Remove a temp directory, handling Windows file-lock issues from ChromaDB."""

    def _onerror(func, fpath, exc_info):
        # On Windows, ChromaDB's HNSW/SQLite files may still be locked
        # even after deleting references. Best-effort removal.
        import stat

        try:
            os.chmod(fpath, stat.S_IWRITE)
            func(fpath)
        except OSError:
            pass  # temp dir will be cleaned up by OS eventually

    shutil.rmtree(path, onerror=_onerror)


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

    # Release ChromaDB handles before cleanup (required on Windows)
    del col, client
    gc.collect()

    _force_rmtree(tmpdir)
