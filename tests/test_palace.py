"""Tests for shared palace access helpers."""

from mempalace.palace import get_drawer_collection, iter_collection_metadatas


class _PagedCollection:
    def __init__(self, total):
        self._metadatas = [{"wing": "w", "room": f"r{i % 3}"} for i in range(total)]

    def get(self, include, limit, offset, where=None):
        del include, where
        batch = self._metadatas[offset : offset + limit]
        return {
            "ids": [f"id{offset + i}" for i in range(len(batch))],
            "metadatas": batch,
        }


def test_get_drawer_collection_read_does_not_create_missing_dir(tmp_path):
    missing = tmp_path / "missing-palace"

    assert get_drawer_collection(palace_path=str(missing), create=False) is None
    assert not missing.exists()


def test_iter_collection_metadatas_pages_without_hard_cap():
    collection = _PagedCollection(10_005)

    rows = list(iter_collection_metadatas(collection, batch_size=1000))

    assert len(rows) == 10_005
    assert rows[0]["room"] == "r0"
    assert rows[-1]["room"] == "r2"
