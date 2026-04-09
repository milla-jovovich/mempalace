import gc
import os
import sys
import tempfile
import shutil
import chromadb
from mempalace.convo_miner import mine_convos


def _force_cleanup(path):
    """Best-effort temp dir removal; ChromaDB may hold file locks on Windows."""
    try:
        shutil.rmtree(path)
    except PermissionError:
        if sys.platform == "win32":
            import time

            gc.collect()
            time.sleep(0.5)
            shutil.rmtree(path, ignore_errors=True)
        else:
            raise


def test_convo_mining():
    tmpdir = tempfile.mkdtemp()
    try:
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

        del col, client
        gc.collect()
    finally:
        _force_cleanup(tmpdir)
