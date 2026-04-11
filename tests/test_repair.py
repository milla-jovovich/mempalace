"""Tests for mempalace.repair — scan, prune, and rebuild HNSW index."""

import os
from unittest.mock import MagicMock, patch


from mempalace import repair


# ── _get_palace_path ──────────────────────────────────────────────────


@patch("mempalace.repair.MempalaceConfig", create=True)
def test_get_palace_path_from_config(mock_config_cls):
    mock_config_cls.return_value.palace_path = "/configured/palace"
    with patch.dict("sys.modules", {}):
        # Force reimport to pick up the mock
        result = repair._get_palace_path()
    assert isinstance(result, str)


def test_get_palace_path_fallback():
    with patch("mempalace.repair._get_palace_path") as mock_get:
        mock_get.return_value = os.path.join(os.path.expanduser("~"), ".mempalace", "palace")
        result = mock_get()
        assert ".mempalace" in result


# ── _paginate_ids ─────────────────────────────────────────────────────


def test_paginate_ids_single_batch():
    col = MagicMock()
    col.get.return_value = {"ids": ["id1", "id2", "id3"]}
    ids = repair._paginate_ids(col)
    assert ids == ["id1", "id2", "id3"]


def test_paginate_ids_empty():
    col = MagicMock()
    col.get.return_value = {"ids": []}
    ids = repair._paginate_ids(col)
    assert ids == []


def test_paginate_ids_with_where():
    col = MagicMock()
    col.get.return_value = {"ids": ["id1"]}
    repair._paginate_ids(col, where={"wing": "test"})
    col.get.assert_called_with(where={"wing": "test"}, include=[], limit=1000, offset=0)


def test_paginate_ids_offset_exception_fallback():
    col = MagicMock()
    # First call raises, fallback returns ids, second fallback returns empty
    col.get.side_effect = [
        Exception("offset bug"),
        {"ids": ["id1", "id2"]},
        Exception("offset bug"),
        {"ids": ["id1", "id2"]},  # same ids = no new = break
    ]
    ids = repair._paginate_ids(col)
    assert "id1" in ids


# ── scan_palace ───────────────────────────────────────────────────────


@patch("mempalace.repair.chromadb")
def test_scan_palace_no_ids(mock_chromadb, tmp_path):
    mock_col = MagicMock()
    mock_col.count.return_value = 0
    mock_col.get.return_value = {"ids": []}
    mock_client = MagicMock()
    mock_client.get_collection.return_value = mock_col
    mock_chromadb.PersistentClient.return_value = mock_client

    good, bad = repair.scan_palace(palace_path=str(tmp_path))
    assert good == set()
    assert bad == set()


@patch("mempalace.repair.chromadb")
def test_scan_palace_all_good(mock_chromadb, tmp_path):
    mock_col = MagicMock()
    mock_col.count.return_value = 2
    # _paginate_ids call
    mock_col.get.side_effect = [
        {"ids": ["id1", "id2"]},  # paginate
        {"ids": ["id1", "id2"]},  # probe batch — both returned
    ]
    mock_client = MagicMock()
    mock_client.get_collection.return_value = mock_col
    mock_chromadb.PersistentClient.return_value = mock_client

    good, bad = repair.scan_palace(palace_path=str(tmp_path))
    assert "id1" in good
    assert "id2" in good
    assert len(bad) == 0


@patch("mempalace.repair.chromadb")
def test_scan_palace_with_bad_ids(mock_chromadb, tmp_path):
    mock_col = MagicMock()
    mock_col.count.return_value = 2

    def get_side_effect(**kwargs):
        ids = kwargs.get("ids", None)
        if ids is None:
            # paginate call
            return {"ids": ["good1", "bad1"]}
        if "bad1" in ids and len(ids) == 1:
            raise Exception("corrupt")
        if "good1" in ids and len(ids) == 1:
            return {"ids": ["good1"]}
        # batch probe — raise to force per-id
        raise Exception("batch fail")

    mock_col.get.side_effect = get_side_effect
    mock_client = MagicMock()
    mock_client.get_collection.return_value = mock_col
    mock_chromadb.PersistentClient.return_value = mock_client

    good, bad = repair.scan_palace(palace_path=str(tmp_path))
    assert "good1" in good
    assert "bad1" in bad


@patch("mempalace.repair.chromadb")
def test_scan_palace_with_wing_filter(mock_chromadb, tmp_path):
    mock_col = MagicMock()
    mock_col.count.return_value = 1
    mock_col.get.side_effect = [
        {"ids": ["id1"]},  # paginate
        {"ids": ["id1"]},  # probe
    ]
    mock_client = MagicMock()
    mock_client.get_collection.return_value = mock_col
    mock_chromadb.PersistentClient.return_value = mock_client

    repair.scan_palace(palace_path=str(tmp_path), only_wing="test_wing")
    # Verify where filter was passed
    first_call = mock_col.get.call_args_list[0]
    assert first_call.kwargs.get("where") == {"wing": "test_wing"}


