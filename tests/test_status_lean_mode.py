"""
test_status_lean_mode.py — A5 (RFC-0028 §4.5).

Pre-fix, ``tool_status`` returned the palace overview with the entire
PALACE_PROTOCOL prose, the AAAK_SPEC dialect, the per-room dict (130
rows in a mature palace), and ``palace_path``. The payload measured
~6KB on every call. Most workflows that call ``status`` only need a
"is the palace alive and how big is it" health check — paying 6KB for
that on every invocation is waste.

Post-fix:
- ``full=False`` (default) → lean payload: total_drawers, per-wing
  counts, ``rooms_count`` (single integer), ``lean: True`` marker.
  No protocol prose, no AAAK, no palace_path.
- ``full=True`` → historical payload minus ``aaak_dialect`` (which now
  lives in ``get_aaak_spec`` only — the inline duplicate doubled
  payload size whenever an LLM caller noticed the field).

The existing ``test_mcp_server.TestStatusTool`` tests still call
``tool_status()`` with no arguments and assert on ``total_drawers`` /
``wings``; those keys are preserved in the lean payload so prior tests
keep passing without modification.
"""

import json


def test_lean_status_payload_under_2kb(
    monkeypatch, config, palace_path, seeded_collection, kg
):
    """Default lean status payload is well under 2KB."""
    from mempalace import mcp_server

    monkeypatch.setattr(mcp_server, "_config", config)
    monkeypatch.setattr(mcp_server, "_kg", kg)

    result = mcp_server.tool_status()
    payload_bytes = len(json.dumps(result).encode("utf-8"))
    assert payload_bytes < 2048, f"lean status was {payload_bytes} bytes"


def test_lean_status_omits_protocol_and_aaak(
    monkeypatch, config, palace_path, seeded_collection, kg
):
    """Lean status drops the protocol prose, AAAK dialect, palace_path, and per-room dict."""
    from mempalace import mcp_server

    monkeypatch.setattr(mcp_server, "_config", config)
    monkeypatch.setattr(mcp_server, "_kg", kg)

    result = mcp_server.tool_status()
    assert result["lean"] is True
    assert "protocol" not in result
    assert "aaak_dialect" not in result
    assert "palace_path" not in result
    assert "rooms" not in result, "lean must collapse the per-room dict"
    assert "rooms_count" in result
    assert isinstance(result["rooms_count"], int)


def test_lean_status_preserves_total_drawers_and_wings(
    monkeypatch, config, palace_path, seeded_collection, kg
):
    """Lean status keeps the keys prior callers (and the existing test suite) rely on."""
    from mempalace import mcp_server

    monkeypatch.setattr(mcp_server, "_config", config)
    monkeypatch.setattr(mcp_server, "_kg", kg)

    result = mcp_server.tool_status()
    assert result["total_drawers"] == 4
    assert "project" in result["wings"]
    assert "notes" in result["wings"]


def test_full_status_returns_palace_path_and_protocol(
    monkeypatch, config, palace_path, seeded_collection, kg
):
    """``full=True`` returns the historical shape (minus aaak_dialect)."""
    from mempalace import mcp_server

    monkeypatch.setattr(mcp_server, "_config", config)
    monkeypatch.setattr(mcp_server, "_kg", kg)

    result = mcp_server.tool_status(full=True)
    assert "palace_path" in result
    assert "protocol" in result
    assert "rooms" in result
    assert isinstance(result["rooms"], dict)
    # AAAK lives in get_aaak_spec only — the inline duplicate is gone.
    assert "aaak_dialect" not in result, (
        "full status must not duplicate AAAK; that's mempalace_get_aaak_spec's job"
    )


def test_status_descriptor_exposes_full_flag():
    """The MCP TOOLS descriptor must declare the new ``full`` parameter."""
    from mempalace.mcp_server import TOOLS

    schema = TOOLS["mempalace_status"]["input_schema"]
    assert "full" in schema["properties"]
    assert schema["properties"]["full"]["type"] == "boolean"
