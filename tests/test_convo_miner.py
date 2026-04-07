import gc
import os
import tempfile
import shutil
import chromadb
from mempalace.convo_miner import mine_convos


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


def test_convo_mining():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "chat.txt"), "w") as f:
        f.write(
            "> What is memory?\nMemory is persistence.\n\n> Why does it matter?\nIt enables continuity.\n\n> How do we build it?\nWith structured storage.\n"
        )

    palace_path = os.path.join(tmpdir, "palace")
    mine_convos(tmpdir, palace_path, wing="test_convos")

    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_collection("mempalace_drawers")
    assert col.count() >= 2

    # Verify search works
    results = col.query(query_texts=["memory persistence"], n_results=1)
    assert len(results["documents"][0]) > 0

    # Release ChromaDB handles before cleanup (required on Windows)
    del col, client
    gc.collect()

    _force_rmtree(tmpdir)
