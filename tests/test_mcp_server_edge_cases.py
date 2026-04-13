"""Additional branch coverage for the MCP server's error and protocol edges."""

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from mempalace import mcp_server


def _load_isolated_mcp_module(module_name: str) -> object:
    """Execute a fresh copy of mcp_server without mutating the canonical import."""
    spec = importlib.util.spec_from_file_location(module_name, Path(mcp_server.__file__))
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.pop(module_name, None)


def test_import_honors_palace_override_and_tolerates_wal_chmod_failures(monkeypatch, tmp_path):
    """Import-time setup is branch-heavy, so probe it in an isolated module copy."""
    wal_dir = tmp_path / ".mempalace" / "wal"
    wal_dir.mkdir(parents=True)
    (wal_dir / "write_log.jsonl").write_text("{}", encoding="utf-8")

    custom_palace = tmp_path / "custom-palace"
    fake_config = SimpleNamespace(
        palace_path=str(custom_palace),
        collection_name="mempalace_drawers",
    )

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    with (
        patch(
            "argparse.ArgumentParser.parse_known_args",
            return_value=(SimpleNamespace(palace=str(custom_palace)), []),
        ),
        patch("mempalace.config.MempalaceConfig", return_value=fake_config),
        patch("mempalace.knowledge_graph.KnowledgeGraph") as mock_kg,
        patch.object(Path, "chmod", side_effect=NotImplementedError),
    ):
        probe = _load_isolated_mcp_module("mempalace._mcp_server_import_probe")

    assert os.environ["MEMPALACE_PALACE_PATH"] == os.path.abspath(custom_palace)
    mock_kg.assert_called_once_with(
        db_path=os.path.join(fake_config.palace_path, "knowledge_graph.sqlite3")
    )
    assert probe._args.palace == str(custom_palace)


def test_wal_log_reports_write_failures():
    with patch("mempalace.mcp_server.os.open", side_effect=OSError("disk full")), patch.object(
        mcp_server.logger, "error"
    ) as mock_error:
        mcp_server._wal_log("add_drawer", {"content_preview": "secret"})

    assert "WAL write failed" in mock_error.call_args[0][0]


def test_get_cached_metadata_uses_hot_cache(monkeypatch):
    fake_col = object()
    monkeypatch.setattr(mcp_server, "_metadata_cache", [{"wing": "project"}])
    monkeypatch.setattr(mcp_server, "_metadata_cache_time", mcp_server.time.time())
    with patch("mempalace.mcp_server._fetch_all_metadata") as mock_fetch:
        result = mcp_server._get_cached_metadata(fake_col)

    assert result == [{"wing": "project"}]
    mock_fetch.assert_not_called()


def test_tool_status_reports_agent_loading_errors(monkeypatch):
    fake_col = MagicMock()
    fake_col.count.return_value = 0
    monkeypatch.setattr(mcp_server, "_get_collection", lambda create=False: fake_col)
    monkeypatch.setattr(mcp_server, "_get_cached_metadata", lambda col: [])

    with patch("mempalace.mcp_server.list_agents", side_effect=RuntimeError("broken registry")):
        result = mcp_server.tool_status()

    assert result["specialist_agents_error"] == "broken registry"


def test_tool_status_returns_partial_on_metadata_failure(monkeypatch):
    fake_col = MagicMock()
    fake_col.count.return_value = 2
    monkeypatch.setattr(mcp_server, "_get_collection", lambda create=False: fake_col)
    with (
        patch("mempalace.mcp_server.list_agents", return_value={"count": 0, "agents": []}),
        patch("mempalace.mcp_server._get_cached_metadata", side_effect=RuntimeError("sqlite")),
    ):
        result = mcp_server.tool_status()

    assert result["partial"] is True
    assert result["error"] == "sqlite"


@pytest.mark.parametrize(
    ("func", "kwargs"),
    [
        (mcp_server.tool_list_wings, {}),
        (mcp_server.tool_list_rooms, {}),
        (mcp_server.tool_get_taxonomy, {}),
        (mcp_server.tool_traverse_graph, {"start_room": "backend"}),
        (mcp_server.tool_find_tunnels, {}),
        (mcp_server.tool_graph_stats, {}),
        (mcp_server.tool_check_duplicate, {"content": "hello"}),
        (mcp_server.tool_delete_drawer, {"drawer_id": "drawer_x"}),
        (mcp_server.tool_get_drawer, {"drawer_id": "drawer_x"}),
        (mcp_server.tool_list_drawers, {}),
        (mcp_server.tool_diary_read, {"agent_name": "reader"}),
    ],
)
def test_tools_return_no_palace_when_collection_is_missing(monkeypatch, func, kwargs):
    monkeypatch.setattr(mcp_server, "_get_collection", lambda create=False: None)
    result = func(**kwargs)
    assert result["error"] == "No palace found"


