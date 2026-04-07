"""
test_mcp_server.py — Tests for the MCP server tool handlers and dispatch.

Tests each tool handler directly (unit-level) and the handle_request
dispatch layer (integration-level). Uses isolated palace + KG fixtures
via monkeypatch to avoid touching real data.
"""

import json


def _patch_mcp_server(monkeypatch, config, palace_path, kg):
    """Patch the mcp_server module globals to use test fixtures."""
    from mempalace import mcp_server

    assert getattr(config, "palace_path", None) == palace_path, (
        f"config.palace_path ({getattr(config, 'palace_path', None)!r}) does not match palace_path fixture ({palace_path!r})"
    )
    monkeypatch.setattr(mcp_server, "_config", config)
    monkeypatch.setattr(mcp_server, "_kg", kg)


def _get_collection(palace_path, create=False):
    """Helper to get collection from test palace."""
    import chromadb

    client = chromadb.PersistentClient(path=palace_path)
    if create:
        return client.get_or_create_collection("mempalace_drawers")
    return client.get_collection("mempalace_drawers")


# ── Protocol Layer ──────────────────────────────────────────────────────


class TestHandleRequest:
    def test_initialize(self):
        from mempalace.mcp_server import handle_request

        resp = handle_request({"method": "initialize", "id": 1, "params": {}})
        assert resp["result"]["serverInfo"]["name"] == "mempalace"
        assert resp["id"] == 1

    def test_notifications_initialized_returns_none(self):
        from mempalace.mcp_server import handle_request

        resp = handle_request({"method": "notifications/initialized", "id": None, "params": {}})
        assert resp is None

    def test_tools_list(self):
        from mempalace.mcp_server import handle_request

        resp = handle_request({"method": "tools/list", "id": 2, "params": {}})
        tools = resp["result"]["tools"]
        names = {t["name"] for t in tools}
        assert "mempalace_status" in names
        assert "mempalace_search" in names
        assert "mempalace_add_drawer" in names
        assert "mempalace_kg_add" in names

    def test_unknown_tool(self):
        from mempalace.mcp_server import handle_request

        resp = handle_request(
            {
                "method": "tools/call",
                "id": 3,
                "params": {"name": "nonexistent_tool", "arguments": {}},
            }
        )
        assert resp["error"]["code"] == -32601

    def test_unknown_method(self):
        from mempalace.mcp_server import handle_request

        resp = handle_request({"method": "unknown/method", "id": 4, "params": {}})
        assert resp["error"]["code"] == -32601

    def test_tools_call_dispatches(self, monkeypatch, config, palace_path, seeded_kg):
        _patch_mcp_server(monkeypatch, config, palace_path, seeded_kg)
        from mempalace.mcp_server import handle_request

        # Create a collection so status works
        _get_collection(palace_path, create=True)

        resp = handle_request(
            {
                "method": "tools/call",
                "id": 5,
                "params": {"name": "mempalace_status", "arguments": {}},
            }
        )
        assert "result" in resp
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "total_drawers" in content


# ── Read Tools ──────────────────────────────────────────────────────────


