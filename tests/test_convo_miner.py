import os
import tempfile
import shutil
import chromadb
from mempalace.convo_miner import mine_convos


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

    stored = col.get(include=["metadatas", "documents"], limit=1)
    meta = stored["metadatas"][0]
    assert meta["wing"] == "test_convos"
    assert meta["source_type"] == "conversation_file"
    assert meta["memory_type"] == "conversation_exchange"
    assert meta["hall"] == "hall_conversation"
    assert meta["importance"] == 3
    assert meta["confidence"] == 1.0
    assert meta["closet_id"].startswith("closet_test_convos_")
    assert meta["source_group_id"].startswith("conversation_file_")
    assert meta["content_hash"]
    assert meta["source_updated_at"]
    assert meta["source_file"].endswith("chat.txt")
    assert meta["extract_mode"] == "exchange"
    assert meta["ingest_mode"] == "convos"

    # Verify search works
    results = col.query(query_texts=["memory persistence"], n_results=1)
    assert len(results["documents"][0]) > 0

    shutil.rmtree(tmpdir, ignore_errors=True)
