"""Tests for mempalace.palace_db — ChromaDB operations."""

import os

import pytest

from mempalace.palace_db import (
    build_where_filter,
    file_already_mined,
    get_client,
    get_collection,
    no_palace_error,
    query_palace,
    reset,
)


class TestBuildWhereFilter:
    def test_wing_only(self):
        assert build_where_filter(wing="myapp") == {"wing": "myapp"}

    def test_room_only(self):
        assert build_where_filter(room="backend") == {"room": "backend"}

    def test_both(self):
        result = build_where_filter(wing="myapp", room="backend")
        assert result == {"$and": [{"wing": "myapp"}, {"room": "backend"}]}

    def test_neither(self):
        assert build_where_filter() == {}


class TestGetClient:
    def test_creates_directory(self, palace_path):
        client = get_client(palace_path)
        assert client is not None
        assert os.path.exists(palace_path)

    def test_singleton(self, palace_path):
        c1 = get_client(palace_path)
        c2 = get_client(palace_path)
        assert c1 is c2


class TestGetCollection:
    def test_create_true(self, palace_path):
        col = get_collection(palace_path=palace_path, create=True)
        assert col is not None
        assert col.count() == 0

    def test_create_false_missing(self, palace_path):
        os.makedirs(palace_path, exist_ok=True)
        col = get_collection(palace_path=palace_path, create=False)
        assert col is None

    def test_custom_collection_name(self, palace_path):
        col = get_collection(palace_path=palace_path, create=True, collection_name="custom_col")
        assert col is not None

    def test_cached(self, palace_path):
        c1 = get_collection(palace_path=palace_path, create=True)
        c2 = get_collection(palace_path=palace_path, create=True)
        assert c1 is c2


class TestFileAlreadyMined:
    def test_not_mined(self, palace_path):
        col = get_collection(palace_path=palace_path, create=True)
        assert file_already_mined(col, "/src/new.py") is False

    def test_already_mined(self, palace_path):
        col = get_collection(palace_path=palace_path, create=True)
        col.add(
            documents=["content"],
            ids=["d1"],
            metadatas=[{"source_file": "/src/old.py", "wing": "w", "room": "r"}],
        )
        assert file_already_mined(col, "/src/old.py") is True


class TestQueryPalace:
    @pytest.mark.integration
    def test_basic_search(self, palace_with_data):
        results = query_palace("GraphQL architecture", palace_path=palace_with_data)
        assert results is not None
        assert len(results["documents"][0]) > 0

    @pytest.mark.integration
    def test_wing_filter(self, palace_with_data):
        results = query_palace("anything", wing="personal", palace_path=palace_with_data)
        metas = results["metadatas"][0]
        assert all(m["wing"] == "personal" for m in metas)

    def test_no_palace(self, tmp_path):
        result = query_palace("test", palace_path=str(tmp_path / "nope"))
        assert result is None


class TestNoPalaceError:
    def test_returns_error_dict(self):
        result = no_palace_error("/fake/path")
        assert result["error"] == "No palace found"
        assert result["palace_path"] == "/fake/path"
        assert "hint" in result


class TestReset:
    def test_clears_caches(self, palace_path):
        get_collection(palace_path=palace_path, create=True)
        reset()
        reset()  # should not error when called twice
