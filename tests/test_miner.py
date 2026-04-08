import os
import shutil
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import chromadb
import yaml

from mempalace.miner import mine, scan_project
from mempalace.palace import file_already_mined


def write_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def scanned_files(project_root: Path, **kwargs):
    files = scan_project(str(project_root), **kwargs)
    return sorted(path.relative_to(project_root).as_posix() for path in files)


def write_project_config(project_root: Path, wing: str = "test_project"):
    with open(project_root / "mempalace.yaml", "w") as f:
        yaml.dump(
            {
                "wing": wing,
                "rooms": [
                    {
                        "name": "billing",
                        "description": "Billing work",
                        "keywords": ["invoice", "billing", "payment"],
                    },
                    {
                        "name": "auth",
                        "description": "Authentication work",
                        "keywords": ["auth", "oauth", "token"],
                    },
                    {"name": "general", "description": "General"},
                ],
            },
            f,
        )


def get_collection(palace_path: Path):
    client = chromadb.PersistentClient(path=str(palace_path))
    return client.get_collection("mempalace_drawers")


def get_source_rows(col, source_file: Path, wing: str):
    results = col.get(
        where={"$and": [{"source_file": str(source_file.resolve())}, {"wing": wing}]},
        include=["documents", "metadatas"],
    )
    return list(zip(results["ids"], results["documents"], results["metadatas"]))


def test_project_mining():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        os.makedirs(project_root / "backend")

        write_file(
            project_root / "backend" / "app.py", "def main():\n    print('hello world')\n" * 20
        )
        with open(project_root / "mempalace.yaml", "w") as f:
            yaml.dump(
                {
                    "wing": "test_project",
                    "rooms": [
                        {"name": "backend", "description": "Backend code"},
                        {"name": "general", "description": "General"},
                    ],
                },
                f,
            )

        palace_path = project_root / "palace"
        mine(str(project_root), str(palace_path))

        client = chromadb.PersistentClient(path=str(palace_path))
        col = client.get_collection("mempalace_drawers")
        assert col.count() > 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_scan_project_respects_gitignore():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "ignored.py\ngenerated/\n")
        write_file(project_root / "src" / "app.py", "print('hello')\n" * 20)
        write_file(project_root / "ignored.py", "print('ignore me')\n" * 20)
        write_file(project_root / "generated" / "artifact.py", "print('artifact')\n" * 20)

        assert scanned_files(project_root) == ["src/app.py"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_respects_nested_gitignore():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "*.log\n")
        write_file(project_root / "subrepo" / ".gitignore", "tasks/\n")
        write_file(project_root / "subrepo" / "src" / "main.py", "print('main')\n" * 20)
        write_file(project_root / "subrepo" / "tasks" / "task.py", "print('task')\n" * 20)
        write_file(project_root / "subrepo" / "debug.log", "debug\n" * 20)

        assert scanned_files(project_root) == ["subrepo/src/main.py"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_allows_nested_gitignore_override():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "*.csv\n")
        write_file(project_root / "subrepo" / ".gitignore", "!keep.csv\n")
        write_file(project_root / "drop.csv", "a,b,c\n" * 20)
        write_file(project_root / "subrepo" / "keep.csv", "a,b,c\n" * 20)

        assert scanned_files(project_root) == ["subrepo/keep.csv"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_allows_gitignore_negation_when_parent_dir_is_visible():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "generated/*\n!generated/keep.py\n")
        write_file(project_root / "generated" / "drop.py", "print('drop')\n" * 20)
        write_file(project_root / "generated" / "keep.py", "print('keep')\n" * 20)

        assert scanned_files(project_root) == ["generated/keep.py"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_does_not_reinclude_file_from_ignored_directory():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "generated/\n!generated/keep.py\n")
        write_file(project_root / "generated" / "drop.py", "print('drop')\n" * 20)
        write_file(project_root / "generated" / "keep.py", "print('keep')\n" * 20)

        assert scanned_files(project_root) == []
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_can_disable_gitignore():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "data/\n")
        write_file(project_root / "data" / "stuff.csv", "a,b,c\n" * 20)

        assert scanned_files(project_root, respect_gitignore=False) == ["data/stuff.csv"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_can_include_ignored_directory():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "docs/\n")
        write_file(project_root / "docs" / "guide.md", "# Guide\n" * 20)

        assert scanned_files(project_root, include_ignored=["docs"]) == ["docs/guide.md"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_can_include_specific_ignored_file():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "generated/\n")
        write_file(project_root / "generated" / "drop.py", "print('drop')\n" * 20)
        write_file(project_root / "generated" / "keep.py", "print('keep')\n" * 20)

        assert scanned_files(project_root, include_ignored=["generated/keep.py"]) == [
            "generated/keep.py"
        ]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_can_include_exact_file_without_known_extension():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "README\n")
        write_file(project_root / "README", "hello\n" * 20)

        assert scanned_files(project_root, include_ignored=["README"]) == ["README"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_include_override_beats_skip_dirs():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".pytest_cache" / "cache.py", "print('cache')\n" * 20)

        assert scanned_files(
            project_root,
            respect_gitignore=False,
            include_ignored=[".pytest_cache"],
        ) == [".pytest_cache/cache.py"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_skip_dirs_still_apply_without_override():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".pytest_cache" / "cache.py", "print('cache')\n" * 20)
        write_file(project_root / "main.py", "print('main')\n" * 20)

        assert scanned_files(project_root, respect_gitignore=False) == ["main.py"]
    finally:
        shutil.rmtree(tmpdir)


