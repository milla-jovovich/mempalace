import os
import tempfile
import shutil
import chromadb
from mempalace.convo_miner import get_collection, mine_convos


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

    shutil.rmtree(tmpdir)


def test_get_collection_uses_cosine_distance(tmp_path):
    """Newly-created drawer collections must declare hnsw:space=cosine so that
    searcher.py's `similarity = 1 - distance` formula yields scores in [0, 1]
    instead of negative L2 distances. Regression test for issue #218."""
    col = get_collection(str(tmp_path / "palace"))
    assert col.metadata.get("hnsw:space") == "cosine"
