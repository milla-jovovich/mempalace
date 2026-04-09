"""test_cli.py — Tests for mempalace.cli command handlers."""

import argparse

import chromadb


def test_cmd_repair_rebuilds_with_cosine_metadata(tmp_path, capsys):
    """Issue #218: cmd_repair must recreate the drawer collection with
    hnsw:space=cosine — otherwise running `mempalace repair` silently reverts
    an already-fixed palace back to L2 distance."""
    from mempalace.cli import cmd_repair

    palace = tmp_path / "palace"
    palace.mkdir()

    # Seed a palace with one drawer on the default (L2) metric, simulating a
    # pre-#218 collection that needs repair.
    client = chromadb.PersistentClient(path=str(palace))
    old = client.create_collection("mempalace_drawers")
    old.add(ids=["d1"], documents=["hello"], metadatas=[{"wing": "w", "room": "r"}])
    del old
    del client

    cmd_repair(argparse.Namespace(palace=str(palace)))

    client = chromadb.PersistentClient(path=str(palace))
    rebuilt = client.get_collection("mempalace_drawers")
    assert rebuilt.metadata.get("hnsw:space") == "cosine"
