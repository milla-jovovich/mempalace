"""Tests for mcp_server.py — verifies _validate_tool_args param validation."""

from mempalace.mcp_server import _validate_tool_args, TOOLS


def test_validate_passes_valid_args():
    """Valid args for search tool should return None (no error)."""
    result = _validate_tool_args(
        "mempalace_search", {"query": "test search"}, req_id=1
    )
    assert result is None


def test_validate_rejects_missing_required():
    """Missing 'query' param should return JSON-RPC error."""
    result = _validate_tool_args("mempalace_search", {}, req_id=1)
    assert result is not None
    assert result["error"]["code"] == -32602
    assert "query" in result["error"]["message"]


def test_validate_rejects_wrong_type():
    """Passing integer for 'query' (expects string) should return error."""
    result = _validate_tool_args(
        "mempalace_search", {"query": 42}, req_id=1
    )
    assert result is not None
    assert result["error"]["code"] == -32602
    assert "string" in result["error"]["message"]


def test_validate_passes_optional_params():
    """Optional params with correct types should pass."""
    result = _validate_tool_args(
        "mempalace_search",
        {"query": "test", "limit": 10, "wing": "myproject"},
        req_id=1,
    )
    assert result is None


def test_validate_rejects_wrong_optional_type():
    """Optional param with wrong type should still be rejected."""
    result = _validate_tool_args(
        "mempalace_search",
        {"query": "test", "limit": "not_a_number"},
        req_id=1,
    )
    assert result is not None
    assert "integer" in result["error"]["message"]


def test_validate_number_type_accepts_int_and_float():
    """Number type should accept both int and float."""
    # check_duplicate has threshold as "number" type
    result_int = _validate_tool_args(
        "mempalace_check_duplicate",
        {"content": "test", "threshold": 1},
        req_id=1,
    )
    result_float = _validate_tool_args(
        "mempalace_check_duplicate",
        {"content": "test", "threshold": 0.9},
        req_id=1,
    )
    assert result_int is None
    assert result_float is None


def test_validate_ignores_unknown_params():
    """Extra params not in schema should be ignored (not rejected)."""
    result = _validate_tool_args(
        "mempalace_search",
        {"query": "test", "unknown_param": "value"},
        req_id=1,
    )
    assert result is None


def test_validate_tool_with_no_required():
    """Tools with no required params should pass with empty args."""
    result = _validate_tool_args("mempalace_status", {}, req_id=1)
    assert result is None
