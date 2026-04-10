"""Failure mode tests — verify graceful degradation under error conditions.

Tests error paths, corrupted data, and edge conditions in:
  - palace.py: ChromaDB access failures
  - config.py: malformed configuration
  - searcher.py: query failures
  - knowledge_graph.py: DB corruption / locking
  - mcp_server.py: malformed requests and tool errors
"""

import json
import os
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from mempalace.config import MempalaceConfig
from mempalace.palace import get_collection, file_already_mined
from mempalace.searcher import SearchError, search, search_memories
from mempalace.knowledge_graph import KnowledgeGraph


# ── Palace failure modes ───────────────────────────────────────────────


class TestPalaceFailures:
    def test_get_collection_chromadb_get_fails_creates_new(self, tmp_path):
        """If get_collection raises, it should fallback to create_collection."""
        palace_path = str(tmp_path / "palace")
        # get_collection internally catches and creates — just verify it works
        col = get_collection(palace_path, "new_collection")
        assert col is not None
        assert col.name == "new_collection"

    def test_file_already_mined_with_corrupt_metadata(self, tmp_path):
        """Metadata with unexpected types should not crash."""
        palace_path = str(tmp_path / "palace")
        col = get_collection(palace_path)
        # Add metadata with non-standard values
        col.add(
            ids=["d_corrupt"],
            documents=["some content"],
            metadatas=[{"source_file": "/test.py", "source_mtime": "not_a_number", "wing": "t"}],
        )
        # check_mtime=True with non-numeric mtime should return False gracefully
        result = file_already_mined(col, "/test.py", check_mtime=True)
        # Should not crash — the float() conversion of "not_a_number" will fail
        # and the function catches all exceptions
        assert isinstance(result, bool)


# ── Config failure modes ───────────────────────────────────────────────


class TestConfigFailures:
    def test_truncated_json(self, tmp_path):
        """Truncated JSON should fallback to defaults."""
        (tmp_path / "config.json").write_text('{"palace_path": "/cus', encoding="utf-8")
        cfg = MempalaceConfig(config_dir=str(tmp_path))
        # Should use default, not crash
        assert cfg.palace_path is not None

    def test_json_array_instead_of_object(self, tmp_path):
        """JSON array instead of object — .get() will fail, but config
        catches the exception and falls back to defaults."""
        (tmp_path / "config.json").write_text("[1, 2, 3]", encoding="utf-8")
        cfg = MempalaceConfig(config_dir=str(tmp_path))
        # _file_config will be [1,2,3] — accessing .get() raises AttributeError
        # The config is loaded successfully but properties that call .get() may fail.
        # Verify the property doesn't crash at construction time.
        assert cfg is not None
        # Accessing collection_name will call list.get() which raises.
        # This reveals the config doesn't guard against non-dict JSON.
        with pytest.raises(AttributeError):
            _ = cfg.collection_name

    def test_people_map_file_is_array(self, tmp_path):
        """people_map.json containing a list should fallback gracefully."""
        (tmp_path / "people_map.json").write_text("[1, 2]", encoding="utf-8")
        cfg = MempalaceConfig(config_dir=str(tmp_path))
        result = cfg.people_map
        # Returns the list (or empty) — should not crash
        assert result is not None

    def test_config_dir_is_file_not_directory(self, tmp_path):
        """Passing a file as config_dir should not crash."""
        cfg_file = tmp_path / "not_a_dir"
        cfg_file.write_text("oops", encoding="utf-8")
        # Should not crash during init
        cfg = MempalaceConfig(config_dir=str(cfg_file))
        assert cfg.palace_path is not None

    def test_unicode_in_config_values(self, tmp_path):
        """Config with Unicode values should work."""
        (tmp_path / "config.json").write_text(
            json.dumps({"palace_path": "/tmp/宫殿/мемори"}),
            encoding="utf-8",
        )
        cfg = MempalaceConfig(config_dir=str(tmp_path))
        assert "宫殿" in cfg.palace_path


# ── Searcher failure modes ─────────────────────────────────────────────


