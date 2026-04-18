import sqlite3

import chromadb
import pytest

from mempalace.backends.chroma import ChromaBackend, ChromaCollection, _fix_blob_seq_ids
from mempalace.embedding import DEFAULT_MODEL, get_embedding_function


class _FakeCollection:
    def __init__(self):
        self.calls = []

    def add(self, **kwargs):
        self.calls.append(("add", kwargs))

    def upsert(self, **kwargs):
        self.calls.append(("upsert", kwargs))

    def query(self, **kwargs):
        self.calls.append(("query", kwargs))
        return {"kind": "query"}

    def get(self, **kwargs):
        self.calls.append(("get", kwargs))
        return {"kind": "get"}

    def delete(self, **kwargs):
        self.calls.append(("delete", kwargs))

    def count(self):
        self.calls.append(("count", {}))
        return 7


def test_chroma_collection_delegates_methods():
    fake = _FakeCollection()
    collection = ChromaCollection(fake)

    collection.add(documents=["d"], ids=["1"], metadatas=[{"wing": "w"}])
    collection.upsert(documents=["u"], ids=["2"], metadatas=[{"room": "r"}])
    assert collection.query(query_texts=["q"]) == {"kind": "query"}
    assert collection.get(where={"wing": "w"}) == {"kind": "get"}
    collection.delete(ids=["1"])
    assert collection.count() == 7

    assert fake.calls == [
        ("add", {"documents": ["d"], "ids": ["1"], "metadatas": [{"wing": "w"}]}),
        ("upsert", {"documents": ["u"], "ids": ["2"], "metadatas": [{"room": "r"}]}),
        ("query", {"query_texts": ["q"]}),
        ("get", {"where": {"wing": "w"}}),
        ("delete", {"ids": ["1"]}),
        ("count", {}),
    ]


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


def test_chroma_backend_stamps_embedding_model_on_create(tmp_path):
    palace_path = tmp_path / "palace"
    ef = get_embedding_function(DEFAULT_MODEL)

    ChromaBackend().get_collection(
        str(palace_path),
        collection_name="mempalace_drawers",
        create=True,
        embedding_function=ef,
        embedding_model_name=DEFAULT_MODEL,
    )

    # Verify model name was stamped in collection metadata
    client = chromadb.PersistentClient(path=str(palace_path))
    col = client.get_collection("mempalace_drawers")
    assert col.metadata.get("embedding_model") == DEFAULT_MODEL


def test_chroma_backend_passes_embedding_function_on_get(tmp_path):
    palace_path = tmp_path / "palace"
    ef = get_embedding_function(DEFAULT_MODEL)

    # Create first
    ChromaBackend().get_collection(
        str(palace_path),
        collection_name="mempalace_drawers",
        create=True,
        embedding_function=ef,
        embedding_model_name=DEFAULT_MODEL,
    )

    # Get with embedding function — should not raise
    col = ChromaBackend().get_collection(
        str(palace_path),
        collection_name="mempalace_drawers",
        create=False,
        embedding_function=ef,
    )
    assert col.count() == 0


def test_chroma_backend_works_without_embedding_function(tmp_path):
    """Backwards compatibility — no embedding_function still works."""
    palace_path = tmp_path / "palace"

    col = ChromaBackend().get_collection(
        str(palace_path),
        collection_name="mempalace_drawers",
        create=True,
    )
    assert col.count() == 0