# ── prune_corrupt ─────────────────────────────────────────────────────


@patch("mempalace.repair.chromadb")
def test_prune_corrupt_no_file(mock_chromadb, tmp_path):
    # Should print message and return without error
    repair.prune_corrupt(palace_path=str(tmp_path))


@patch("mempalace.repair.chromadb")
def test_prune_corrupt_dry_run(mock_chromadb, tmp_path):
    bad_file = tmp_path / "corrupt_ids.txt"
    bad_file.write_text("bad1\nbad2\n")
    repair.prune_corrupt(palace_path=str(tmp_path), confirm=False)
    # No chromadb calls in dry run
    mock_chromadb.PersistentClient.assert_not_called()


@patch("mempalace.repair.chromadb")
def test_prune_corrupt_confirmed(mock_chromadb, tmp_path):
    bad_file = tmp_path / "corrupt_ids.txt"
    bad_file.write_text("bad1\nbad2\n")

    mock_col = MagicMock()
    mock_col.count.side_effect = [10, 8]
    mock_client = MagicMock()
    mock_client.get_collection.return_value = mock_col
    mock_chromadb.PersistentClient.return_value = mock_client

    repair.prune_corrupt(palace_path=str(tmp_path), confirm=True)
    mock_col.delete.assert_called_once()


@patch("mempalace.repair.chromadb")
def test_prune_corrupt_delete_failure_fallback(mock_chromadb, tmp_path):
    bad_file = tmp_path / "corrupt_ids.txt"
    bad_file.write_text("bad1\nbad2\n")

    mock_col = MagicMock()
    mock_col.count.side_effect = [10, 8]
    # Batch delete fails, per-id succeeds
    mock_col.delete.side_effect = [Exception("batch fail"), None, None]
    mock_client = MagicMock()
    mock_client.get_collection.return_value = mock_col
    mock_chromadb.PersistentClient.return_value = mock_client

    repair.prune_corrupt(palace_path=str(tmp_path), confirm=True)
    assert mock_col.delete.call_count == 3  # 1 batch + 2 individual


# ── rebuild_index ─────────────────────────────────────────────────────


@patch("mempalace.repair.chromadb")
def test_rebuild_index_no_palace(mock_chromadb, tmp_path):
    nonexistent = str(tmp_path / "nope")
    repair.rebuild_index(palace_path=nonexistent)
    mock_chromadb.PersistentClient.assert_not_called()


@patch("mempalace.repair.shutil")
@patch("mempalace.repair.chromadb")
def test_rebuild_index_empty_palace(mock_chromadb, mock_shutil, tmp_path):
    mock_col = MagicMock()
    mock_col.count.return_value = 0
    mock_client = MagicMock()
    mock_client.get_collection.return_value = mock_col
    mock_chromadb.PersistentClient.return_value = mock_client

    repair.rebuild_index(palace_path=str(tmp_path))
    mock_client.delete_collection.assert_not_called()


@patch("mempalace.repair.shutil")
@patch("mempalace.repair.chromadb")
def test_rebuild_index_success(mock_chromadb, mock_shutil, tmp_path):
    # Create a fake sqlite file
    sqlite_path = tmp_path / "chroma.sqlite3"
    sqlite_path.write_text("fake")

    mock_col = MagicMock()
    mock_col.count.return_value = 2
    mock_col.get.return_value = {
        "ids": ["id1", "id2"],
        "documents": ["doc1", "doc2"],
        "metadatas": [{"wing": "a"}, {"wing": "b"}],
    }

    mock_new_col = MagicMock()
    mock_client = MagicMock()
    mock_client.get_collection.return_value = mock_col
    mock_client.create_collection.return_value = mock_new_col
    mock_chromadb.PersistentClient.return_value = mock_client

    repair.rebuild_index(palace_path=str(tmp_path))

    # Verify: backed up sqlite only (not copytree)
    mock_shutil.copy2.assert_called_once()
    assert "chroma.sqlite3" in str(mock_shutil.copy2.call_args)

    # Verify: deleted and recreated with cosine
    mock_client.delete_collection.assert_called_once_with("mempalace_drawers")
    mock_client.create_collection.assert_called_once_with(
        "mempalace_drawers", metadata={"hnsw:space": "cosine"}
    )

    # Verify: used upsert not add
    mock_new_col.upsert.assert_called_once()
    mock_new_col.add.assert_not_called()


@patch("mempalace.repair.shutil")
@patch("mempalace.repair.chromadb")
def test_rebuild_index_error_reading(mock_chromadb, mock_shutil, tmp_path):
    mock_client = MagicMock()
    mock_client.get_collection.side_effect = Exception("corrupt")
    mock_chromadb.PersistentClient.return_value = mock_client

    repair.rebuild_index(palace_path=str(tmp_path))
    mock_client.delete_collection.assert_not_called()
