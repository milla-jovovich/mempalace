import os
import tempfile
import shutil
from mempalace.convo_miner import mine_convos
from mempalace.storage import get_collection


def test_convo_mining():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "chat.txt"), "w") as f:
        f.write(
            "> What is memory?\nMemory is persistence.\n\n"
            "> Why does it matter?\nIt enables continuity.\n\n"
            "> How do we build it?\nWith structured storage.\n"
        )

    palace_path = os.path.join(tmpdir, "palace")

    # Force chromadb backend for test isolation
    old_env = os.environ.get("MEMPALACE_STORAGE_BACKEND")
    os.environ["MEMPALACE_STORAGE_BACKEND"] = "chromadb"
    try:
        mine_convos(tmpdir, palace_path, wing="test_convos")
        col = get_collection("mempalace_drawers", palace_path=palace_path)
        assert col.count() >= 2

        results = col.query(query_texts=["memory persistence"], n_results=1)
        assert len(results["documents"][0]) > 0
    finally:
        if old_env is not None:
            os.environ["MEMPALACE_STORAGE_BACKEND"] = old_env
        else:
            os.environ.pop("MEMPALACE_STORAGE_BACKEND", None)
        shutil.rmtree(tmpdir)
