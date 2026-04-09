import json
import os
import tempfile
import shutil
import chromadb
from mempalace.convo_miner import mine_convos, detect_wing, detect_wing_from_path


def test_convo_mining():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "chat.txt"), "w") as f:
        f.write(
            "> What is memory?\nMemory is persistence.\n\n> Why does it matter?\nIt enables continuity.\n\n> How do we build it?\nWith structured storage.\n"
        )

    palace_path = os.path.join(tmpdir, "palace")
    mine_convos(tmpdir, palace_path, wing="test_convos")

    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_collection("mempalace_drawers")
    assert col.count() >= 2

    # Verify search works
    results = col.query(query_texts=["memory persistence"], n_results=1)
    assert len(results["documents"][0]) > 0

    shutil.rmtree(tmpdir)


# =============================================================================
# Wing auto-detection tests
# =============================================================================


def test_detect_wing_claude_code_project():
    """Tier 1: Claude Code project path extracts the project name as wing."""
    convo_dir = "/Users/alice/.claude/projects"
    filepath = (
        "/Users/alice/.claude/projects/"
        "-Users-alice-Projects-my-cool-app/"
        "abc-123/subagents/agent-xyz.jsonl"
    )
    assert detect_wing(filepath, convo_dir) == "my_cool_app"


def test_detect_wing_claude_code_single_word_project():
    """Tier 1: single-word project name."""
    convo_dir = "/Users/bob/.claude/projects"
    filepath = (
        "/Users/bob/.claude/projects/"
        "-Users-bob-Projects-webapp/"
        "session-1/subagents/agent-a.jsonl"
    )
    assert detect_wing(filepath, convo_dir) == "webapp"


def test_detect_wing_claude_code_root_projects():
    """Tier 1: sessions from ~/Projects root → general (no path signal)."""
    convo_dir = "/Users/alice/.claude/projects"
    filepath = (
        "/Users/alice/.claude/projects/"
        "-Users-alice-Projects/"
        "session-uuid/subagents/agent-xyz.jsonl"
    )
    # With no content, path-only returns general
    assert detect_wing(filepath, convo_dir, content="no project info") == "general"


def test_detect_wing_claude_code_home_dir():
    """Tier 1: sessions from home directory (no anchor) → general."""
    convo_dir = "/Users/alice/.claude/projects"
    filepath = (
        "/Users/alice/.claude/projects/"
        "-Users-alice/"
        "session-uuid/subagents/agent-xyz.jsonl"
    )
    assert detect_wing(filepath, convo_dir, content="no project info") == "general"


def test_detect_wing_developer_anchor():
    """Tier 1: paths with Developer as anchor directory."""
    convo_dir = "/Users/carol/.claude/projects"
    filepath = (
        "/Users/carol/.claude/projects/"
        "-Users-carol-Developer-side-project/"
        "session/subagents/agent.jsonl"
    )
    assert detect_wing(filepath, convo_dir) == "side_project"


def test_detect_wing_fallback_parent():
    """Tier 1: non-Claude-Code paths fall back to parent directory name."""
    convo_dir = "/tmp/chats"
    filepath = "/tmp/chats/work-stuff/transcript.txt"
    assert detect_wing(filepath, convo_dir, content="no project info") == "work_stuff"


def test_detect_wing_from_cwd():
    """Tier 2: detect project from cwd fields in JSONL content."""
    convo_dir = "/Users/alice/.claude/projects"
    filepath = (
        "/Users/alice/.claude/projects/"
        "-Users-alice-Projects/"
        "session-uuid/subagents/agent.jsonl"
    )
    # Simulate Claude Code JSONL with cwd pointing to a project
    lines = [
        json.dumps({"type": "user", "cwd": "/Users/alice/Projects", "message": {"content": "hi"}}),
        json.dumps({"type": "assistant", "cwd": "/Users/alice/Projects/myapp", "message": {"content": "hello"}}),
        json.dumps({"type": "user", "cwd": "/Users/alice/Projects/myapp", "message": {"content": "help"}}),
        json.dumps({"type": "assistant", "cwd": "/Users/alice/Projects/myapp", "message": {"content": "sure"}}),
    ]
    content = "\n".join(lines)
    # Tier 1 returns general (root Projects dir), tier 2 should find myapp from cwd
    assert detect_wing(filepath, convo_dir, content=content) == "myapp"


