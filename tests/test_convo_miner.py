import os
import tempfile
import shutil
import chromadb
from mempalace.convo_miner import mine_convos


def _close_client(client):
    """Close Chroma clients across versions."""
    close = getattr(client, "close", None)
    if callable(close):
        close()
        return

    system = getattr(client, "_system", None)
    stop = getattr(system, "stop", None)
    if callable(stop):
        stop()


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
        try:
            col = client.get_collection("mempalace_drawers")
            count = col.count()
            results = col.query(query_texts=["memory persistence"], n_results=1)
            docs = results["documents"][0]
        finally:
            _close_client(client)  # release file handles before cleanup (required on Windows)

        assert count >= 2

        # Verify search works
        assert len(docs) > 0
    finally:
        shutil.rmtree(tmpdir)