def test_collection_read_tools_return_partial_errors(monkeypatch):
    fake_col = MagicMock()
    monkeypatch.setattr(mcp_server, "_get_collection", lambda create=False: fake_col)

    with patch("mempalace.mcp_server._get_cached_metadata", side_effect=RuntimeError("boom")):
        wings = mcp_server.tool_list_wings()
        taxonomy = mcp_server.tool_get_taxonomy()

    with patch("mempalace.mcp_server._fetch_all_metadata", side_effect=RuntimeError("boom")):
        rooms = mcp_server.tool_list_rooms(wing="project")

    assert wings["partial"] is True and wings["error"] == "boom"
    assert taxonomy["partial"] is True and taxonomy["error"] == "boom"
    assert rooms["partial"] is True and rooms["error"] == "boom"


def test_tool_search_adds_sanitizer_details_and_context(monkeypatch):
    monkeypatch.setattr(
        mcp_server,
        "sanitize_query",
        lambda query: {
            "clean_query": "auth migration",
            "was_sanitized": True,
            "method": "question_extraction",
            "original_length": 999,
            "clean_length": 14,
        },
    )
    monkeypatch.setattr(mcp_server, "search_memories", lambda *args, **kwargs: {"results": []})

    result = mcp_server.tool_search("ignored", context="background")

    assert result["query_sanitized"] is True
    assert result["context_received"] is True
    assert result["sanitizer"]["clean_query"] == "auth migration"


def test_tool_check_duplicate_returns_errors_on_query_failures(monkeypatch):
    fake_col = MagicMock()
    fake_col.query.side_effect = RuntimeError("vector fail")
    monkeypatch.setattr(mcp_server, "_get_collection", lambda create=False: fake_col)

    result = mcp_server.tool_check_duplicate("some content")

    assert result == {"error": "Duplicate check failed"}


def test_get_aaak_spec_returns_protocol_text():
    result = mcp_server.tool_get_aaak_spec()
    assert "aaak_spec" in result
    assert "FORMAT" in result["aaak_spec"]


def test_graph_wrapper_tools_delegate_when_collection_exists(monkeypatch):
    fake_col = object()
    monkeypatch.setattr(mcp_server, "_get_collection", lambda create=False: fake_col)
    monkeypatch.setattr(mcp_server, "traverse", lambda room, col, max_hops: {"room": room})
    monkeypatch.setattr(mcp_server, "find_tunnels", lambda wing_a, wing_b, col: {"count": 1})
    monkeypatch.setattr(mcp_server, "graph_stats", lambda col: {"nodes": 2})

    assert mcp_server.tool_traverse_graph("backend", max_hops=99) == {"room": "backend"}
    assert mcp_server.tool_find_tunnels("a", "b") == {"count": 1}
    assert mcp_server.tool_graph_stats() == {"nodes": 2}


def test_tool_add_drawer_validation_and_storage_errors(monkeypatch):
    assert mcp_server.tool_add_drawer("../bad", "room", "content")["success"] is False

    monkeypatch.setattr(mcp_server, "_get_collection", lambda create=False: None)
    no_palace = mcp_server.tool_add_drawer("wing", "room", "content")
    assert no_palace["error"] == "No palace found"

    fake_col = MagicMock()
    fake_col.get.side_effect = RuntimeError("lookup failed")
    fake_col.upsert.side_effect = RuntimeError("upsert failed")
    monkeypatch.setattr(mcp_server, "_get_collection", lambda create=False: fake_col)

    result = mcp_server.tool_add_drawer("wing", "room", "content")

    assert result["success"] is False
    assert result["error"] == "upsert failed"


