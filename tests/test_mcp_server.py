import json

import pytest
from mempalace.config import MempalaceConfig
from mempalace.knowledge_graph import KnowledgeGraph


@pytest.fixture
def mcp_server(tmp_dir):
    """Patch mcp_server module globals to use temp dirs, restore after test."""
    palace_path = str(tmp_dir / "palace")
    config_dir = tmp_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.json").write_text(json.dumps({"palace_path": palace_path}))
    config = MempalaceConfig(config_dir=str(config_dir))
    kg = KnowledgeGraph(db_path=str(tmp_dir / "kg.db"))

    import mempalace.mcp_server as mcp

    original_config, original_kg = mcp._config, mcp._kg
    mcp._config = config
    mcp._kg = kg
    yield mcp
    mcp._config = original_config
    mcp._kg = original_kg


def test_handle_initialize(mcp_server):
    resp = mcp_server.handle_request({"method": "initialize", "id": 1, "params": {}})
    assert resp["id"] == 1
    assert resp["result"]["serverInfo"]["name"] == "mempalace"


def test_handle_tools_list(mcp_server):
    resp = mcp_server.handle_request({"method": "tools/list", "id": 2, "params": {}})
    tools = resp["result"]["tools"]
    tool_names = {t["name"] for t in tools}
    assert "mempalace_search" in tool_names
    assert "mempalace_add_drawer" in tool_names
    assert "mempalace_kg_query" in tool_names
    assert len(tools) == len(mcp_server.TOOLS)


def test_handle_unknown_tool(mcp_server):
    resp = mcp_server.handle_request(
        {
            "method": "tools/call",
            "id": 3,
            "params": {"name": "nonexistent_tool", "arguments": {}},
        }
    )
    assert "error" in resp
    assert resp["error"]["code"] == -32601


def test_handle_unknown_method(mcp_server):
    resp = mcp_server.handle_request({"method": "bogus/method", "id": 4, "params": {}})
    assert "error" in resp


def test_tool_add_and_delete_drawer(mcp_server):
    resp = mcp_server.handle_request(
        {
            "method": "tools/call",
            "id": 5,
            "params": {
                "name": "mempalace_add_drawer",
                "arguments": {"wing": "test", "room": "misc", "content": "Hello from test"},
            },
        }
    )
    result = json.loads(resp["result"]["content"][0]["text"])
    assert result["success"] is True
    drawer_id = result["drawer_id"]

    resp = mcp_server.handle_request(
        {
            "method": "tools/call",
            "id": 6,
            "params": {
                "name": "mempalace_delete_drawer",
                "arguments": {"drawer_id": drawer_id},
            },
        }
    )
    result = json.loads(resp["result"]["content"][0]["text"])
    assert result["success"] is True


def test_tool_delete_nonexistent(mcp_server):
    mcp_server.handle_request(
        {
            "method": "tools/call",
            "id": 7,
            "params": {
                "name": "mempalace_add_drawer",
                "arguments": {"wing": "x", "room": "y", "content": "seed"},
            },
        }
    )
    resp = mcp_server.handle_request(
        {
            "method": "tools/call",
            "id": 8,
            "params": {
                "name": "mempalace_delete_drawer",
                "arguments": {"drawer_id": "nonexistent_id"},
            },
        }
    )
    result = json.loads(resp["result"]["content"][0]["text"])
    assert result["success"] is False


def test_tool_kg_add_and_query(mcp_server):
    mcp_server.handle_request(
        {
            "method": "tools/call",
            "id": 9,
            "params": {
                "name": "mempalace_kg_add",
                "arguments": {"subject": "Max", "predicate": "loves", "object": "chess"},
            },
        }
    )

    resp = mcp_server.handle_request(
        {
            "method": "tools/call",
            "id": 10,
            "params": {
                "name": "mempalace_kg_query",
                "arguments": {"entity": "Max"},
            },
        }
    )
    result = json.loads(resp["result"]["content"][0]["text"])
    assert result["count"] >= 1
    assert any(f["predicate"] == "loves" for f in result["facts"])


