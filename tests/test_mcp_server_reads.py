"""Tests for MCP server read tools — status, list_wings, list_rooms, get_taxonomy.

These tools previously called col.get() without a limit, causing them to return
empty results on palaces with more drawers than ChromaDB's internal default.
"""

import shutil
import tempfile
from unittest.mock import patch

import chromadb

from mempalace import mcp_server


def _populate_palace(palace_path, drawers):
    """Insert drawers into a fresh palace.

    Args:
        palace_path: Directory for the ChromaDB persistent client.
        drawers: List of (id, document, metadata) tuples.

    Returns:
        The ChromaDB collection.
    """
    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_or_create_collection("mempalace_drawers")
    batch_size = 5000
    for start in range(0, len(drawers), batch_size):
        batch = drawers[start : start + batch_size]
        col.add(
            ids=[d[0] for d in batch],
            documents=[d[1] for d in batch],
            metadatas=[d[2] for d in batch],
        )
    return col


def _make_drawers(n, n_wings=2, n_rooms=3):
    """Generate n drawer tuples spread across wings and rooms."""
    wings = [f"wing_{i}" for i in range(n_wings)]
    rooms = [f"room_{i}" for i in range(n_rooms)]
    return [
        (
            f"drawer_{i}",
            f"content {i}",
            {"wing": wings[i % n_wings], "room": rooms[i % n_rooms], "source_file": f"f{i}.py"},
        )
        for i in range(n)
    ]


def _patch_config(palace_path):
    """Return a mock _get_collection that points at our temp palace."""
    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_collection("mempalace_drawers")

    def fake_get_collection(create=False):
        return col

    return patch.object(mcp_server, "_get_collection", side_effect=fake_get_collection)


class TestToolStatus:
    def test_status_returns_all_wings_and_rooms(self):
        palace_path = tempfile.mkdtemp()
        try:
            drawers = _make_drawers(60, n_wings=3, n_rooms=2)
            _populate_palace(palace_path, drawers)

            with _patch_config(palace_path):
                result = mcp_server.tool_status()

            assert result["total_drawers"] == 60
            assert len(result["wings"]) == 3
            assert sum(result["wings"].values()) == 60
            assert len(result["rooms"]) == 2
            assert sum(result["rooms"].values()) == 60
        finally:
            shutil.rmtree(palace_path)

    def test_status_empty_palace(self):
        palace_path = tempfile.mkdtemp()
        try:
            client = chromadb.PersistentClient(path=palace_path)
            client.get_or_create_collection("mempalace_drawers")

            with _patch_config(palace_path):
                result = mcp_server.tool_status()

            assert result["total_drawers"] == 0
            assert result["wings"] == {}
            assert result["rooms"] == {}
        finally:
            shutil.rmtree(palace_path)


class TestToolListWings:
    def test_lists_all_wings_with_counts(self):
        palace_path = tempfile.mkdtemp()
        try:
            drawers = _make_drawers(40, n_wings=4)
            _populate_palace(palace_path, drawers)

            with _patch_config(palace_path):
                result = mcp_server.tool_list_wings()

            assert len(result["wings"]) == 4
            for wing_name, count in result["wings"].items():
                assert count == 10
        finally:
            shutil.rmtree(palace_path)

    def test_lists_wings_empty_palace(self):
        palace_path = tempfile.mkdtemp()
        try:
            client = chromadb.PersistentClient(path=palace_path)
            client.get_or_create_collection("mempalace_drawers")

            with _patch_config(palace_path):
                result = mcp_server.tool_list_wings()

            assert result["wings"] == {}
        finally:
            shutil.rmtree(palace_path)


class TestToolListRooms:
    def test_lists_all_rooms(self):
        palace_path = tempfile.mkdtemp()
        try:
            drawers = _make_drawers(30, n_wings=1, n_rooms=3)
            _populate_palace(palace_path, drawers)

            with _patch_config(palace_path):
                result = mcp_server.tool_list_rooms()

            assert result["wing"] == "all"
            assert len(result["rooms"]) == 3
            assert sum(result["rooms"].values()) == 30
        finally:
            shutil.rmtree(palace_path)

    def test_lists_rooms_filtered_by_wing(self):
        palace_path = tempfile.mkdtemp()
        try:
            drawers = _make_drawers(60, n_wings=3, n_rooms=2)
            _populate_palace(palace_path, drawers)

            with _patch_config(palace_path):
                result = mcp_server.tool_list_rooms(wing="wing_0")

            assert result["wing"] == "wing_0"
            assert sum(result["rooms"].values()) == 20
        finally:
            shutil.rmtree(palace_path)


class TestToolGetTaxonomy:
    def test_taxonomy_returns_full_tree(self):
        palace_path = tempfile.mkdtemp()
        try:
            drawers = _make_drawers(60, n_wings=3, n_rooms=2)
            _populate_palace(palace_path, drawers)

            with _patch_config(palace_path):
                result = mcp_server.tool_get_taxonomy()

            taxonomy = result["taxonomy"]
            assert len(taxonomy) == 3  # 3 wings
            total = 0
            for wing, rooms in taxonomy.items():
                for room, count in rooms.items():
                    total += count
            assert total == 60
        finally:
            shutil.rmtree(palace_path)


class TestToolDiaryRead:
    def test_diary_read_returns_all_entries(self):
        """tool_diary_read must return all diary entries, not a truncated subset."""
        palace_path = tempfile.mkdtemp()
        try:
            drawers = [
                (
                    f"diary_{i}",
                    f"diary entry {i}",
                    {
                        "wing": "wing_reviewer",
                        "room": "diary",
                        "topic": f"topic_{i}",
                        "filed_at": f"2026-04-{i + 1:02d}T12:00:00",
                        "date": f"2026-04-{i + 1:02d}",
                    },
                )
                for i in range(25)
            ]
            _populate_palace(palace_path, drawers)

            with _patch_config(palace_path):
                result = mcp_server.tool_diary_read("reviewer", last_n=50)

            assert result["total"] == 25
            assert result["showing"] == 25
            assert len(result["entries"]) == 25
        finally:
            shutil.rmtree(palace_path)

    def test_diary_read_empty(self):
        """tool_diary_read on a palace with no diary entries returns an empty list."""
        palace_path = tempfile.mkdtemp()
        try:
            client = chromadb.PersistentClient(path=palace_path)
            client.get_or_create_collection("mempalace_drawers")

            with _patch_config(palace_path):
                result = mcp_server.tool_diary_read("reviewer")

            assert result["entries"] == []
        finally:
            shutil.rmtree(palace_path)
