import os
import tempfile
import shutil
from pathlib import Path
import chromadb
from mempalace.convo_miner import mine_convos, process_convo_file_cpu


def test_process_convo_file_cpu_returns_records():
    """process_convo_file_cpu returns records without touching ChromaDB."""
    tmpdir = tempfile.mkdtemp()
    try:
        filepath = Path(tmpdir) / "chat.txt"
        filepath.write_text(
            "> What is memory?\nMemory is persistence.\n\n"
            "> Why does it matter?\nIt enables continuity.\n\n"
            "> How do we build it?\nWith structured storage.\n",
            encoding="utf-8",
        )
        result = process_convo_file_cpu(filepath, wing="testwing", agent="testbot", extract_mode="exchange")
        assert result is not None
        source_file, room, records, room_counts_delta = result
        assert source_file == str(filepath)
        assert len(records) > 0
        drawer_id, content, meta = records[0]
        assert drawer_id.startswith("drawer_testwing_")
        assert meta["wing"] == "testwing"
        assert meta["added_by"] == "testbot"
        assert meta["ingest_mode"] == "convos"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_process_convo_file_cpu_returns_none_for_empty():
    """process_convo_file_cpu returns None for empty/tiny files."""
    tmpdir = tempfile.mkdtemp()
    try:
        filepath = Path(tmpdir) / "empty.txt"
        filepath.write_text("", encoding="utf-8")
        result = process_convo_file_cpu(filepath, wing="testwing", agent="testbot", extract_mode="exchange")
        assert result is None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


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

    shutil.rmtree(tmpdir, ignore_errors=True)
