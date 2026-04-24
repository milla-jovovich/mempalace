"""
Tests for focused fixes:

  1. KG singleton uses _config.palace_path, not the hardcoded default
  2. cmd_split forwards --palace through to split_main's argv
"""

import os
import sys
import types
from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Fix 1: Knowledge graph co-located with palace
# ---------------------------------------------------------------------------


def test_kg_accepts_custom_db_path(tmp_path):
    """KnowledgeGraph must store to the path given, not always DEFAULT_KG_PATH.

    The fix: _get_kg() now passes db_path=os.path.join(_config.palace_path,
    'knowledge_graph.sqlite3') instead of letting KnowledgeGraph fall back to
    DEFAULT_KG_PATH. This test verifies KnowledgeGraph honours the argument.
    """
    from mempalace.knowledge_graph import KnowledgeGraph

    custom_db = str(tmp_path / "custom_palace" / "knowledge_graph.sqlite3")
    kg = KnowledgeGraph(db_path=custom_db)

    assert kg.db_path == custom_db
    # The file must be created on init
    assert Path(custom_db).exists(), "KG must create the db file at the given path"


def test_kg_default_path_is_home_mempalace():
    """Default KG path must remain ~/.mempalace/knowledge_graph.sqlite3.

    Ensures backward compatibility: users who run without --palace still get
    data in the same location as before the fix.
    """
    from mempalace.knowledge_graph import DEFAULT_KG_PATH

    expected = os.path.expanduser("~/.mempalace/knowledge_graph.sqlite3")
    assert DEFAULT_KG_PATH == expected


def test_kg_lazy_init_pattern():
    """_get_kg() in mcp_server must be a lazy initialiser, not a module-level call.

    Inspects the source of mcp_server to verify:
    - No bare `_kg = KnowledgeGraph()` at module scope
    - A `_get_kg` function exists
    - `_kg_instance` sentinel exists for caching

    This is a static-analysis test -- runs without importing chromadb.
    """
    import ast

    src = (Path(__file__).parent.parent / "mempalace" / "mcp_server.py").read_text()
    tree = ast.parse(src)

    # Check that no module-level assignment creates a KnowledgeGraph() call
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "_kg":
                    # If the value is a Call to KnowledgeGraph, that's the bug
                    if isinstance(node.value, ast.Call):
                        func = node.value.func
                        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                        assert name != "KnowledgeGraph", (
                            "Module-level `_kg = KnowledgeGraph()` found -- "
                            "this is the bug we fixed. Use _get_kg() instead."
                        )

    # Check _get_kg function exists
    func_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    assert "_get_kg" in func_names, "_get_kg lazy-init function must exist in mcp_server.py"

    # Check _kg_instance sentinel exists
    sentinel_found = any(
        isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "_kg_instance" for t in node.targets)
        for node in ast.walk(tree)
    )
    assert sentinel_found, "_kg_instance sentinel variable must exist for lazy caching"


# ---------------------------------------------------------------------------
# Fix 2: cmd_split forwards --palace
# ---------------------------------------------------------------------------


def test_cmd_split_forwards_palace(tmp_path):
    """cmd_split must include --palace in the reconstructed sys.argv.

    Before this fix, running `mempalace split <dir> --palace /x` would drop
    the --palace flag when rebuilding sys.argv for split_main. The result:
    split files processed correctly but written to the wrong palace location.
    """
    captured = []

    def mock_split_main():
        captured.extend(sys.argv)

    args = types.SimpleNamespace(
        dir=str(tmp_path),
        palace=str(tmp_path / "mypalace"),
        output_dir=None,
        dry_run=False,
        min_sessions=2,
    )

    with patch("mempalace.split_mega_files.main", mock_split_main):
        from mempalace.cli import cmd_split
        cmd_split(args)

    assert "--palace" in captured, (
        f"--palace must appear in sys.argv passed to split_main. Got: {captured}"
    )
    palace_idx = captured.index("--palace")
    assert captured[palace_idx + 1] == str(tmp_path / "mypalace"), (
        "--palace value must be the custom path"
    )


def test_cmd_split_no_palace_not_forwarded(tmp_path):
    """When --palace is not given, the reconstructed argv must not include it."""
    captured = []

    def mock_split_main():
        captured.extend(sys.argv)

    args = types.SimpleNamespace(
        dir=str(tmp_path),
        palace=None,
        output_dir=None,
        dry_run=False,
        min_sessions=2,
    )

    with patch("mempalace.split_mega_files.main", mock_split_main):
        from mempalace.cli import cmd_split
        cmd_split(args)

    assert "--palace" not in captured, (
        "--palace must not appear in argv when args.palace is None"
    )


def test_cmd_split_all_flags_forwarded(tmp_path):
    """cmd_split must forward all flags together correctly."""
    captured = []

    def mock_split_main():
        captured.extend(sys.argv)

    args = types.SimpleNamespace(
        dir=str(tmp_path),
        palace=str(tmp_path / "palace"),
        output_dir=str(tmp_path / "out"),
        dry_run=True,
        min_sessions=5,
    )

    with patch("mempalace.split_mega_files.main", mock_split_main):
        from mempalace.cli import cmd_split
        cmd_split(args)

    assert "--palace" in captured
    assert "--output-dir" in captured
    assert "--dry-run" in captured
    assert "--min-sessions" in captured
    assert "5" in captured