def test_tool_check_duplicate_is_duplicate(mcp_server):
    # Add a drawer first
    mcp_server.handle_request(
        {
            "method": "tools/call",
            "id": 20,
            "params": {
                "name": "mempalace_add_drawer",
                "arguments": {
                    "wing": "test",
                    "room": "dup",
                    "content": "The quick brown fox jumps over the lazy dog near the riverbank",
                },
            },
        }
    )
    # Check duplicate with identical content
    resp = mcp_server.handle_request(
        {
            "method": "tools/call",
            "id": 21,
            "params": {
                "name": "mempalace_check_duplicate",
                "arguments": {
                    "content": "The quick brown fox jumps over the lazy dog near the riverbank"
                },
            },
        }
    )
    result = json.loads(resp["result"]["content"][0]["text"])
    assert result["is_duplicate"] is True
    assert len(result["matches"]) >= 1


def test_tool_check_duplicate_not_duplicate(mcp_server):
    # Add a drawer with one topic
    mcp_server.handle_request(
        {
            "method": "tools/call",
            "id": 22,
            "params": {
                "name": "mempalace_add_drawer",
                "arguments": {
                    "wing": "test",
                    "room": "unique",
                    "content": "PostgreSQL database migration strategy with Alembic",
                },
            },
        }
    )
    # Check with completely different content — should not be a duplicate
    resp = mcp_server.handle_request(
        {
            "method": "tools/call",
            "id": 23,
            "params": {
                "name": "mempalace_check_duplicate",
                "arguments": {
                    "content": "Riley scored three goals in the championship football match on Saturday afternoon"
                },
            },
        }
    )
    result = json.loads(resp["result"]["content"][0]["text"])
    assert result["is_duplicate"] is False


def test_tool_traverse_graph(mcp_server):
    # Populate the palace with rooms that share a wing so the graph has nodes
    mcp_server.handle_request(
        {
            "method": "tools/call",
            "id": 24,
            "params": {
                "name": "mempalace_add_drawer",
                "arguments": {
                    "wing": "code",
                    "room": "backend",
                    "content": "FastAPI backend with PostgreSQL and authentication middleware",
                },
            },
        }
    )
    mcp_server.handle_request(
        {
            "method": "tools/call",
            "id": 25,
            "params": {
                "name": "mempalace_add_drawer",
                "arguments": {
                    "wing": "code",
                    "room": "frontend",
                    "content": "React frontend with TanStack Query for server state management",
                },
            },
        }
    )
    resp = mcp_server.handle_request(
        {
            "method": "tools/call",
            "id": 26,
            "params": {
                "name": "mempalace_traverse",
                "arguments": {"start_room": "backend", "max_hops": 1},
            },
        }
    )
    result = json.loads(resp["result"]["content"][0]["text"])
    # traverse returns a list of room nodes; first entry is the start room
    assert isinstance(result, list)
    assert len(result) >= 1
    assert result[0]["room"] == "backend"


def test_tool_graph_stats(mcp_server):
    # Add a couple of drawers to ensure the graph has data
    mcp_server.handle_request(
        {
            "method": "tools/call",
            "id": 27,
            "params": {
                "name": "mempalace_add_drawer",
                "arguments": {
                    "wing": "project",
                    "room": "planning",
                    "content": "Sprint planning notes for Q2 milestones and database refactor",
                },
            },
        }
    )
    mcp_server.handle_request(
        {
            "method": "tools/call",
            "id": 28,
            "params": {
                "name": "mempalace_add_drawer",
                "arguments": {
                    "wing": "project",
                    "room": "backend",
                    "content": "API rate limiting implementation with Redis and token buckets",
                },
            },
        }
    )
    resp = mcp_server.handle_request(
        {
            "method": "tools/call",
            "id": 29,
            "params": {
                "name": "mempalace_graph_stats",
                "arguments": {},
            },
        }
    )
    result = json.loads(resp["result"]["content"][0]["text"])
    assert "total_rooms" in result
    assert "tunnel_rooms" in result
    assert "total_edges" in result
    assert "rooms_per_wing" in result
    assert result["total_rooms"] >= 1


def test_tool_diary_write_and_read(mcp_server):
    mcp_server.handle_request(
        {
            "method": "tools/call",
            "id": 11,
            "params": {
                "name": "mempalace_diary_write",
                "arguments": {
                    "agent_name": "Atlas",
                    "entry": "SESSION:test|built.tests",
                    "topic": "testing",
                },
            },
        }
    )

    resp = mcp_server.handle_request(
        {
            "method": "tools/call",
            "id": 12,
            "params": {
                "name": "mempalace_diary_read",
                "arguments": {"agent_name": "Atlas"},
            },
        }
    )
    result = json.loads(resp["result"]["content"][0]["text"])
    assert result["total"] >= 1
    assert result["entries"][0]["content"] == "SESSION:test|built.tests"
