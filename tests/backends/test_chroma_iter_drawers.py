"""Verify ChromaBackend.iter_drawers() against a real temp palace."""
from pathlib import Path
import pytest


@pytest.fixture
def tiny_palace(tmp_path):
    """Write 3 drawers directly via ChromaBackend, bypassing miner."""
    pytest.importorskip("chromadb")
    from mempalace.backends.chroma import ChromaBackend

    palace_path = tmp_path / "palace"
    palace_path.mkdir()
    backend = ChromaBackend()
    col = backend.get_or_create_collection(str(palace_path), "mempalace_drawers")
    col.add(
        ids=["d0", "d1", "d2"],
        documents=["Text zero about Alice.", "Text one about Bob.", "Text two about Carol."],
        metadatas=[{"wing": "w1"}, {"wing": "w1"}, {"wing": "w2"}],
    )
    return str(palace_path)


def test_iter_drawers_returns_all(tiny_palace):
    from mempalace.backends.chroma import ChromaBackend
    drawers = list(ChromaBackend().iter_drawers(tiny_palace))
    assert len(drawers) == 3
    ids = {d["id"] for d in drawers}
    assert ids == {"d0", "d1", "d2"}
    for d in drawers:
        assert "text" in d and d["text"].startswith("Text")


def test_iter_drawers_filters_by_wing(tiny_palace):
    from mempalace.backends.chroma import ChromaBackend
    w1 = list(ChromaBackend().iter_drawers(tiny_palace, wing="w1"))
    assert len(w1) == 2
    w_none = list(ChromaBackend().iter_drawers(tiny_palace, wing="nope"))
    assert w_none == []


def test_iter_drawers_empty_palace(tmp_path):
    pytest.importorskip("chromadb")
    from mempalace.backends.chroma import ChromaBackend
    empty = tmp_path / "empty"
    empty.mkdir()
    assert list(ChromaBackend().iter_drawers(str(empty))) == []
