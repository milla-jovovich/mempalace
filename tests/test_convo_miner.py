import os
import tempfile
import shutil
import chromadb
from mempalace.convo_miner import mine_convos, scan_convos


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


def test_scan_convos_skips_tool_results_and_meta():
    """tool-results/ and *.meta.json should not be mined as conversations (#111)."""
    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmp, "session", "sub"))
        good = os.path.join(tmp, "session", "sub", "chat.txt")
        with open(good, "w") as f:
            f.write("hello")
        os.makedirs(os.path.join(tmp, "tool-results"))
        with open(os.path.join(tmp, "tool-results", "huge.txt"), "w") as f:
            f.write("noise")
        with open(os.path.join(tmp, "noise.meta.json"), "w") as f:
            f.write("{}")
        files = scan_convos(tmp)
        assert len(files) == 1
        assert files[0].name == "chat.txt"
    finally:
        shutil.rmtree(tmp)
