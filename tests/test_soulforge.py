"""Tests for SoulForge JSONL session import.

Uses real SoulForge ChatMessage schema: {id, role, content, timestamp,
toolCalls?, segments?, durationMs?, showInChat?, isSteering?}.
"""

import json
import os
import tempfile

from mempalace.normalize import normalize


def _write_jsonl(lines):
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for obj in lines:
        f.write(json.dumps(obj) + "\n")
    f.close()
    return f.name


def _msg(role, content, **kw):
    return {"id": f"msg-{id(content)}", "role": role, "content": content, "timestamp": 0, **kw}


def test_full_session():
    """Realistic multi-turn session with every segment type and edge case."""
    path = _write_jsonl(
        [
            _msg("system", "You are Forge."),
            _msg("user", "Refactor auth to support OAuth2"),
            _msg(
                "assistant",
                "",
                durationMs=4200,
                segments=[
                    {"type": "reasoning", "content": "Need to check existing auth first."},
                    {"type": "text", "content": "I'll read the current auth module."},
                    {"type": "tools", "toolCallIds": ["tc-1", "tc-2"]},
                    {"type": "text", "content": "Found the JWT impl. Here's my plan."},
                    {
                        "type": "plan",
                        "plan": {
                            "steps": [
                                {"id": "s1", "label": "Add OAuth2 provider", "status": "done"},
                                {"id": "s2", "label": "Keep JWT fallback", "status": "pending"},
                            ]
                        },
                    },
                ],
                toolCalls=[
                    {"id": "tc-1", "name": "read", "args": {"path": "src/auth/jwt.ts"}},
                    {"id": "tc-2", "name": "soul_grep", "args": {"pattern": "authenticate"}},
                ],
            ),
            _msg("user", "Use PKCE flow", isSteering=True),
            _msg("system", "Context compacted.", showInChat=True),
            _msg("assistant", "Switching to PKCE.", durationMs=800),
        ]
    )
    result = normalize(path)

    assert "You are Forge" not in result
    assert "Context compacted." in result
    assert "> Refactor auth to support OAuth2" in result
    assert "Use PKCE flow" in result
    assert "I'll read the current auth module." in result
    assert "[read: src/auth/jwt.ts]" in result
    assert "[soul_grep: authenticate]" in result
    assert "[reasoning]" in result
    assert "[plan] Add OAuth2 provider; Keep JWT fallback" in result
    assert "Switching to PKCE." in result

    os.unlink(path)


def test_malformed_lines_and_missing_tool_refs():
    """Broken JSON lines skipped; missing toolCallId refs don't crash."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    f.write(json.dumps(_msg("user", "Go")) + "\n")
    f.write("NOT JSON\n")
    f.write('truncated {"role":\n')
    f.write(
        json.dumps(
            _msg(
                "assistant",
                "",
                durationMs=100,
                segments=[
                    {"type": "tools", "toolCallIds": ["tc-1", "tc-GHOST"]},
                    {"type": "text", "content": "Done."},
                ],
                toolCalls=[{"id": "tc-1", "name": "read", "args": {"path": "a.ts"}}],
            )
        )
        + "\n"
    )
    f.close()
    result = normalize(f.name)
    assert "[read: a.ts]" in result
    assert "Done." in result
    os.unlink(f.name)


def test_empty_segments_falls_back_to_flat():
    """segments=[] uses content + toolCalls fallback."""
    path = _write_jsonl(
        [
            _msg("user", "Search"),
            _msg(
                "assistant",
                "Found 3 matches.",
                segments=[],
                toolCalls=[{"id": "tc-1", "name": "soul_grep", "args": {"pattern": "auth"}}],
                durationMs=100,
            ),
        ]
    )
    result = normalize(path)
    assert "Found 3 matches." in result
    assert "[soul_grep: auth]" in result
    os.unlink(path)


def test_tool_summary_priority_truncation_fallback():
    """path preferred; long values truncated; no informative arg shows name only."""
    long_path = "src/deeply/nested/" + "x" * 80 + "/file.ts"
    path = _write_jsonl(
        [
            _msg("user", "Go"),
            _msg(
                "assistant",
                "",
                durationMs=100,
                segments=[{"type": "tools", "toolCallIds": ["tc-1", "tc-2", "tc-3"]}],
                toolCalls=[
                    {
                        "id": "tc-1",
                        "name": "edit_file",
                        "args": {"path": "src/main.ts", "pattern": "ignored"},
                    },
                    {"id": "tc-2", "name": "read", "args": {"path": long_path}},
                    {"id": "tc-3", "name": "list_dir", "args": {"depth": 2}},
                ],
            ),
        ]
    )
    result = normalize(path)
    assert "[edit_file: src/main.ts]" in result
    assert long_path not in result
    assert "[list_dir]" in result
    os.unlink(path)


def test_reasoning_truncated_at_500():
    """Reasoning over 500 chars is cut."""
    path = _write_jsonl(
        [
            _msg("user", "Think"),
            _msg(
                "assistant",
                "",
                durationMs=100,
                segments=[
                    {"type": "reasoning", "content": "x" * 800},
                    {"type": "text", "content": "Done."},
                ],
            ),
        ]
    )
    result = normalize(path)
    reasoning_line = [line for line in result.split("\n") if "[reasoning]" in line][0]
    assert len(reasoning_line) <= 512
    os.unlink(path)