def test_detect_wing_from_content_paths():
    """Tier 3: detect project from path references in conversation text."""
    convo_dir = "/Users/alice/.claude/projects"
    filepath = (
        "/Users/alice/.claude/projects/"
        "-Users-alice-Projects/"
        "session-uuid/subagents/agent.jsonl"
    )
    # Normalized transcript — no cwd fields, but content mentions project paths
    content = (
        "> Help me fix the scoring bug\n"
        "Looking at /Users/alice/Projects/cabra/src/game/scoring.ts\n\n"
        "> What about the synergy system?\n"
        "Reading /Users/alice/Projects/cabra/src/game/synergy.ts now.\n"
    )
    assert detect_wing(filepath, convo_dir, content=content) == "cabra"


def test_detect_wing_cwd_beats_content():
    """Tier 2 (cwd) takes priority over tier 3 (content references)."""
    convo_dir = "/Users/alice/.claude/projects"
    filepath = (
        "/Users/alice/.claude/projects/"
        "-Users-alice-Projects/"
        "session/agent.jsonl"
    )
    # cwd points to appA, but content mentions appB more
    lines = [
        json.dumps({"type": "user", "cwd": "/Users/alice/Projects/appA", "message": {"content": "hi"}}),
        json.dumps({"type": "assistant", "cwd": "/Users/alice/Projects/appA", "message": {"content": "hello"}}),
    ]
    content = "\n".join(lines)
    # Even though content is JSONL (no path refs to other projects), cwd wins
    assert detect_wing(filepath, convo_dir, content=content) == "appa"


def test_detect_wing_backwards_compat():
    """detect_wing_from_path is an alias for detect_wing."""
    assert detect_wing_from_path is detect_wing


def test_clean_wing_normalizes_dots():
    """Dots in project names (e.g., zachtime.xyz) become underscores."""
    convo_dir = "/Users/alice/.claude/projects"
    filepath = (
        "/Users/alice/.claude/projects/"
        "-Users-alice-Projects/"
        "session/agent.jsonl"
    )
    content = (
        "> Deploy the site\n"
        "Deploying /Users/alice/Projects/zachtime.xyz/dist to CloudFront.\n\n"
        "> Check the build\n"
        "Reading /Users/alice/Projects/zachtime.xyz/package.json.\n"
    )
    assert detect_wing(filepath, convo_dir, content=content) == "zachtime_xyz"


def test_detect_wing_auto_mine_creates_per_project_wings():
    """When no --wing is given, mine_convos files drawers with per-file wings."""
    tmpdir = tempfile.mkdtemp()
    # Simulate Claude Code structure: two "projects"
    proj_a = os.path.join(tmpdir, "-Users-test-Projects-alpha", "session1", "subagents")
    proj_b = os.path.join(tmpdir, "-Users-test-Projects-beta", "session1", "subagents")
    os.makedirs(proj_a)
    os.makedirs(proj_b)

    convo = "> What is X?\nX is a thing.\n\n> Tell me more\nMore details here.\n"
    with open(os.path.join(proj_a, "agent-a.txt"), "w") as f:
        f.write(convo)
    with open(os.path.join(proj_b, "agent-b.txt"), "w") as f:
        f.write(convo)

    palace_path = os.path.join(tmpdir, "palace")
    # No --wing: auto-detect
    mine_convos(tmpdir, palace_path, wing=None)

    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_collection("mempalace_drawers")
    all_meta = col.get(include=["metadatas"])["metadatas"]

    wings = {m["wing"] for m in all_meta}
    assert "alpha" in wings
    assert "beta" in wings

    shutil.rmtree(tmpdir)


def test_explicit_wing_overrides_auto_detect():
    """When --wing is given, all files use that wing regardless of path."""
    tmpdir = tempfile.mkdtemp()
    proj = os.path.join(tmpdir, "-Users-test-Projects-alpha", "session1", "subagents")
    os.makedirs(proj)
    convo = (
        "> What is the meaning of software architecture and why does it matter?\n"
        "Software architecture defines the high-level structure of a system.\n\n"
        "> Can you explain the difference between monoliths and microservices?\n"
        "Monoliths deploy as a single unit while microservices are distributed.\n\n"
        "> What about serverless architecture patterns?\n"
        "Serverless lets you focus on business logic without managing servers.\n"
    )
    with open(os.path.join(proj, "agent.txt"), "w") as f:
        f.write(convo)

    palace_path = os.path.join(tmpdir, "palace")
    mine_convos(tmpdir, palace_path, wing="my_custom_wing")

    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_collection("mempalace_drawers")
    all_meta = col.get(include=["metadatas"])["metadatas"]

    wings = {m["wing"] for m in all_meta}
    assert wings == {"my_custom_wing"}

    shutil.rmtree(tmpdir)
