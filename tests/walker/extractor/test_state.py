import threading
import pytest
from mempalace.knowledge_graph import KnowledgeGraph
from mempalace.walker.extractor.state import ExtractionState


def test_table_created_with_correct_schema(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    ExtractionState(kg)
    cols = kg._conn().execute("PRAGMA table_info(extraction_state)").fetchall()
    names = [c[1] for c in cols]
    assert names == [
        "drawer_id", "extractor_version", "extracted_at",
        "triple_count", "entity_count",
    ]
    pk = [c for c in cols if c[5] == 1]
    assert len(pk) == 1
    assert pk[0][1] == "drawer_id"


def test_is_extracted_unknown_drawer(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    assert state.is_extracted("drawer_1", "v1.0") is False


def test_mark_and_query(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    state.mark_extracted("d1", "v1.0", triple_count=3, entity_count=5)
    assert state.is_extracted("d1", "v1.0") is True
    assert state.is_extracted("d1", "v1.1") is False


def test_mark_replaces_prior(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    state.mark_extracted("d1", "v1.0", 2, 3)
    state.mark_extracted("d1", "v1.0", 4, 6)
    row = kg._conn().execute(
        "SELECT triple_count, entity_count FROM extraction_state WHERE drawer_id='d1'"
    ).fetchone()
    assert row[0] == 4 and row[1] == 6


def test_unextracted_ids_filters(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    state.mark_extracted("d1", "v1.0", 0, 0)
    state.mark_extracted("d2", "v1.0", 0, 0)
    result = state.unextracted_ids(["d1", "d2", "d3", "d4"], "v1.0")
    assert set(result) == {"d3", "d4"}


def test_unextracted_ids_different_version(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    state.mark_extracted("d1", "v1.0", 0, 0)
    assert state.unextracted_ids(["d1"], "v1.1") == ["d1"]


def test_max_extracted_at(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    state.mark_extracted("d1", "v1.0", 0, 0)
    assert state.max_extracted_at("v1.0") is not None
    assert state.max_extracted_at("v2.0") is None


def test_concurrent_writes_no_errors(tmp_path):
    """Verify shared-lock prevents mid-transaction collisions."""
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    errors = []

    def upsert_worker(i):
        try:
            kg.upsert_triple(f"Alice{i}", "knows", f"Bob{i}")
        except Exception as e:
            errors.append(e)

    def state_worker(i):
        try:
            state.mark_extracted(f"d{i}", "v1.0", 1, 2)
        except Exception as e:
            errors.append(e)

    threads = []
    for i in range(20):
        threads.append(threading.Thread(target=upsert_worker, args=(i,)))
        threads.append(threading.Thread(target=state_worker, args=(i,)))
    for t in threads: t.start()
    for t in threads: t.join()
    assert errors == []
