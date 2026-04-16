import json
from unittest.mock import MagicMock, AsyncMock
import pytest
from mempalace.knowledge_graph import KnowledgeGraph
from mempalace.walker.extractor.state import ExtractionState
from mempalace.walker.extractor.gliner_ner import Entity
from mempalace.walker.extractor.qwen_rel import Triple
from mempalace.walker.extractor.pipeline import extract_drawers


def _mock_gliner(per_drawer):
    g = MagicMock()
    g.extract_batch.return_value = per_drawer
    return g


def _mock_qwen(triples_sequence):
    q = AsyncMock()
    q.extract = AsyncMock(side_effect=triples_sequence)
    return q


async def test_empty_drawer_list(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    g = _mock_gliner([])
    q = _mock_qwen([])
    stats = await extract_drawers(drawers=[], kg=kg, state=state, gliner=g, qwen=q)
    assert stats.drawers_processed == 0
    g.extract_batch.assert_not_called()
    q.extract.assert_not_called()


async def test_single_drawer_full_pipeline(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    drawer = {"id": "d1", "text": "Alice works at DeepMind."}
    g = _mock_gliner([[Entity("Alice", "person", 0.9), Entity("DeepMind", "organization", 0.9)]])
    q = _mock_qwen([[Triple("Alice", "works_at", "DeepMind")]])

    stats = await extract_drawers(drawers=[drawer], kg=kg, state=state, gliner=g, qwen=q)

    assert stats.drawers_processed == 1
    assert stats.entities_found == 2
    assert stats.triples_inserted == 1
    assert state.is_extracted("d1", "v1.0")


async def test_source_tag_and_drawer_id_written(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    g = _mock_gliner([[Entity("Alice", "person", 0.9), Entity("DeepMind", "organization", 0.9)]])
    q = _mock_qwen([[Triple("Alice", "works_at", "DeepMind")]])

    await extract_drawers(
        drawers=[{"id": "d1", "text": "Alice works at DeepMind."}],
        kg=kg, state=state, gliner=g, qwen=q,
    )
    row = kg._conn().execute(
        "SELECT source, source_drawer_ids FROM triples"
    ).fetchone()
    assert row[0] == "extractor_v1.0"
    assert json.loads(row[1]) == ["d1"]

    row = kg._conn().execute(
        "SELECT triple_count, entity_count FROM extraction_state WHERE drawer_id='d1'"
    ).fetchone()
    assert row[0] == 1 and row[1] == 2


async def test_zero_entity_skips_qwen_marks_extracted(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    g = _mock_gliner([[]])
    q = _mock_qwen([])

    stats = await extract_drawers(
        drawers=[{"id": "d1", "text": "bland"}],
        kg=kg, state=state, gliner=g, qwen=q,
    )
    q.extract.assert_not_called()
    assert state.is_extracted("d1", "v1.0")
    assert stats.drawers_processed == 1
    assert stats.triples_inserted == 0


async def test_already_extracted_skipped(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    state.mark_extracted("d1", "v1.0", 0, 0)
    g = _mock_gliner([])
    q = _mock_qwen([])

    stats = await extract_drawers(
        drawers=[{"id": "d1", "text": "x"}],
        kg=kg, state=state, gliner=g, qwen=q,
    )
    assert stats.drawers_skipped == 1
    g.extract_batch.assert_not_called()
    q.extract.assert_not_called()


async def test_idempotent_run_twice(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    drawer = {"id": "d1", "text": "Alice works at DeepMind."}
    entities = [Entity("Alice", "person", 0.9), Entity("DeepMind", "organization", 0.9)]
    triples = [Triple("Alice", "works_at", "DeepMind")]

    for _ in range(2):
        await extract_drawers(
            drawers=[drawer], kg=kg, state=state,
            gliner=_mock_gliner([entities]),
            qwen=_mock_qwen([triples]),
        )

    live = kg._conn().execute(
        "SELECT COUNT(*) FROM triples WHERE valid_to IS NULL"
    ).fetchone()[0]
    assert live == 1


async def test_dry_run_prints_and_does_not_write(tmp_path, capsys):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    g = _mock_gliner([[Entity("Alice", "person", 0.9)]])
    q = _mock_qwen([[Triple("Alice", "works_at", "DeepMind")]])

    stats = await extract_drawers(
        drawers=[{"id": "d1", "text": "Alice."}],
        kg=kg, state=state, gliner=g, qwen=q, dry_run=True,
    )
    out = capsys.readouterr().out
    assert "[DRY]" in out and "d1" in out and "Alice" in out
    assert stats.drawers_processed == 1
    assert not state.is_extracted("d1", "v1.0")
    assert kg._conn().execute("SELECT COUNT(*) FROM triples").fetchone()[0] == 0


async def test_custom_version_propagates(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    g = _mock_gliner([[Entity("Alice", "person", 0.9)]])
    q = _mock_qwen([[Triple("Alice", "is_a", "person")]])

    await extract_drawers(
        drawers=[{"id": "d1", "text": "Alice."}],
        kg=kg, state=state, gliner=g, qwen=q,
        extractor_version="v2.5",
    )
    source = kg._conn().execute("SELECT source FROM triples").fetchone()[0]
    assert source == "extractor_v2.5"
    assert state.is_extracted("d1", "v2.5")
    assert not state.is_extracted("d1", "v1.0")