def test_tool_get_delete_list_and_update_drawer_error_paths(monkeypatch):
    get_fail_col = MagicMock()
    get_fail_col.get.side_effect = RuntimeError("read failed")
    list_fail_col = MagicMock()
    list_fail_col.get.side_effect = RuntimeError("list failed")
    delete_fail_col = MagicMock()
    delete_fail_col.get.return_value = {
        "ids": ["drawer_x"],
        "documents": ["text"],
        "metadatas": [{"wing": "w", "room": "r"}],
    }
    delete_fail_col.delete.side_effect = RuntimeError("delete failed")
    update_fail_col = MagicMock()
    update_fail_col.get.side_effect = RuntimeError("update failed")

    monkeypatch.setattr(mcp_server, "_get_collection", lambda create=False: get_fail_col)
    assert mcp_server.tool_get_drawer("drawer_x")["error"] == "read failed"

    monkeypatch.setattr(mcp_server, "_get_collection", lambda create=False: list_fail_col)
    assert mcp_server.tool_list_drawers()["error"] == "list failed"

    monkeypatch.setattr(mcp_server, "_get_collection", lambda create=False: delete_fail_col)
    assert mcp_server.tool_delete_drawer("drawer_x")["error"] == "delete failed"

    monkeypatch.setattr(mcp_server, "_get_collection", lambda create=False: None)
    assert mcp_server.tool_update_drawer("drawer_x", content="new")["error"] == "No palace found"

    monkeypatch.setattr(mcp_server, "_get_collection", lambda create=False: update_fail_col)
    assert mcp_server.tool_update_drawer("drawer_x", content="new")["error"] == "update failed"


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"content": ""}, "content must be a non-empty string"),
        ({"wing": "../bad"}, "wing contains invalid path characters"),
        ({"room": "../bad"}, "room contains invalid path characters"),
    ],
)
def test_tool_update_drawer_validates_inputs_before_update(monkeypatch, kwargs, expected):
    fake_col = MagicMock()
    fake_col.get.return_value = {
        "ids": ["drawer_x"],
        "documents": ["old content"],
        "metadatas": [{"wing": "wing", "room": "room"}],
    }
    monkeypatch.setattr(mcp_server, "_get_collection", lambda create=False: fake_col)

    result = mcp_server.tool_update_drawer("drawer_x", **kwargs)

    assert result["success"] is False
    assert expected in result["error"]


@pytest.mark.parametrize(
    ("func", "kwargs"),
    [
        (mcp_server.tool_kg_query, {"entity": "../bad"}),
        (mcp_server.tool_kg_check, {"subject": "../bad", "predicate": "likes", "object": "tea"}),
        (mcp_server.tool_kg_add, {"subject": "../bad", "predicate": "likes", "object": "tea"}),
        (
            mcp_server.tool_kg_invalidate,
            {"subject": "../bad", "predicate": "likes", "object": "tea"},
        ),
        (mcp_server.tool_kg_timeline, {"entity": "../bad"}),
    ],
)
def test_kg_tools_reject_invalid_names(func, kwargs):
    result = func(**kwargs)
    assert "error" in result


def test_kg_query_rejects_invalid_direction():
    result = mcp_server.tool_kg_query(entity="Alice", direction="sideways")
    assert result["error"] == "direction must be 'outgoing', 'incoming', or 'both'"


def test_diary_tools_cover_validation_and_storage_failures(monkeypatch):
    assert mcp_server.tool_diary_write("Agent", "")["success"] is False
    assert "error" in mcp_server.tool_diary_read("../bad")

    monkeypatch.setattr(mcp_server, "_get_collection", lambda create=False: None)
    no_palace = mcp_server.tool_diary_write("Agent", "Entry that is long enough to be valid.")
    assert no_palace["error"] == "No palace found"

    write_fail_col = MagicMock()
    write_fail_col.add.side_effect = RuntimeError("disk full")
    read_fail_col = MagicMock()
    read_fail_col.get.side_effect = RuntimeError("broken")

    monkeypatch.setattr(mcp_server, "_get_collection", lambda create=False: write_fail_col)
    result = mcp_server.tool_diary_write("Agent", "Entry that is long enough to be valid.")
    assert result["success"] is False
    assert result["error"] == "disk full"

    monkeypatch.setattr(mcp_server, "_get_collection", lambda create=False: read_fail_col)
    result = mcp_server.tool_diary_read("Agent")
    assert result == {"error": "Failed to read diary entries"}


def test_hook_settings_handles_config_errors():
    with patch("mempalace.config.MempalaceConfig", side_effect=RuntimeError("no config")):
        result = mcp_server.tool_hook_settings()
    assert result == {"success": False, "error": "no config"}


def test_hook_settings_handles_persist_failures():
    fake_config = MagicMock()
    fake_config.set_hook_setting.side_effect = OSError("read-only")
    fake_config.hook_silent_save = True
    fake_config.hook_desktop_toast = False

    with patch("mempalace.config.MempalaceConfig", return_value=fake_config):
        result = mcp_server.tool_hook_settings(desktop_toast=True)

    assert result["success"] is False
    assert "Failed to persist hook settings" in result["error"]


def test_hook_settings_succeeds_even_if_reread_fails():
    fake_config = MagicMock()
    fake_config.hook_silent_save = True
    fake_config.hook_desktop_toast = False

    with patch("mempalace.config.MempalaceConfig", side_effect=[fake_config, RuntimeError("boom")]):
        result = mcp_server.tool_hook_settings()

    assert result["success"] is True
    assert result["settings"] == {"silent_save": True, "desktop_toast": False}


