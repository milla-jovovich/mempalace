"""Additional miner coverage for ignore rules, routing, and CLI-style output."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mempalace.miner import (
    GitignoreMatcher,
    add_drawer,
    build_retrieval_artifacts,
    chunk_text,
    detect_room,
    is_exact_force_include,
    is_force_included,
    load_config,
    mine,
    normalize_include_paths,
    process_file,
    should_skip_dir,
    status,
)


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_gitignore_matcher_handles_comments_escaped_prefixes_and_read_errors(tmp_path, monkeypatch):
    _write(
        tmp_path / ".gitignore",
        "\n".join(
            [
                "# comment",
                r"\#literal.txt",
                r"\!literalbang.txt",
                "/anchored.txt",
                "build/",
            ]
        ),
    )

    matcher = GitignoreMatcher.from_dir(tmp_path)
    assert matcher is not None
    assert matcher.matches(tmp_path / "#literal.txt", is_dir=False) is True
    # The current parser strips the escape before applying normal negation handling, so
    # the literal-bang pattern becomes an explicit unignore rule for "literalbang.txt".
    # The literal filename "!literalbang.txt" therefore receives no decision.
    assert matcher.matches(tmp_path / "!literalbang.txt", is_dir=False) is None
    assert matcher.matches(tmp_path / "anchored.txt", is_dir=False) is True
    assert matcher.matches(tmp_path / "build", is_dir=True) is True

    broken = tmp_path / "broken"
    broken.mkdir()
    _write(broken / ".gitignore", "ignored.txt\n")
    monkeypatch.setattr(Path, "read_text", lambda self, **kwargs: (_ for _ in ()).throw(OSError("boom")))

    assert GitignoreMatcher.from_dir(broken) is None


def test_include_helpers_and_skip_dir_cover_edge_cases(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    include_paths = normalize_include_paths([" docs/guide.md ", "/generated"])

    assert include_paths == {"docs/guide.md", "generated"}
    assert is_exact_force_include(project / "docs" / "guide.md", project, include_paths) is True
    assert is_exact_force_include(tmp_path / "outside.txt", project, include_paths) is False
    assert is_force_included(project / "generated" / "nested" / "file.py", project, include_paths) is True
    assert is_force_included(project, project, include_paths) is False
    assert should_skip_dir("package.egg-info") is True


def test_load_config_supports_legacy_name_and_exits_when_missing(tmp_path, capsys):
    legacy = tmp_path / "mempal.yaml"
    legacy.write_text("wing: legacy\nrooms: []\n", encoding="utf-8")

    assert load_config(str(tmp_path))["wing"] == "legacy"

    missing = tmp_path / "missing"
    missing.mkdir()
    try:
        load_config(str(missing))
        assert False, "Expected load_config to exit when no config file exists"
    except SystemExit as exc:
        assert exc.code == 1
    output = capsys.readouterr().out
    assert "No mempalace.yaml found" in output


@pytest.mark.parametrize(
    ("filepath", "content", "expected"),
    [
        ("src/backend/module.py", "nothing relevant", "backend"),
        ("notes/planning/deploy-plan.txt", "nothing relevant", "planning"),
        ("misc/file.txt", "graphql graphql api server", "backend"),
        ("misc/file.txt", "plain unrelated text", "general"),
    ],
)
def test_detect_room_uses_path_filename_content_and_fallback(tmp_path, filepath, content, expected):
    project = tmp_path / "project"
    file_path = project / filepath
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    rooms = [
        {"name": "backend", "keywords": ["graphql", "server"]},
        {"name": "planning", "keywords": ["roadmap", "milestone"]},
    ]

    assert detect_room(file_path, content, rooms, project) == expected


def test_chunk_text_handles_empty_content_and_boundary_splitting():
    assert chunk_text("   ", "demo.txt") == []

    content = ("A" * 500) + "\n\n" + ("B" * 500) + "\n" + ("C" * 200)
    chunks = chunk_text(content, "demo.txt")

    assert len(chunks) >= 2
    assert all("content" in chunk and "chunk_index" in chunk for chunk in chunks)


def test_add_drawer_handles_missing_mtime_and_reraises_backend_errors(monkeypatch):
    collection = MagicMock()
    monkeypatch.setattr("mempalace.miner.os.path.getmtime", lambda _: (_ for _ in ()).throw(OSError("no stat")))

    assert (
        add_drawer(collection, "wing", "room", "content", "/tmp/file.txt", 0, "tester") is True
    )
    metadata = collection.upsert.call_args.kwargs["metadatas"][0]
    assert "source_mtime" not in metadata

    failing = MagicMock()
    failing.upsert.side_effect = RuntimeError("disk full")
    try:
        add_drawer(failing, "wing", "room", "content", "/tmp/file.txt", 0, "tester")
        assert False, "Expected add_drawer to re-raise storage failures"
    except RuntimeError as exc:
        assert "disk full" in str(exc)


def test_add_drawer_writes_hall_and_preference_support_doc(monkeypatch):
    collection = MagicMock()
    support_collection = MagicMock()
    monkeypatch.setattr("mempalace.miner.os.path.getmtime", lambda _: 123.0)

    added = add_drawer(
        collection,
        "wing",
        "room",
        "I've been struggling with battery life on my laptop lately.",
        "/tmp/file.txt",
        0,
        "tester",
        support_collection=support_collection,
        ingest_mode="project",
    )

    raw_meta = collection.upsert.call_args.kwargs["metadatas"][0]
    support_meta = support_collection.upsert.call_args.kwargs["metadatas"][0]
    support_doc = support_collection.upsert.call_args.kwargs["documents"][0]
    assert added is True
    assert raw_meta["hall"] == "hall_preferences"
    assert raw_meta["ingest_mode"] == "project"
    assert support_meta["parent_drawer_id"].startswith("drawer_wing_room_")
    assert support_meta["support_kind"] == "preference"
    assert "battery life on my laptop" in support_meta["preference_signals"]
    assert support_doc.startswith("User has mentioned:")


def test_build_retrieval_artifacts_normalizes_signals_and_preserves_existing_metadata(monkeypatch):
    monkeypatch.setattr("mempalace.miner.os.path.getmtime", lambda _: 123.0)

    artifacts = build_retrieval_artifacts(
        wing="wing",
        room="room",
        content="> I prefer long battery life\nYou suggested trying a lower-power profile.",
        source_file="/tmp/chat.txt",
        chunk_index=7,
        agent="tester",
        ingest_mode="project",
        extra_metadata={"extract_mode": "exchange", "filed_at": "2024-01-01T00:00:00"},
        drawer_id_override="drawer_manual_override",
    )

    assert artifacts["drawer_id"] == "drawer_manual_override"
    assert artifacts["metadata"]["ingest_mode"] == "convos"
    assert artifacts["metadata"]["hall"] == "hall_preferences"
    assert artifacts["metadata"]["filed_at"] == "2024-01-01T00:00:00"
    assert artifacts["support_row"]["metadata"]["parent_drawer_id"] == "drawer_manual_override"


def test_build_retrieval_artifacts_can_skip_support_doc_generation(monkeypatch):
    monkeypatch.setattr("mempalace.miner.os.path.getmtime", lambda _: 123.0)

    artifacts = build_retrieval_artifacts(
        wing="wing",
        room="room",
        content="> I prefer long battery life\nYou suggested trying a lower-power profile.",
        source_file="/tmp/chat.txt",
        chunk_index=7,
        agent="tester",
        ingest_mode="project",
        include_support=False,
    )

    assert artifacts["metadata"]["ingest_mode"] == "convos"
    assert artifacts["metadata"]["hall"] == "hall_preferences"
    assert artifacts["support_row"] is None


def test_add_drawer_support_id_can_be_overridden(monkeypatch):
    collection = MagicMock()
    monkeypatch.setattr("mempalace.miner.os.path.getmtime", lambda _: 123.0)

    add_drawer(
        collection,
        "wing",
        "room",
        "plain content with no preference signal",
        "/tmp/file.txt",
        0,
        "tester",
        drawer_id_override="drawer_manual_override",
    )

    assert collection.upsert.call_args.kwargs["ids"] == ["drawer_manual_override"]


def test_process_file_covers_already_mined_read_error_dry_run_and_delete_failure(tmp_path, capsys):
    project = tmp_path / "project"
    project.mkdir()
    target = project / "src" / "app.py"
    _write(target, "print('hello world')\n" * 20)
    rooms = [{"name": "backend", "keywords": ["print"]}]

    with patch("mempalace.miner.file_already_mined", return_value=True):
        assert process_file(target, project, MagicMock(), "wing", rooms, "tester", False) == (0, None)

    missing = project / "missing.py"
    with patch.object(Path, "read_text", side_effect=OSError("no read")):
        assert process_file(missing, project, MagicMock(), "wing", rooms, "tester", False) == (0, None)

    drawers, room = process_file(target, project, MagicMock(), "wing", rooms, "tester", True)
    assert drawers >= 1
    assert room == "backend"
    assert "[DRY RUN]" in capsys.readouterr().out

    collection = MagicMock()
    support_collection = MagicMock()
    collection.delete.side_effect = RuntimeError("cannot delete stale chunks")
    drawers, room = process_file(
        target,
        project,
        collection,
        "wing",
        rooms,
        "tester",
        False,
        support_collection=support_collection,
    )
    assert drawers >= 1
    assert room == "backend"
    support_collection.delete.assert_called_once_with(where={"source_file": str(target)})


def test_process_file_ignores_support_delete_failure(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    target = project / "src" / "app.py"
    _write(target, "print('hello world')\n" * 20)
    rooms = [{"name": "backend", "keywords": ["print"]}]
    collection = MagicMock()
    support_collection = MagicMock()
    support_collection.delete.side_effect = RuntimeError("cannot delete support rows")

    drawers, room = process_file(
        target,
        project,
        collection,
        "wing",
        rooms,
        "tester",
        False,
        support_collection=support_collection,
    )

    assert drawers >= 1
    assert room == "backend"


def test_mine_reports_skips_limits_and_include_overrides(tmp_path, capsys):
    files = [tmp_path / "a.py", tmp_path / "b.py"]
    for path in files:
        path.write_text("print('x')", encoding="utf-8")

    with patch("mempalace.miner.load_config", return_value={"wing": "demo", "rooms": [{"name": "backend"}]}), patch(
        "mempalace.miner.scan_project",
        return_value=files,
    ), patch("mempalace.miner.get_collection", return_value=object()) as mock_get_collection, patch(
        "mempalace.miner.get_support_collection", return_value=object()
    ) as mock_get_support_collection, patch(
        "mempalace.miner.process_file",
        side_effect=[(0, None), (2, "backend")],
    ):
        mine(
            str(tmp_path),
            str(tmp_path / "palace"),
            limit=2,
            respect_gitignore=False,
            include_ignored=["docs", "generated/file.py"],
        )

    output = capsys.readouterr().out
    assert ".gitignore: DISABLED" in output
    assert "Include: docs, generated/file.py" in output
    assert "Files skipped (already filed): 1" in output
    assert "Drawers filed: 2" in output
    mock_get_collection.assert_called_once()
    mock_get_support_collection.assert_called_once()


def test_mine_dry_run_does_not_create_collection(tmp_path, capsys):
    files = [tmp_path / "a.py"]
    files[0].write_text("print('x')", encoding="utf-8")

    with patch("mempalace.miner.load_config", return_value={"wing": "demo", "rooms": [{"name": "backend"}]}), patch(
        "mempalace.miner.scan_project",
        return_value=files,
    ), patch("mempalace.miner.process_file", return_value=(1, "backend")), patch(
        "mempalace.miner.get_collection"
    ) as mock_get_collection, patch("mempalace.miner.get_support_collection") as mock_get_support_collection:
        mine(str(tmp_path), str(tmp_path / "palace"), dry_run=True, limit=1)

    output = capsys.readouterr().out
    assert "DRY RUN" in output
    mock_get_collection.assert_not_called()
    mock_get_support_collection.assert_not_called()


def test_status_prints_room_breakdown_and_missing_palace_message(capsys):
    collection = MagicMock()
    collection.get.return_value = {
        "metadatas": [
            {"wing": "project", "room": "backend"},
            {"wing": "project", "room": "backend"},
            {"wing": "notes", "room": "planning"},
        ]
    }

    with patch("mempalace.miner.get_collection", return_value=collection):
        status("/tmp/palace")
    output = capsys.readouterr().out
    assert "MemPalace Status — 3 drawers" in output
    assert "WING: project" in output
    assert "ROOM: backend" in output

    with patch("mempalace.miner.get_collection", side_effect=RuntimeError("missing")):
        status("/tmp/missing-palace")
    output = capsys.readouterr().out
    assert "No palace found" in output
