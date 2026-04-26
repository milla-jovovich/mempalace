"""
test_memories_filed_away_clarification.py — A6 (RFC-0028 §4.6).

The tool name ``mempalace_memories_filed_away`` suggests "drawer count"
or "memories filed". It actually checks whether a recent SessionStop
checkpoint exists and returns the count of messages in *that one*
checkpoint event — completely orthogonal to palace size. New users
read the name, expect drawer counts, and get ``count: 0`` even on a
mature palace, which is misleading.

The lib-side fix is documentation-only:
- Docstring on ``tool_memories_filed_away`` clarifies the contract and
  points at ``mempalace_status`` for palace-size queries.
- The MCP TOOLS descriptor description carries the same clarification.
- A new alias ``mempalace_last_checkpoint`` points at the same handler
  with a name that says what the tool actually does. The legacy name
  ``mempalace_memories_filed_away`` is preserved for back-compat.

Behaviour is unchanged.
"""


def test_memories_filed_away_descriptor_clarifies_contract():
    """Descriptor description must say 'NOT a drawer-count' and point at mempalace_status."""
    from mempalace.mcp_server import TOOLS

    desc = TOOLS["mempalace_memories_filed_away"]["description"]
    assert "NOT a drawer-count" in desc, (
        f"description must clarify the tool isn't a drawer count: {desc}"
    )
    assert "mempalace_status" in desc, (
        f"description must redirect drawer-count callers to mempalace_status: {desc}"
    )


def test_last_checkpoint_alias_registered():
    """The clearer ``mempalace_last_checkpoint`` alias must share the handler."""
    from mempalace.mcp_server import TOOLS

    assert "mempalace_last_checkpoint" in TOOLS, (
        "alias not registered in the TOOLS dispatch table"
    )
    legacy = TOOLS["mempalace_memories_filed_away"]["handler"]
    alias = TOOLS["mempalace_last_checkpoint"]["handler"]
    assert legacy is alias, "alias must point at the same handler as the legacy name"


def test_legacy_name_preserved_for_back_compat():
    """The legacy ``mempalace_memories_filed_away`` entry must still exist."""
    from mempalace.mcp_server import TOOLS

    assert "mempalace_memories_filed_away" in TOOLS


def test_docstring_clarifies_not_a_drawer_count():
    """The handler docstring must point at mempalace_status for drawer-count queries."""
    from mempalace.mcp_server import tool_memories_filed_away

    doc = tool_memories_filed_away.__doc__ or ""
    assert "NOT a drawer-count" in doc
    assert "mempalace_status" in doc


def test_handler_behavior_unchanged_no_checkpoint(tmp_path, monkeypatch):
    """With no checkpoint file, returns status='quiet' and count=0 (unchanged)."""
    from mempalace import mcp_server

    # _isolate_home in conftest already redirects HOME to a temp dir;
    # we just need to make sure the ack file does not exist.
    state_dir = tmp_path / ".mempalace" / "hook_state"
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    assert not (state_dir / "last_checkpoint").exists()

    result = mcp_server.tool_memories_filed_away()
    assert result["status"] == "quiet"
    assert result["count"] == 0
