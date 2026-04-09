import os
import tempfile
import shutil
from pathlib import Path

from mempalace import convo_miner
from mempalace.convo_miner import mine_convos


class FakeCollection:
    def __init__(self):
        self.records = {}

    def add(self, documents, ids, metadatas):
        for doc, record_id, meta in zip(documents, ids, metadatas):
            self.records[record_id] = {
                "id": record_id,
                "document": doc,
                "metadata": dict(meta),
            }

    def get(self, where=None, limit=None, include=None):
        matches = []
        for record in self.records.values():
            if _matches_where(record["metadata"], where):
                matches.append(record)
        matches.sort(key=lambda item: item["id"])
        if limit is not None:
            matches = matches[:limit]
        return {
            "ids": [record["id"] for record in matches],
            "documents": [record["document"] for record in matches],
            "metadatas": [record["metadata"] for record in matches],
        }

    def delete(self, ids):
        for record_id in ids:
            self.records.pop(record_id, None)


def _matches_where(metadata, where):
    if not where:
        return True
    if "$and" in where:
        return all(_matches_where(metadata, clause) for clause in where["$and"])
    return all(metadata.get(key) == value for key, value in where.items())


def _patch_fake_collection(monkeypatch):
    collection = FakeCollection()
    monkeypatch.setattr(convo_miner, "get_collection", lambda palace_path: collection)
    return collection


def test_convo_mining(monkeypatch):
    collection = _patch_fake_collection(monkeypatch)
    tmpdir = tempfile.mkdtemp()
    try:
        chat_path = str((Path(tmpdir) / "chat.txt").resolve())
        with open(chat_path, "w") as f:
            f.write(
                "> What is memory?\nMemory is persistence.\n\n> Why does it matter?\nIt enables continuity.\n\n> How do we build it?\nWith structured storage.\n"
            )

        palace_path = os.path.join(tmpdir, "palace")
        mine_convos(tmpdir, palace_path, wing="test_convos")

        results = collection.get(where={"source_file": chat_path})
        assert len(results["documents"]) >= 2
        assert any("Memory is persistence." in doc for doc in results["documents"])
    finally:
        shutil.rmtree(tmpdir)


def _drawer_ids_for_source(collection, source_file: str):
    results = collection.get(where={"source_file": source_file})
    return results["ids"]


def test_convo_mining_reingests_when_source_file_changes(monkeypatch):
    collection = _patch_fake_collection(monkeypatch)
    tmpdir = tempfile.mkdtemp()
    try:
        chat_path = str((Path(tmpdir) / "chat.txt").resolve())
        with open(chat_path, "w") as f:
            f.write(
                "> What is memory?\nMemory is persistence.\n\n"
                "> Why does it matter?\nIt enables continuity.\n"
            )

        palace_path = os.path.join(tmpdir, "palace")
        mine_convos(tmpdir, palace_path, wing="test_convos")

        assert len(_drawer_ids_for_source(collection, chat_path)) == 2

        with open(chat_path, "w") as f:
            f.write(
                "> What is memory?\nMemory is persistence.\n\n"
                "> Why does it matter?\nIt enables continuity.\n\n"
                "> How do we build it?\nWith structured storage.\n"
            )
        current_mtime = os.path.getmtime(chat_path)
        os.utime(chat_path, (current_mtime + 10, current_mtime + 10))

        mine_convos(tmpdir, palace_path, wing="test_convos")

        ids = _drawer_ids_for_source(collection, chat_path)
        assert len(ids) == 3
        results = collection.get(where={"source_file": chat_path}, include=["documents"])
        assert any("How do we build it?" in doc for doc in results["documents"])
    finally:
        shutil.rmtree(tmpdir)


def test_convo_mining_removes_stale_drawers_when_file_shrinks(monkeypatch):
    collection = _patch_fake_collection(monkeypatch)
    tmpdir = tempfile.mkdtemp()
    try:
        chat_path = str((Path(tmpdir) / "chat.txt").resolve())
        with open(chat_path, "w") as f:
            f.write(
                "> One?\nFirst reply with enough detail to pass chunk size checks.\n\n"
                "> Two?\nSecond reply with enough detail to pass chunk size checks.\n\n"
                "> Three?\nThird reply with enough detail to pass chunk size checks.\n"
            )

        palace_path = os.path.join(tmpdir, "palace")
        mine_convos(tmpdir, palace_path, wing="test_convos")

        assert len(_drawer_ids_for_source(collection, chat_path)) == 3

        with open(chat_path, "w") as f:
            f.write("> One?\nFirst reply with enough detail to pass chunk size checks.\n")
        current_mtime = os.path.getmtime(chat_path)
        os.utime(chat_path, (current_mtime + 10, current_mtime + 10))

        mine_convos(tmpdir, palace_path, wing="test_convos")

        ids = _drawer_ids_for_source(collection, chat_path)
        assert len(ids) == 1
    finally:
        shutil.rmtree(tmpdir)
