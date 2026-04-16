import sqlite3

import chromadb
import pytest

from mempalace.backends.base import GetResult, QueryResult
from mempalace.backends.chroma import ChromaBackend, ChromaCollection, _fix_blob_seq_ids


class _FakeCollection:
    """Mimics enough of a chromadb Collection for adapter tests."""

    def __init__(self):
        self.calls = []

    def add(self, **kwargs):
        self.calls.append(("add", kwargs))

    def upsert(self, **kwargs):
        self.calls.append(("upsert", kwargs))

    def update(self, **kwargs):
        self.calls.append(("update", kwargs))

    def query(self, **kwargs):
        self.calls.append(("query", kwargs))
        return {
            "ids": [["a", "b"]],
            "documents": [["doc_a", "doc_b"]],
            "metadatas": [[{"wing": "w"}, {"wing": "w"}]],
            "distances": [[0.1, 0.2]],
        }

    def get(self, **kwargs):
        self.calls.append(("get", kwargs))
        return {
            "ids": ["a"],
            "documents": ["doc_a"],
            "metadatas": [{"wing": "w"}],
        }

    def delete(self, **kwargs):
        self.calls.append(("delete", kwargs))

    def count(self):
        self.calls.append(("count", {}))
        return 7


def test_chroma_collection_forwards_writes_with_keyword_args():
    fake = _FakeCollection()
    collection = ChromaCollection(fake)

    collection.add(ids=["1"], documents=["d"], metadatas=[{"wing": "w"}])
    collection.upsert(ids=["2"], documents=["u"], metadatas=[{"room": "r"}])
    collection.update(ids=["3"], metadatas=[{"room": "r2"}])
    collection.delete(ids=["1"])
    assert collection.count() == 7

    assert fake.calls[0] == (
        "add",
        {"ids": ["1"], "documents": ["d"], "metadatas": [{"wing": "w"}]},
    )
    assert fake.calls[1] == (
        "upsert",
        {"ids": ["2"], "documents": ["u"], "metadatas": [{"room": "r"}]},
    )
    # update only forwards kwargs the caller actually supplied.
    assert fake.calls[2] == ("update", {"ids": ["3"], "metadatas": [{"room": "r2"}]})
    assert fake.calls[3] == ("delete", {"ids": ["1"]})


def test_chroma_collection_query_flattens_batch_shape():
    fake = _FakeCollection()
    collection = ChromaCollection(fake)

    result = collection.query(query_texts=["hi"], n_results=2)

    assert isinstance(result, QueryResult)
    # Chroma's batch dimension ([[...]]) is collapsed into flat lists.
    assert result.ids == ["a", "b"]
    assert result.documents == ["doc_a", "doc_b"]
    assert result.metadatas == [{"wing": "w"}, {"wing": "w"}]
    assert result.distances == [0.1, 0.2]
    # Dict-style access still works for compatibility with older helpers.
    assert result["ids"] == ["a", "b"]
    assert "distances" in result


def test_chroma_collection_get_returns_get_result():
    fake = _FakeCollection()
    collection = ChromaCollection(fake)

    result = collection.get(ids=["a"])

    assert isinstance(result, GetResult)
    assert result.ids == ["a"]
    assert result.documents == ["doc_a"]
    assert result.metadatas == [{"wing": "w"}]
    assert result["metadatas"][0]["wing"] == "w"
    # Dict-style .get falls back to the default for unknown keys only.
    assert result.get("ids") == ["a"]
    assert result.get("distances", "absent") == "absent"


def test_chroma_collection_get_omits_none_kwargs():
    fake = _FakeCollection()
    collection = ChromaCollection(fake)

    collection.get(ids=["a"])

    # include always forwards; ids/where/limit/offset only when set.
    _, forwarded = fake.calls[-1]
    assert forwarded == {"ids": ["a"], "include": ["documents", "metadatas"]}


def test_chroma_backend_create_false_raises_without_creating_directory(tmp_path):
    palace_path = tmp_path / "missing-palace"

    with pytest.raises(FileNotFoundError):
        ChromaBackend().get_collection(
            str(palace_path),
            collection_name="mempalace_drawers",
            create=False,
        )

    assert not palace_path.exists()


def test_chroma_backend_create_true_creates_directory_and_collection(tmp_path):
    palace_path = tmp_path / "palace"

    collection = ChromaBackend().get_collection(
        str(palace_path),
        collection_name="mempalace_drawers",
        create=True,
    )

    assert palace_path.is_dir()
    assert isinstance(collection, ChromaCollection)

    client = chromadb.PersistentClient(path=str(palace_path))
    client.get_collection("mempalace_drawers")


def test_chroma_backend_creates_collection_with_cosine_distance(tmp_path):
    palace_path = tmp_path / "palace"

    ChromaBackend().get_collection(
        str(palace_path),
        collection_name="mempalace_drawers",
        create=True,
    )

    client = chromadb.PersistentClient(path=str(palace_path))
    col = client.get_collection("mempalace_drawers")
    assert col.metadata.get("hnsw:space") == "cosine"


def test_fix_blob_seq_ids_converts_blobs_to_integers(tmp_path):
    """Simulate a ChromaDB 0.6.x database with BLOB seq_ids and verify repair."""
    db_path = tmp_path / "chroma.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE embeddings (rowid INTEGER PRIMARY KEY, seq_id)")
    conn.execute("CREATE TABLE max_seq_id (rowid INTEGER PRIMARY KEY, seq_id)")
    # Insert BLOB seq_ids like ChromaDB 0.6.x would
    blob_42 = (42).to_bytes(8, byteorder="big")
    blob_99 = (99).to_bytes(8, byteorder="big")
    conn.execute("INSERT INTO embeddings (seq_id) VALUES (?)", (blob_42,))
    conn.execute("INSERT INTO max_seq_id (seq_id) VALUES (?)", (blob_99,))
    conn.commit()
    conn.close()

    _fix_blob_seq_ids(str(tmp_path))

    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT seq_id, typeof(seq_id) FROM embeddings").fetchone()
    assert row == (42, "integer")
    row = conn.execute("SELECT seq_id, typeof(seq_id) FROM max_seq_id").fetchone()
    assert row == (99, "integer")
    conn.close()


def test_fix_blob_seq_ids_noop_without_blobs(tmp_path):
    """No error when seq_ids are already integers."""
    db_path = tmp_path / "chroma.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE embeddings (rowid INTEGER PRIMARY KEY, seq_id INTEGER)")
    conn.execute("INSERT INTO embeddings (seq_id) VALUES (42)")
    conn.commit()
    conn.close()

    _fix_blob_seq_ids(str(tmp_path))

    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT seq_id, typeof(seq_id) FROM embeddings").fetchone()
    assert row == (42, "integer")
    conn.close()


def test_fix_blob_seq_ids_noop_without_database(tmp_path):
    """No error when palace has no chroma.sqlite3."""
    _fix_blob_seq_ids(str(tmp_path))  # should not raise