class TestReadTools:
    def test_status_empty_palace(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _get_collection(palace_path, create=True)
        from mempalace.mcp_server import tool_status

        result = tool_status()
        assert result["total_drawers"] == 0
        assert result["wings"] == {}

    def test_status_with_data(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_status

        result = tool_status()
        assert result["total_drawers"] == 4
        assert "project" in result["wings"]
        assert "notes" in result["wings"]

    def test_list_wings(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_list_wings

        result = tool_list_wings()
        assert result["wings"]["project"] == 3
        assert result["wings"]["notes"] == 1

    def test_list_rooms_all(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_list_rooms

        result = tool_list_rooms()
        assert "backend" in result["rooms"]
        assert "frontend" in result["rooms"]
        assert "planning" in result["rooms"]

    def test_list_rooms_filtered(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_list_rooms

        result = tool_list_rooms(wing="project")
        assert "backend" in result["rooms"]
        assert "planning" not in result["rooms"]

    def test_get_taxonomy(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_get_taxonomy

        result = tool_get_taxonomy()
        assert result["taxonomy"]["project"]["backend"] == 2
        assert result["taxonomy"]["project"]["frontend"] == 1
        assert result["taxonomy"]["notes"]["planning"] == 1

    def test_no_palace_returns_error(self, monkeypatch, config, kg):
        config._file_config["palace_path"] = "/nonexistent/path"
        _patch_mcp_server(monkeypatch, config, "/nonexistent/path", kg)
        from mempalace.mcp_server import tool_status

        result = tool_status()
        assert "error" in result


# ── Search Tool ─────────────────────────────────────────────────────────


class TestSearchTool:
    def test_search_basic(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_search

        result = tool_search(query="JWT authentication tokens")
        assert "results" in result
        assert len(result["results"]) > 0
        # Top result should be the auth drawer
        top = result["results"][0]
        assert "JWT" in top["text"] or "authentication" in top["text"].lower()

    def test_search_with_wing_filter(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_search

        result = tool_search(query="planning", wing="notes")
        assert all(r["wing"] == "notes" for r in result["results"])

    def test_search_with_room_filter(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_search

        result = tool_search(query="database", room="backend")
        assert all(r["room"] == "backend" for r in result["results"])


# ── Write Tools ─────────────────────────────────────────────────────────


class TestWriteTools:
    def test_add_drawer(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _get_collection(palace_path, create=True)
        from mempalace.mcp_server import tool_add_drawer

        result = tool_add_drawer(
            wing="test_wing",
            room="test_room",
            content="This is a test memory about Python decorators and metaclasses.",
        )
        assert result["success"] is True
        assert result["wing"] == "test_wing"
        assert result["room"] == "test_room"
        assert result["drawer_id"].startswith("drawer_test_wing_test_room_")

    def test_add_drawer_duplicate_detection(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _get_collection(palace_path, create=True)
        from mempalace.mcp_server import tool_add_drawer

        content = "This is a unique test memory about Rust ownership and borrowing."
        result1 = tool_add_drawer(wing="w", room="r", content=content)
        assert result1["success"] is True

        result2 = tool_add_drawer(wing="w", room="r", content=content)
        assert result2["success"] is False
        assert result2["reason"] == "duplicate"

    def test_delete_drawer(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_delete_drawer

        result = tool_delete_drawer("drawer_proj_backend_aaa")
        assert result["success"] is True
        assert seeded_collection.count() == 3

    def test_delete_drawer_not_found(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_delete_drawer

        result = tool_delete_drawer("nonexistent_drawer")
        assert result["success"] is False

    def test_check_duplicate(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_check_duplicate

        # Exact match text from seeded_collection should be flagged
        result = tool_check_duplicate(
            "The authentication module uses JWT tokens for session management. "
            "Tokens expire after 24 hours. Refresh tokens are stored in HttpOnly cookies.",
            threshold=0.5,
        )
        assert result["is_duplicate"] is True

        # Unrelated content should not be flagged
        result = tool_check_duplicate(
            "Black holes emit Hawking radiation at the event horizon.",
            threshold=0.99,
        )
        assert result["is_duplicate"] is False


# ── KG Tools ────────────────────────────────────────────────────────────


class TestKGTools:
    def test_kg_add(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_kg_add

        result = tool_kg_add(
            subject="Alice",
            predicate="likes",
            object="coffee",
            valid_from="2025-01-01",
        )
        assert result["success"] is True

    def test_kg_query(self, monkeypatch, config, palace_path, seeded_kg):
        _patch_mcp_server(monkeypatch, config, palace_path, seeded_kg)
        from mempalace.mcp_server import tool_kg_query

        result = tool_kg_query(entity="Max")
        assert result["count"] > 0

    def test_kg_invalidate(self, monkeypatch, config, palace_path, seeded_kg):
        _patch_mcp_server(monkeypatch, config, palace_path, seeded_kg)
        from mempalace.mcp_server import tool_kg_invalidate

        result = tool_kg_invalidate(
            subject="Max",
            predicate="does",
            object="chess",
            ended="2026-03-01",
        )
        assert result["success"] is True

    def test_kg_timeline(self, monkeypatch, config, palace_path, seeded_kg):
        _patch_mcp_server(monkeypatch, config, palace_path, seeded_kg)
        from mempalace.mcp_server import tool_kg_timeline

        result = tool_kg_timeline(entity="Alice")
        assert result["count"] > 0

    def test_kg_stats(self, monkeypatch, config, palace_path, seeded_kg):
        _patch_mcp_server(monkeypatch, config, palace_path, seeded_kg)
        from mempalace.mcp_server import tool_kg_stats

        result = tool_kg_stats()
        assert result["entities"] >= 4


# ── Diary Tools ─────────────────────────────────────────────────────────


class TestDiaryTools:
    def test_diary_write_and_read(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _get_collection(palace_path, create=True)
        from mempalace.mcp_server import tool_diary_write, tool_diary_read

        w = tool_diary_write(
            agent_name="TestAgent",
            entry="Today we discussed authentication patterns.",
            topic="architecture",
        )
        assert w["success"] is True
        assert w["agent"] == "TestAgent"

        r = tool_diary_read(agent_name="TestAgent")
        assert r["total"] == 1
        assert r["entries"][0]["topic"] == "architecture"
        assert "authentication" in r["entries"][0]["content"]

    def test_diary_read_empty(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _get_collection(palace_path, create=True)
        from mempalace.mcp_server import tool_diary_read

        r = tool_diary_read(agent_name="Nobody")
        assert r["entries"] == []


# ── Input Validation ───────────────────────────────────────────────────


class TestAuth:
    def test_auth_disabled_no_token_needed(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace import mcp_server
        from mempalace.mcp_server import handle_request

        monkeypatch.setattr(mcp_server, "_auth_token", None)
        _get_collection(palace_path, create=True)

        resp = handle_request(
            {
                "method": "tools/call",
                "id": 200,
                "params": {"name": "mempalace_status", "arguments": {}},
            }
        )
        assert "result" in resp

    def test_auth_enabled_missing_token(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace import mcp_server
        from mempalace.mcp_server import handle_request

        monkeypatch.setattr(mcp_server, "_auth_token", "secret-token-123")

        resp = handle_request(
            {
                "method": "tools/call",
                "id": 201,
                "params": {"name": "mempalace_status", "arguments": {}},
            }
        )
        assert resp["error"]["code"] == -32001

    def test_auth_enabled_wrong_token(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace import mcp_server
        from mempalace.mcp_server import handle_request

        monkeypatch.setattr(mcp_server, "_auth_token", "secret-token-123")

        resp = handle_request(
            {
                "method": "tools/call",
                "id": 202,
                "params": {
                    "name": "mempalace_status",
                    "arguments": {},
                    "_meta": {"auth_token": "wrong-token"},
                },
            }
        )
        assert resp["error"]["code"] == -32001

    def test_auth_enabled_valid_token(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace import mcp_server
        from mempalace.mcp_server import handle_request

        monkeypatch.setattr(mcp_server, "_auth_token", "secret-token-123")
        _get_collection(palace_path, create=True)

        resp = handle_request(
            {
                "method": "tools/call",
                "id": 203,
                "params": {
                    "name": "mempalace_status",
                    "arguments": {},
                    "_meta": {"auth_token": "secret-token-123"},
                },
            }
        )
        assert "result" in resp

    def test_initialize_reports_auth_required(self, monkeypatch):
        from mempalace import mcp_server
        from mempalace.mcp_server import handle_request

        monkeypatch.setattr(mcp_server, "_auth_token", "some-token")

        resp = handle_request({"method": "initialize", "id": 204, "params": {}})
        assert resp["result"]["serverInfo"]["authRequired"] is True

    def test_initialize_no_auth_required_when_disabled(self, monkeypatch):
        from mempalace import mcp_server
        from mempalace.mcp_server import handle_request

        monkeypatch.setattr(mcp_server, "_auth_token", None)

        resp = handle_request({"method": "initialize", "id": 205, "params": {}})
        assert "authRequired" not in resp["result"]["serverInfo"]

    def test_tools_list_requires_auth(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace import mcp_server
        from mempalace.mcp_server import handle_request

        monkeypatch.setattr(mcp_server, "_auth_token", "secret-token-123")

        resp = handle_request(
            {"method": "tools/list", "id": 206, "params": {}}
        )
        assert resp["error"]["code"] == -32001


class TestInputValidation:
    def test_missing_required_field(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import handle_request

        resp = handle_request(
            {
                "method": "tools/call",
                "id": 100,
                "params": {
                    "name": "mempalace_search",
                    "arguments": {},  # missing required "query"
                },
            }
        )
        assert resp["error"]["code"] == -32602
        assert "query" in resp["error"]["message"]

    def test_extra_unknown_field_rejected(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import handle_request

        resp = handle_request(
            {
                "method": "tools/call",
                "id": 101,
                "params": {
                    "name": "mempalace_search",
                    "arguments": {"query": "test", "bogus_field": "nope"},
                },
            }
        )
        assert resp["error"]["code"] == -32602
        assert "bogus_field" in resp["error"]["message"]

    def test_content_size_limit_exceeded(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        # Set a very small limit for testing
        config._file_config["security"] = {"max_content_size": 100}
        from mempalace.mcp_server import handle_request

        resp = handle_request(
            {
                "method": "tools/call",
                "id": 102,
                "params": {
                    "name": "mempalace_add_drawer",
                    "arguments": {
                        "wing": "test",
                        "room": "test",
                        "content": "x" * 200,
                    },
                },
            }
        )
        assert resp["error"]["code"] == -32000
        assert "max size" in resp["error"]["message"]

    def test_content_within_size_limit(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _get_collection(palace_path, create=True)
        from mempalace.mcp_server import handle_request

        resp = handle_request(
            {
                "method": "tools/call",
                "id": 103,
                "params": {
                    "name": "mempalace_add_drawer",
                    "arguments": {
                        "wing": "test",
                        "room": "test",
                        "content": "Small content that fits.",
                    },
                },
            }
        )
        assert "result" in resp


# ── Encryption ─────────────────────────────────────────────────────────


class TestEncryption:
    def _enable_encryption(self, monkeypatch):
        from cryptography.fernet import Fernet
        from mempalace import mcp_server

        f = Fernet(Fernet.generate_key())
        monkeypatch.setattr(mcp_server, "_fernet", f)
        return f

    def test_add_drawer_stores_encrypted_content(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        f = self._enable_encryption(monkeypatch)
        col = _get_collection(palace_path, create=True)
        from mempalace.mcp_server import tool_add_drawer

        result = tool_add_drawer(
            wing="enc_test",
            room="secrets",
            content="Top secret family information.",
        )
        assert result["success"] is True

        # Verify encrypted_content is in metadata
        stored = col.get(ids=[result["drawer_id"]], include=["metadatas"])
        meta = stored["metadatas"][0]
        assert "encrypted_content" in meta
        assert meta["encrypted_content"] != "Top secret family information."

        # Verify it decrypts correctly
        from mempalace.security import decrypt

        assert decrypt(f, meta["encrypted_content"]) == "Top secret family information."

    def test_search_returns_decrypted_content(
        self, monkeypatch, config, palace_path, kg
    ):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        f = self._enable_encryption(monkeypatch)
        _get_collection(palace_path, create=True)
        from mempalace.mcp_server import tool_add_drawer, tool_search

        tool_add_drawer(
            wing="enc_test",
            room="secrets",
            content="The encryption key is stored in the OS keychain for safety.",
        )

        result = tool_search(query="encryption key keychain")
        assert len(result["results"]) > 0
        top = result["results"][0]
        assert "encryption key" in top["text"].lower() or "keychain" in top["text"].lower()

    def test_diary_write_read_encrypted_roundtrip(
        self, monkeypatch, config, palace_path, kg
    ):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        self._enable_encryption(monkeypatch)
        _get_collection(palace_path, create=True)
        from mempalace.mcp_server import tool_diary_read, tool_diary_write

        w = tool_diary_write(
            agent_name="SecureAgent",
            entry="Encrypted diary: today we added Fernet encryption.",
            topic="security",
        )
        assert w["success"] is True

        r = tool_diary_read(agent_name="SecureAgent")
        assert r["total"] == 1
        assert "Fernet encryption" in r["entries"][0]["content"]

    def test_unencrypted_drawers_still_readable(
        self, monkeypatch, config, palace_path, seeded_collection, kg
    ):
        """Drawers added before encryption was enabled should still be readable."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        self._enable_encryption(monkeypatch)
        from mempalace.mcp_server import tool_search

        # seeded_collection has drawers without encrypted_content
        result = tool_search(query="JWT authentication")
        assert len(result["results"]) > 0
        assert "JWT" in result["results"][0]["text"]
