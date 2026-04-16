from unittest.mock import MagicMock, AsyncMock
import pytest
from mempalace.knowledge_graph import KnowledgeGraph
from mempalace.walker.extractor.state import ExtractionState
from mempalace.walker.extractor.gliner_ner import Entity
from mempalace.walker.extractor.qwen_rel import Triple
from mempalace.dream.reextract import run_job_a, JobAResult


def _mock_gliner(per_drawer):
    g = MagicMock()
    g.extract_batch.return_value = per_drawer
    return g


def _mock_qwen(triples_seq):
    q = AsyncMock()
    q.extract = AsyncMock(side_effect=triples_seq)
    q.aclose = AsyncMock()
    return q


async def test_processes_unextracted(tmp_path, monkeypatch):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))

    monkeypatch.setattr(
        "mempalace.dream.reextract._load_drawers_from_palace",
        AsyncMock(
            return_value=[
                {"id": "d1", "text": "Alice."},
                {"id": "d2", "text": "Bob."},
            ]
        ),
    )
    gliner = _mock_gliner(
        [
            [Entity("Alice", "person", 0.9)],
            [Entity("Bob", "person", 0.9)],
        ]
    )
    qwen = _mock_qwen(
        [
            [Triple("Alice", "is_a", "person")],
            [Triple("Bob", "is_a", "person")],
        ]
    )
    monkeypatch.setattr("mempalace.dream.reextract._build_gliner", lambda: gliner)
    monkeypatch.setattr("mempalace.dream.reextract._build_qwen", lambda url: qwen)

    result = await run_job_a(
        palace_path=str(tmp_path / "palace"),
        kg=kg,
        version="v1.0",
        batch_size=500,
    )
    assert isinstance(result, JobAResult)
    assert result.drawers_processed == 2
    assert result.batches == 1
    qwen.aclose.assert_called()


async def test_only_processes_stale_version(tmp_path, monkeypatch):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    state.mark_extracted("d1", "v1.0", 1, 1)

    monkeypatch.setattr(
        "mempalace.dream.reextract._load_drawers_from_palace",
        AsyncMock(return_value=[{"id": "d1", "text": "Alice."}]),
    )
    monkeypatch.setattr(
        "mempalace.dream.reextract._build_gliner",
        lambda: _mock_gliner([[Entity("Alice", "person", 0.9)]]),
    )
    monkeypatch.setattr(
        "mempalace.dream.reextract._build_qwen",
        lambda url: _mock_qwen([[]]),
    )

    result = await run_job_a(
        palace_path=str(tmp_path / "palace"),
        kg=kg,
        version="v2.0",
    )
    assert result.drawers_processed == 1  # re-processed at v2.0


async def test_batches(tmp_path, monkeypatch):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    fake = [{"id": f"d{i}", "text": f"t{i}"} for i in range(501)]

    gliner = MagicMock()
    gliner.extract_batch.side_effect = lambda texts: [[] for _ in texts]

    monkeypatch.setattr(
        "mempalace.dream.reextract._load_drawers_from_palace",
        AsyncMock(return_value=fake),
    )
    monkeypatch.setattr("mempalace.dream.reextract._build_gliner", lambda: gliner)
    monkeypatch.setattr("mempalace.dream.reextract._build_qwen", lambda url: _mock_qwen([]))

    result = await run_job_a(
        palace_path=str(tmp_path / "palace"),
        kg=kg,
        version="v1.0",
        batch_size=500,
    )
    assert result.drawers_processed == 501
    assert result.batches == 2


async def test_dry_run_propagates(tmp_path, monkeypatch):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    monkeypatch.setattr(
        "mempalace.dream.reextract._load_drawers_from_palace",
        AsyncMock(return_value=[{"id": "d1", "text": "A."}]),
    )
    monkeypatch.setattr(
        "mempalace.dream.reextract._build_gliner",
        lambda: _mock_gliner([[Entity("A", "person", 0.9)]]),
    )
    monkeypatch.setattr(
        "mempalace.dream.reextract._build_qwen",
        lambda url: _mock_qwen([[Triple("A", "is_a", "person")]]),
    )

    await run_job_a(
        palace_path=str(tmp_path / "palace"),
        kg=kg,
        version="v1.0",
        dry_run=True,
    )
    assert kg._conn().execute("SELECT COUNT(*) FROM triples").fetchone()[0] == 0


async def test_verbatim_invariant_real_backend(tmp_path, monkeypatch):
    """Dream Job A must not mutate drawer content in the real ChromaBackend."""
    pytest.importorskip("chromadb")
    from mempalace.backends.chroma import ChromaBackend

    palace_path = tmp_path / "palace"
    palace_path.mkdir()
    backend = ChromaBackend()
    col = backend.get_or_create_collection(str(palace_path), "mempalace_drawers")
    originals = {
        "d1": "Alice works at DeepMind.",
        "d2": "Bob lives in London.",
    }
    col.add(
        ids=list(originals.keys()),
        documents=list(originals.values()),
        metadatas=[{"wing": "w"}, {"wing": "w"}],
    )

    kg = KnowledgeGraph(str(palace_path / "knowledge_graph.db"))
    monkeypatch.setattr(
        "mempalace.dream.reextract._build_gliner",
        lambda: _mock_gliner(
            [
                [Entity("Alice", "person", 0.9)],
                [Entity("Bob", "person", 0.9)],
            ]
        ),
    )
    monkeypatch.setattr(
        "mempalace.dream.reextract._build_qwen",
        lambda url: _mock_qwen(
            [
                [Triple("Alice", "is_a", "person")],
                [Triple("Bob", "is_a", "person")],
            ]
        ),
    )

    await run_job_a(palace_path=str(palace_path), kg=kg, version="v1.0")

    col2 = backend.get_collection(str(palace_path), "mempalace_drawers")
    result = col2.get(include=["documents"])
    assert col2.count() == 2
    for i, doc in zip(result["ids"], result["documents"]):
        assert doc == originals[i]
