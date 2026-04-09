import tempfile
import chromadb


def test_detect_device_cpu():
    from mempalace.embeddings import _detect_device
    assert _detect_device("cpu") == "cpu"


def test_detect_device_auto():
    from mempalace.embeddings import _detect_device
    device = _detect_device("auto")
    assert device in ("cpu", "cuda")


def test_get_embedding_function_no_crash():
    from mempalace.embeddings import get_embedding_function
    ef = get_embedding_function("cpu")
    # Returns SentenceTransformerEmbeddingFunction or None


def test_get_collection_roundtrip():
    from mempalace.embeddings import get_collection
    tmpdir = tempfile.mkdtemp()
    client = chromadb.PersistentClient(path=tmpdir)
    col = get_collection(client, "test_col", create=True, device="cpu")
    col.add(ids=["t1"], documents=["test document about cats"])
    assert col.count() == 1
    results = col.query(query_texts=["feline"], n_results=1)
    assert len(results["documents"][0]) == 1


def test_flush_batch():
    from mempalace.embeddings import get_collection, flush_batch
    tmpdir = tempfile.mkdtemp()
    client = chromadb.PersistentClient(path=tmpdir)
    col = get_collection(client, "test_col", create=True, device="cpu")
    batch = [
        {"id": f"d{i}", "document": f"doc number {i} content", "metadata": {"wing": "test", "room": "general"}}
        for i in range(10)
    ]
    added = flush_batch(col, batch)
    assert added == 10
    assert col.count() == 10


def test_flush_batch_handles_duplicates():
    from mempalace.embeddings import get_collection, flush_batch
    tmpdir = tempfile.mkdtemp()
    client = chromadb.PersistentClient(path=tmpdir)
    col = get_collection(client, "test_col", create=True, device="cpu")
    col.add(ids=["d0"], documents=["existing doc"])
    batch = [
        {"id": "d0", "document": "duplicate doc", "metadata": {"wing": "test"}},
        {"id": "d1", "document": "new doc", "metadata": {"wing": "test"}},
    ]
    added = flush_batch(col, batch)
    assert added >= 1  # at least d1 should succeed
