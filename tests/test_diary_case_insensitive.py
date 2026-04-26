"""
test_diary_case_insensitive.py — A2 (RFC-0028 §4.2).

ChromaDB metadata filters are exact-match. Pre-fix, ``tool_diary_write``
stored ``agent`` metadata as the caller passed it (e.g. ``"Fox"``) while
``tool_diary_read`` queried with whatever the caller sent (e.g. ``"fox"``),
silently returning zero entries. Wing derivation already lowercased the
agent name, so casing was an asymmetric trap.

Post-fix, both sides normalize to lowercase. The caller still sees the
original-cased ``agent`` field on the write response (so callers using
agent_name in display can keep their casing), but the durable metadata
and filter are lowercase.
"""


def test_diary_write_then_read_case_insensitive(monkeypatch, config, palace_path, kg):
    """Write with `Fox`, read with `fox`, get the entry back."""
    from mempalace import mcp_server

    monkeypatch.setattr(mcp_server, "_config", config)
    monkeypatch.setattr(mcp_server, "_kg", kg)

    # Bootstrap an empty palace.
    import chromadb

    client = chromadb.PersistentClient(path=palace_path)
    client.get_or_create_collection(
        "mempalace_drawers", metadata={"hnsw:space": "cosine"}
    )
    del client

    write = mcp_server.tool_diary_write(
        agent_name="Fox", entry="Sprint planning notes for Tuesday.", topic="planning"
    )
    assert write["success"] is True

    read_lower = mcp_server.tool_diary_read(agent_name="fox")
    assert read_lower.get("total", 0) == 1, f"lowercase read returned: {read_lower}"
    assert read_lower["entries"][0]["topic"] == "planning"

    read_upper = mcp_server.tool_diary_read(agent_name="FOX")
    assert read_upper.get("total", 0) == 1, f"uppercase read returned: {read_upper}"

    read_orig = mcp_server.tool_diary_read(agent_name="Fox")
    assert read_orig.get("total", 0) == 1, f"original-case read returned: {read_orig}"


def test_diary_write_then_read_mixed_agents_isolated(
    monkeypatch, config, palace_path, kg
):
    """Two agents whose names share a casing-only difference must NOT alias —
    the lowercase normalization is consistent, not a free-for-all."""
    from mempalace import mcp_server

    monkeypatch.setattr(mcp_server, "_config", config)
    monkeypatch.setattr(mcp_server, "_kg", kg)

    import chromadb

    client = chromadb.PersistentClient(path=palace_path)
    client.get_or_create_collection(
        "mempalace_drawers", metadata={"hnsw:space": "cosine"}
    )
    del client

    mcp_server.tool_diary_write(agent_name="Fox", entry="entry from fox")
    mcp_server.tool_diary_write(agent_name="Owl", entry="entry from owl")

    fox = mcp_server.tool_diary_read(agent_name="fox")
    owl = mcp_server.tool_diary_read(agent_name="OWL")

    assert fox.get("total", 0) == 1
    assert owl.get("total", 0) == 1
    assert "fox" in fox["entries"][0]["content"]
    assert "owl" in owl["entries"][0]["content"]
