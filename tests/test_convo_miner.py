import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch

import chromadb

from mempalace.convo_miner import mine_convos
from mempalace.palace import file_already_mined
from mempalace.backends.chroma import ChromaCollection


class LocalTestEmbeddingFunction:
    """Small deterministic embedding function for offline convo mining tests."""

    def __call__(self, input):
        embeddings = []
        for text in input:
            lowered = text.lower()
            embeddings.append(
                [
                    float(lowered.count("memory")),
                    float(lowered.count("persistence")),
                    float(lowered.count("continuity")),
                    float(lowered.count("structured")),
                    float(len(lowered.split())),
                    float(len(lowered)),
                ]
            )
        return embeddings


def _get_offline_collection(palace_path):
    client = chromadb.PersistentClient(path=palace_path)
    collection = client.get_or_create_collection(
        "mempalace_drawers",
        embedding_function=LocalTestEmbeddingFunction(),
    )
    return ChromaCollection(collection)


def test_convo_mining():
    tmpdir = tempfile.mkdtemp()
    try:
        with open(os.path.join(tmpdir, "chat.txt"), "w") as f:
            f.write(
                "> What is memory?\nMemory is persistence.\n\n> Why does it matter?\nIt enables continuity.\n\n> How do we build it?\nWith structured storage.\n"
            )

        palace_path = os.path.join(tmpdir, "palace")
        with patch("mempalace.convo_miner.get_collection", side_effect=_get_offline_collection):
            mine_convos(tmpdir, palace_path, wing="test_convos")

        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection(
            "mempalace_drawers",
            embedding_function=LocalTestEmbeddingFunction(),
        )
        assert col.count() >= 2

        # Verify search works without network-backed embeddings.
        results = col.query(query_texts=["memory persistence"], n_results=1)
        assert len(results["documents"][0]) > 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_mine_convos_does_not_reprocess_short_files(capsys):
    """Files below MIN_CHUNK_SIZE get a sentinel so they are skipped on re-run."""
    tmpdir = tempfile.mkdtemp()
    try:
        # A file too short to produce any chunks
        with open(os.path.join(tmpdir, "tiny.txt"), "w") as f:
            f.write("hi")

        palace_path = os.path.join(tmpdir, "palace")

        # First run -- file is processed (sentinel written)
        mine_convos(tmpdir, palace_path, wing="test")
        capsys.readouterr()  # drain output

        # Verify sentinel was written (resolve path -- macOS /var -> /private/var)
        resolved_file = str(Path(tmpdir).resolve() / "tiny.txt")
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
        assert file_already_mined(col, resolved_file)

        # Second run -- file should be skipped
        mine_convos(tmpdir, palace_path, wing="test")
        out2 = capsys.readouterr().out
        assert "Files skipped (already filed): 1" in out2
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_mine_convos_does_not_reprocess_empty_chunk_files(capsys):
    """Files that normalize but produce 0 exchange chunks get a sentinel."""
    tmpdir = tempfile.mkdtemp()
    try:
        # Content long enough to pass MIN_CHUNK_SIZE but with no exchange markers
        # (no "> " lines), so chunk_exchanges returns []
        with open(os.path.join(tmpdir, "no_exchanges.txt"), "w") as f:
            f.write("This is a plain paragraph without any exchange markers. " * 5)

        palace_path = os.path.join(tmpdir, "palace")

        mine_convos(tmpdir, palace_path, wing="test")
        mine_convos(tmpdir, palace_path, wing="test")
        out2 = capsys.readouterr().out
        assert "Files skipped (already filed): 1" in out2
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
