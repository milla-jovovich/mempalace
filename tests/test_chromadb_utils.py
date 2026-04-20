"""Tests for chromadb_utils.get_all — batched reads from ChromaDB."""

import shutil
import tempfile

import chromadb

from mempalace.chromadb_utils import get_all


def _create_palace(n_drawers, n_wings=1):
    """Create a temp palace with *n_drawers* spread across *n_wings* wings.

    Returns (palace_path, collection).
    """
    palace_path = tempfile.mkdtemp()
    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_or_create_collection("mempalace_drawers")

    wing_names = [f"wing_{i}" for i in range(n_wings)]
    room_names = ["src", "docs", "tests"]

    ids = []
    docs = []
    metas = []
    for i in range(n_drawers):
        ids.append(f"drawer_{i}")
        docs.append(f"content for drawer {i}")
        metas.append(
            {
                "wing": wing_names[i % n_wings],
                "room": room_names[i % len(room_names)],
                "source_file": f"file_{i}.py",
            }
        )

    # ChromaDB add has its own batch limits, so insert in chunks
    batch_size = 5000
    for start in range(0, len(ids), batch_size):
        end = start + batch_size
        col.add(
            ids=ids[start:end],
            documents=docs[start:end],
            metadatas=metas[start:end],
        )

    return palace_path, col


def test_get_all_returns_all_metadata():
    """get_all must return every drawer's metadata, not just a default subset."""
    palace_path, col = _create_palace(50)
    try:
        results = get_all(col, include=["metadatas"])
        assert len(results["ids"]) == 50
        assert len(results["metadatas"]) == 50
    finally:
        shutil.rmtree(palace_path)


def test_get_all_returns_documents_and_metadatas():
    """get_all should return multiple include fields correctly."""
    palace_path, col = _create_palace(20)
    try:
        results = get_all(col, include=["documents", "metadatas"])
        assert len(results["ids"]) == 20
        assert len(results["documents"]) == 20
        assert len(results["metadatas"]) == 20
        assert "content for drawer 0" in results["documents"][0]
    finally:
        shutil.rmtree(palace_path)


def test_get_all_with_where_filter():
    """get_all should respect where filters and only return matching drawers."""
    palace_path, col = _create_palace(30, n_wings=3)
    try:
        results = get_all(col, include=["metadatas"], where={"wing": "wing_0"})
        assert len(results["ids"]) == 10
        for m in results["metadatas"]:
            assert m["wing"] == "wing_0"
    finally:
        shutil.rmtree(palace_path)


def test_get_all_on_empty_collection():
    """get_all on an empty collection should return empty lists, not error."""
    palace_path = tempfile.mkdtemp()
    try:
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_or_create_collection("mempalace_drawers")
        results = get_all(col, include=["metadatas"])
        assert results["ids"] == []
        assert results["metadatas"] == []
    finally:
        shutil.rmtree(palace_path)


def test_get_all_batches_large_collections():
    """get_all with a small batch_size must still return all drawers."""
    palace_path, col = _create_palace(100)
    try:
        # Force tiny batches to exercise the pagination loop
        results = get_all(col, include=["metadatas"], batch_size=7)
        assert len(results["ids"]) == 100
        assert len(results["metadatas"]) == 100
    finally:
        shutil.rmtree(palace_path)


def test_get_all_no_duplicate_ids():
    """Batched reads must not produce duplicate drawer IDs."""
    palace_path, col = _create_palace(50)
    try:
        results = get_all(col, include=["metadatas"], batch_size=13)
        assert len(results["ids"]) == len(set(results["ids"]))
    finally:
        shutil.rmtree(palace_path)


def test_get_all_filtered_pagination():
    """get_all with a where filter and small batch_size must return all matching drawers."""
    palace_path, col = _create_palace(60, n_wings=3)
    try:
        # 60 drawers across 3 wings → 20 per wing; batch_size=7 forces multiple pages
        results = get_all(col, include=["metadatas"], where={"wing": "wing_0"}, batch_size=7)
        assert len(results["ids"]) == 20
        for m in results["metadatas"]:
            assert m["wing"] == "wing_0"
        assert len(results["ids"]) == len(set(results["ids"]))
    finally:
        shutil.rmtree(palace_path)
