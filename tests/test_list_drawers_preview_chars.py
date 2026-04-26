"""
test_list_drawers_preview_chars.py — A3 (RFC-0028 §4.3).

Pre-fix, ``tool_list_drawers`` sliced ``content_preview`` to a hardcoded
200 characters. Any drawer whose relevant content sat past 200 chars
required a follow-up ``mempalace_get_drawer`` round-trip. The new
``preview_chars`` parameter (range 50..2000) lets callers right-size the
preview without re-fetching every drawer in full.
"""


def _seed_long_drawer(palace_path):
    """Seed a single drawer whose content is well past the default 200-char slice."""
    import chromadb

    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_or_create_collection(
        "mempalace_drawers", metadata={"hnsw:space": "cosine"}
    )
    long_content = (
        "Sprint review covered authentication migration to passkeys, "
        "database connection pooling tuning, and the new observability "
        "stack. The team also discussed deprecating the legacy session-"
        "token format by Q3 with a backwards-compatibility window of "
        "exactly 90 days. The migration plan ships as RFC-0099 with two "
        "alternates documented for the case where browser passkey support "
        "lags. " * 8
    )
    assert len(long_content) > 2200
    col.add(
        ids=["drawer_long_aaa"],
        documents=[long_content],
        metadatas=[
            {
                "wing": "test",
                "room": "long",
                "source_file": "review.md",
                "chunk_index": 0,
                "filed_at": "2026-04-26T00:00:00",
            }
        ],
    )
    del client
    return long_content


def test_default_preview_chars_unchanged(monkeypatch, config, palace_path, kg):
    """Default behaviour matches pre-fix: 200-character preview."""
    from mempalace import mcp_server

    monkeypatch.setattr(mcp_server, "_config", config)
    monkeypatch.setattr(mcp_server, "_kg", kg)
    long = _seed_long_drawer(palace_path)

    result = mcp_server.tool_list_drawers()
    assert result["count"] == 1
    preview = result["drawers"][0]["content_preview"]
    # Slice + ellipsis terminator. 200 chars + "..." = 203.
    assert preview == long[:200] + "..."


def test_preview_chars_widens_slice(monkeypatch, config, palace_path, kg):
    """Caller-supplied preview_chars=500 returns a 500-char preview."""
    from mempalace import mcp_server

    monkeypatch.setattr(mcp_server, "_config", config)
    monkeypatch.setattr(mcp_server, "_kg", kg)
    long = _seed_long_drawer(palace_path)

    result = mcp_server.tool_list_drawers(preview_chars=500)
    preview = result["drawers"][0]["content_preview"]
    assert preview == long[:500] + "..."


def test_preview_chars_clamps_below_minimum(monkeypatch, config, palace_path, kg):
    """preview_chars below 50 clamps to 50 (no zero-length previews)."""
    from mempalace import mcp_server

    monkeypatch.setattr(mcp_server, "_config", config)
    monkeypatch.setattr(mcp_server, "_kg", kg)
    long = _seed_long_drawer(palace_path)

    result = mcp_server.tool_list_drawers(preview_chars=10)
    preview = result["drawers"][0]["content_preview"]
    assert preview == long[:50] + "..."


def test_preview_chars_clamps_above_maximum(monkeypatch, config, palace_path, kg):
    """preview_chars above 2000 clamps to 2000."""
    from mempalace import mcp_server

    monkeypatch.setattr(mcp_server, "_config", config)
    monkeypatch.setattr(mcp_server, "_kg", kg)
    long = _seed_long_drawer(palace_path)

    result = mcp_server.tool_list_drawers(preview_chars=99999)
    preview = result["drawers"][0]["content_preview"]
    assert preview == long[:2000] + "..."


def test_descriptor_exposes_preview_chars():
    """The MCP TOOLS descriptor must declare preview_chars in input_schema."""
    from mempalace.mcp_server import TOOLS

    schema = TOOLS["mempalace_list_drawers"]["input_schema"]
    assert "preview_chars" in schema["properties"]
    pc = schema["properties"]["preview_chars"]
    assert pc["type"] == "integer"
    assert pc["minimum"] == 50
    assert pc["maximum"] == 2000