def test_file_already_mined_check_mtime():
    tmpdir = tempfile.mkdtemp()
    try:
        palace_path = os.path.join(tmpdir, "palace")
        os.makedirs(palace_path)
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_or_create_collection("mempalace_drawers")

        test_file = os.path.join(tmpdir, "test.txt")
        with open(test_file, "w") as f:
            f.write("hello world")

        mtime = os.path.getmtime(test_file)

        # Not mined yet
        assert file_already_mined(col, test_file) is False
        assert file_already_mined(col, test_file, check_mtime=True) is False

        # Add it with mtime
        col.add(
            ids=["d1"],
            documents=["hello world"],
            metadatas=[{"source_file": test_file, "source_mtime": str(mtime)}],
        )

        # Already mined (no mtime check)
        assert file_already_mined(col, test_file) is True
        # Already mined (mtime matches)
        assert file_already_mined(col, test_file, check_mtime=True) is True

        # Modify file so mtime changes
        time.sleep(0.1)
        with open(test_file, "w") as f:
            f.write("modified content")

        # Still mined without mtime check
        assert file_already_mined(col, test_file) is True
        # Needs re-mining with mtime check
        assert file_already_mined(col, test_file, check_mtime=True) is False

        # Record with no mtime stored should return False for check_mtime
        col.add(
            ids=["d2"],
            documents=["other"],
            metadatas=[{"source_file": "/fake/no_mtime.txt"}],
        )
        assert file_already_mined(col, "/fake/no_mtime.txt", check_mtime=True) is False
    finally:
        shutil.rmtree(tmpdir)


def test_project_mining_refreshes_without_duplicates_and_reports_unchanged(capsys):
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        write_project_config(project_root)
        source = project_root / "notes.txt"
        write_file(source, ("billing invoice payment details\n" * 40).strip())
        palace_path = project_root / "palace"

        mine(str(project_root), str(palace_path))
        col = get_collection(palace_path)
        first_rows = get_source_rows(col, source, "test_project")
        assert first_rows
        assert {meta["room"] for _, _, meta in first_rows} == {"billing"}
        assert all(meta["ingest_mode"] == "projects" for _, _, meta in first_rows)
        assert all(meta["refresh_owner"] == "projects" for _, _, meta in first_rows)
        assert all(meta["source_signature"] for _, _, meta in first_rows)
        assert all(meta["pipeline_fingerprint"] for _, _, meta in first_rows)

        capsys.readouterr()
        mine(str(project_root), str(palace_path))
        output = capsys.readouterr().out
        second_rows = get_source_rows(col, source, "test_project")

        assert "Files unchanged: 1" in output
        assert {row[0] for row in second_rows} == {row[0] for row in first_rows}
    finally:
        shutil.rmtree(tmpdir)


def test_project_mining_updates_changed_files_and_replaces_stale_room_rows(capsys):
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        write_project_config(project_root)
        source = project_root / "notes.txt"
        write_file(source, ("billing invoice payment details\n" * 40).strip())
        palace_path = project_root / "palace"

        mine(str(project_root), str(palace_path))
        col = get_collection(palace_path)
        first_rows = get_source_rows(col, source, "test_project")

        write_file(source, ("auth oauth token login flow\n" * 40).strip())
        capsys.readouterr()
        mine(str(project_root), str(palace_path))
        output = capsys.readouterr().out
        updated_rows = get_source_rows(col, source, "test_project")

        assert "Files updated: 1" in output
        assert {meta["room"] for _, _, meta in updated_rows} == {"auth"}
        assert {row[0] for row in updated_rows}.isdisjoint({row[0] for row in first_rows})
    finally:
        shutil.rmtree(tmpdir)


def test_project_mining_keeps_namespaces_per_wing():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        write_project_config(project_root, wing="alpha")
        source = project_root / "notes.txt"
        write_file(source, ("billing invoice payment details\n" * 40).strip())
        palace_path = project_root / "palace"

        mine(str(project_root), str(palace_path), wing_override="alpha")
        mine(str(project_root), str(palace_path), wing_override="beta")

        col = get_collection(palace_path)
        results = col.get(where={"source_file": str(source.resolve())}, include=["metadatas"])

        assert col.count() > 0
        assert {meta["wing"] for meta in results["metadatas"]} == {"alpha", "beta"}
    finally:
        shutil.rmtree(tmpdir)


