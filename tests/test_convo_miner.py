import os
import tempfile
import shutil
from types import SimpleNamespace

import chromadb
import pytest

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

    # Verify search works
    results = col.query(query_texts=["memory persistence"], n_results=1)
    assert len(results["documents"][0]) > 0

    shutil.rmtree(tmpdir, ignore_errors=True)


def test_convo_mining_uses_configured_collection(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    try:
        with open(os.path.join(tmpdir, "chat.txt"), "w") as f:
            f.write(
                "> What changed?\nWe switched collections.\n\n> Why?\nTo honor config consistently.\n"
            )

        palace_path = os.path.join(tmpdir, "palace")
        monkeypatch.setattr(
            "mempalace.palace.MempalaceConfig",
            lambda: SimpleNamespace(
                palace_path=palace_path,
                collection_name="custom_drawers",
            ),
        )

        mine_convos(tmpdir, palace_path, wing="test_convos")

        client = chromadb.PersistentClient(path=palace_path)
        assert client.get_collection("custom_drawers").count() >= 1
        with pytest.raises(chromadb.errors.NotFoundError):
            client.get_collection("mempalace_drawers")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