def test_hook_settings_records_desktop_toast_updates():
    fake_config = MagicMock()
    fake_config.hook_silent_save = True
    fake_config.hook_desktop_toast = True

    with patch("mempalace.config.MempalaceConfig", return_value=fake_config):
        result = mcp_server.tool_hook_settings(desktop_toast=True)

    assert "desktop_toast → True" in result["updated"]


def test_memories_filed_away_covers_quiet_ok_and_error(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    quiet = mcp_server.tool_memories_filed_away()
    assert quiet["status"] == "quiet"

    state_dir = tmp_path / ".mempalace" / "hook_state"
    state_dir.mkdir(parents=True)
    ack_file = state_dir / "last_checkpoint"
    ack_file.write_text(json.dumps({"msgs": 3, "ts": "2026-04-12T12:00:00"}), encoding="utf-8")

    ok = mcp_server.tool_memories_filed_away()
    assert ok["status"] == "ok"
    assert ok["count"] == 3
    assert not ack_file.exists()

    ack_file.write_text("{not-json", encoding="utf-8")
    bad = mcp_server.tool_memories_filed_away()
    assert bad["status"] == "error"
    assert not ack_file.exists()


def test_handle_request_coerces_numeric_arguments_and_strips_unknowns(monkeypatch):
    calls = {}

    def handler(limit, ratio):
        calls["args"] = (limit, ratio)
        calls["types"] = (type(limit), type(ratio))
        return {"limit": limit, "ratio": ratio}

    monkeypatch.setitem(
        mcp_server.TOOLS,
        "test_numeric",
        {
            "description": "test",
            "input_schema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                    "ratio": {"type": "number"},
                },
            },
            "handler": handler,
        },
    )

    response = mcp_server.handle_request(
        {
            "method": "tools/call",
            "id": 7,
            "params": {
                "name": "test_numeric",
                "arguments": {
                    "limit": "5",
                    "ratio": "1.25",
                    "ignored": "nope",
                    "wait_for_previous": True,
                },
            },
        }
    )

    payload = json.loads(response["result"]["content"][0]["text"])
    assert calls["args"] == (5, 1.25)
    assert calls["types"] == (int, float)
    assert payload == {"limit": 5, "ratio": 1.25}


def test_handle_request_rejects_bad_numeric_arguments(monkeypatch):
    monkeypatch.setitem(
        mcp_server.TOOLS,
        "test_bad_numeric",
        {
            "description": "test",
            "input_schema": {
                "type": "object",
                "properties": {"limit": {"type": "integer"}},
            },
            "handler": lambda limit: {"limit": limit},
        },
    )

    response = mcp_server.handle_request(
        {
            "method": "tools/call",
            "id": 8,
            "params": {"name": "test_bad_numeric", "arguments": {"limit": "oops"}},
        }
    )

    assert response["error"]["code"] == -32602


def test_handle_request_returns_internal_tool_error(monkeypatch):
    monkeypatch.setitem(
        mcp_server.TOOLS,
        "test_boom",
        {
            "description": "test",
            "input_schema": {"type": "object", "properties": {}},
            "handler": MagicMock(side_effect=RuntimeError("boom")),
        },
    )

    response = mcp_server.handle_request(
        {"method": "tools/call", "id": 9, "params": {"name": "test_boom", "arguments": {}}}
    )

    assert response["error"]["code"] == -32000


def test_main_processes_requests_and_skips_blank_lines(monkeypatch):
    fake_stdin = MagicMock()
    fake_stdin.readline.side_effect = [
        "\n",
        json.dumps({"method": "ping", "id": 1, "params": {}}) + "\n",
        "",
    ]
    fake_stdout = MagicMock()

    monkeypatch.setattr(mcp_server.sys, "stdin", fake_stdin)
    monkeypatch.setattr(mcp_server.sys, "stdout", fake_stdout)
    monkeypatch.setattr(mcp_server, "handle_request", lambda request: {"ok": True, "id": request["id"]})

    mcp_server.main()

    fake_stdout.write.assert_called_once_with(json.dumps({"ok": True, "id": 1}) + "\n")
    fake_stdout.flush.assert_called_once()


def test_main_logs_errors_and_exits_on_keyboard_interrupt(monkeypatch):
    fake_stdin = MagicMock()
    fake_stdin.readline.side_effect = ['{not-json}\n', KeyboardInterrupt()]

    monkeypatch.setattr(mcp_server.sys, "stdin", fake_stdin)
    with patch.object(mcp_server.logger, "error") as mock_error:
        mcp_server.main()

    assert "Server error" in mock_error.call_args[0][0]