def test_project_mining_clears_empty_content_only_for_that_namespace(capsys):
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        write_project_config(project_root)
        source = project_root / "notes.txt"
        write_file(source, ("billing invoice payment details\n" * 40).strip())
        palace_path = project_root / "palace"

        mine(str(project_root), str(palace_path), wing_override="alpha")
        mine(str(project_root), str(palace_path), wing_override="beta")
        col = get_collection(palace_path)

        write_file(source, "")
        capsys.readouterr()
        mine(str(project_root), str(palace_path), wing_override="alpha")
        output = capsys.readouterr().out

        alpha_rows = get_source_rows(col, source, "alpha")
        beta_rows = get_source_rows(col, source, "beta")
        assert "Files cleared: 1" in output
        assert alpha_rows == []
        assert beta_rows
    finally:
        shutil.rmtree(tmpdir)


def test_project_mining_preserves_old_drawers_on_read_error(monkeypatch, capsys):
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        write_project_config(project_root)
        source = project_root / "notes.txt"
        write_file(source, ("billing invoice payment details\n" * 40).strip())
        palace_path = project_root / "palace"

        mine(str(project_root), str(palace_path))
        col = get_collection(palace_path)
        first_rows = get_source_rows(col, source, "test_project")

        original_read_text = Path.read_text

        def broken_read_text(self, *args, **kwargs):
            if self.resolve() == source.resolve():
                raise OSError("boom")
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", broken_read_text)
        capsys.readouterr()
        mine(str(project_root), str(palace_path))
        output = capsys.readouterr().out

        assert "Files errored: 1" in output
        assert {row[0] for row in get_source_rows(col, source, "test_project")} == {
            row[0] for row in first_rows
        }
    finally:
        shutil.rmtree(tmpdir)


def test_legacy_project_rows_are_upgraded_on_first_refresh():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        write_project_config(project_root)
        source = project_root / "notes.txt"
        content = ("billing invoice payment details\n" * 40).strip()
        write_file(source, content)
        palace_path = project_root / "palace"

        from mempalace.miner import build_drawer_id, chunk_text

        client = chromadb.PersistentClient(path=str(palace_path))
        col = client.get_or_create_collection("mempalace_drawers")
        chunks = chunk_text(content, str(source.resolve()))
        col.upsert(
            ids=[
                build_drawer_id("test_project", "billing", str(source.resolve()), chunk["chunk_index"])
                for chunk in chunks
            ],
            documents=[chunk["content"] for chunk in chunks],
            metadatas=[
                {
                    "wing": "test_project",
                    "room": "billing",
                    "source_file": str(source.resolve()),
                    "chunk_index": chunk["chunk_index"],
                    "added_by": "legacy",
                    "filed_at": "2026-01-01T00:00:00",
                }
                for chunk in chunks
            ],
        )

        mine(str(project_root), str(palace_path))
        rows = get_source_rows(col, source, "test_project")

        assert rows
        assert all(meta["ingest_mode"] == "projects" for _, _, meta in rows)
        assert all(meta["refresh_owner"] == "projects" for _, _, meta in rows)
        assert all(meta["source_signature"] for _, _, meta in rows)
        assert all(meta["pipeline_fingerprint"] for _, _, meta in rows)
    finally:
        shutil.rmtree(tmpdir)


def test_manual_drawers_with_same_source_file_survive_project_refresh(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        write_project_config(project_root)
        source = project_root / "notes.txt"
        write_file(source, ("billing invoice payment details\n" * 40).strip())
        palace_path = project_root / "palace"

        from mempalace import mcp_server
        from mempalace.mcp_server import tool_add_drawer

        monkeypatch.setattr(
            mcp_server,
            "_config",
            SimpleNamespace(
                palace_path=str(palace_path),
                collection_name="mempalace_drawers",
            ),
        )

        result = tool_add_drawer(
            wing="test_project",
            room="manual_notes",
            content="Remember the migration checklist.",
            source_file=str(source.resolve()),
            added_by="test",
        )
        assert result["success"] is True

        mine(str(project_root), str(palace_path))
        col = get_collection(palace_path)
        rows = get_source_rows(col, source, "test_project")

        assert any(doc == "Remember the migration checklist." for _, doc, _ in rows)
        assert any(meta.get("ingest_mode") == "manual" for _, _, meta in rows)
        assert any(meta.get("ingest_mode") == "projects" for _, _, meta in rows)
    finally:
        shutil.rmtree(tmpdir)