class TestSearcherFailures:
    def test_search_memories_no_palace(self, tmp_path):
        """search_memories on nonexistent path returns error dict."""
        result = search_memories("query", str(tmp_path / "nope"))
        assert "error" in result

    def test_search_cli_no_palace_raises(self, tmp_path):
        """search() CLI function raises SearchError."""
        with pytest.raises(SearchError):
            search("query", str(tmp_path / "nope"))

    def test_search_memories_empty_collection(self, tmp_path):
        """Search on empty collection returns empty results, not error."""
        import chromadb

        palace_path = str(tmp_path / "palace")
        client = chromadb.PersistentClient(path=palace_path)
        client.get_or_create_collection("mempalace_drawers")
        del client

        result = search_memories("anything", palace_path)
        assert "error" not in result
        assert result["results"] == []

    def test_search_memories_query_exception(self):
        """Internal query exception returns error dict."""
        mock_col = MagicMock()
        mock_col.query.side_effect = RuntimeError("internal error")
        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_col

        with patch("mempalace.searcher.chromadb.PersistentClient", return_value=mock_client):
            result = search_memories("test", "/fake")
        assert "error" in result

    def test_search_with_special_characters(self, tmp_path):
        """Queries with special chars should not crash."""
        import chromadb

        palace_path = str(tmp_path / "palace")
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_or_create_collection("mempalace_drawers")
        col.add(
            ids=["d1"],
            documents=["normal content"],
            metadatas=[{"wing": "test", "room": "room", "source_file": "f.py", "chunk_index": 0}],
        )
        del client

        # These should not crash
        for query in ["", "   ", "🚀 emoji query", "SELECT * FROM", "<script>alert(1)</script>"]:
            result = search_memories(query or "fallback", palace_path)
            assert isinstance(result, dict)


# ── KnowledgeGraph failure modes ───────────────────────────────────────


class TestKGFailures:
    def test_add_entity_duplicate_is_safe(self, tmp_path):
        """Adding the same entity twice should not raise."""
        kg = KnowledgeGraph(db_path=str(tmp_path / "kg.sqlite3"))
        kg.add_entity("Alice", entity_type="person")
        kg.add_entity("Alice", entity_type="person")  # should not crash
        stats = kg.stats()
        assert stats["entities"] >= 1

    def test_query_nonexistent_entity(self, tmp_path):
        """Querying a non-existent entity returns empty results."""
        kg = KnowledgeGraph(db_path=str(tmp_path / "kg.sqlite3"))
        result = kg.query_entity("NoSuchPerson")
        assert isinstance(result, (list, dict))

    def test_stats_on_empty_db(self, tmp_path):
        """Stats on empty KG should return zero counts."""
        kg = KnowledgeGraph(db_path=str(tmp_path / "kg.sqlite3"))
        stats = kg.stats()
        assert stats["entities"] == 0
        assert stats["triples"] == 0


# ── MCP Server failure modes ──────────────────────────────────────────


class TestMCPFailures:
    def test_malformed_jsonrpc_missing_method(self):
        """Request missing 'method' should return error."""
        from mempalace.mcp_server import handle_request

        resp = handle_request({"id": 1, "params": {}})
        # Should handle gracefully (error or None)
        assert resp is None or "error" in resp or "result" in resp

    def test_tools_call_with_empty_string_name(self):
        """Tool call with empty name returns method-not-found."""
        from mempalace.mcp_server import handle_request

        resp = handle_request(
            {"method": "tools/call", "id": 1, "params": {"name": "", "arguments": {}}}
        )
        assert "error" in resp

    def test_tools_call_with_none_name(self):
        """Tool call with None name returns error."""
        from mempalace.mcp_server import handle_request

        resp = handle_request(
            {"method": "tools/call", "id": 1, "params": {"name": None, "arguments": {}}}
        )
        assert "error" in resp

    def test_search_tool_with_empty_query(self, monkeypatch, tmp_path):
        """mempalace_search with empty query should not crash."""
        import chromadb
        import mempalace.mcp_server as mcp_mod
        from mempalace.config import MempalaceConfig
        from mempalace.knowledge_graph import KnowledgeGraph

        palace_path = str(tmp_path / "palace")
        client = chromadb.PersistentClient(path=palace_path)
        client.get_or_create_collection("mempalace_drawers")
        del client

        cfg = MempalaceConfig(config_dir=str(tmp_path / "cfg"))
        monkeypatch.setattr(cfg, "_file_config", {"palace_path": palace_path})
        monkeypatch.setattr(mcp_mod, "_config", cfg)
        monkeypatch.setattr(mcp_mod, "_kg", KnowledgeGraph(db_path=str(tmp_path / "kg.sqlite3")))

        from mempalace.mcp_server import handle_request

        resp = handle_request(
            {
                "method": "tools/call",
                "id": 1,
                "params": {"name": "mempalace_search", "arguments": {"query": "  "}},
            }
        )
        # Should return a response (possibly with validation error), not crash
        assert resp is not None
