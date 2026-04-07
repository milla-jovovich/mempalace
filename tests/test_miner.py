import json
import tempfile
from pathlib import Path

import chromadb
import pytest
import yaml

from mempalace.config import DEFAULT_COLLECTION_NAME
from mempalace.layers import MemoryStack
from mempalace.mcp_server import tool_add_drawer, tool_status
from mempalace.miner import build_drawer_id, chunk_text, mine, status
from mempalace.searcher import search_memories


def write_project_config(project_dir: Path, wing: str = "test_project"):
    (project_dir / "mempalace.yaml").write_text(
        yaml.dump(
            {
                "wing": wing,
                "rooms": [
                    {"name": "billing", "description": "Billing work", "keywords": ["invoice", "billing", "payment"]},
                    {"name": "auth", "description": "Authentication", "keywords": ["auth", "oauth", "token"]},
                    {"name": "general", "description": "General"},
                ],
            }
        )
    )


def get_collection(palace_path: Path, collection_name: str = "mempalace_drawers"):
    client = chromadb.PersistentClient(path=str(palace_path))
    return client.get_collection(collection_name)


def write_global_config(palace_path: Path, collection_name: str = DEFAULT_COLLECTION_NAME):
    config_dir = Path.home() / ".mempalace"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "palace_path": str(palace_path),
                "collection_name": collection_name,
            }
        )
    )


def get_source_rows(col, source_file: Path, wing: str):
    results = col.get(
        where={"$and": [{"source_file": str(source_file.resolve())}, {"wing": wing}]},
        include=["documents", "metadatas"],
    )
    return list(zip(results["ids"], results["documents"], results["metadatas"]))


def test_project_mining_refreshes_updates_and_removes_stale_room_drawers(capsys):
    tmpdir = Path(tempfile.mkdtemp())
    project_dir = tmpdir / "project"
    project_dir.mkdir()
    write_project_config(project_dir)
    notes = project_dir / "notes.txt"
    notes.write_text(("billing invoice payment details\n" * 40).strip())
    palace_path = tmpdir / "palace"

    mine(str(project_dir), str(palace_path))
    col = get_collection(palace_path)
    first_rows = get_source_rows(col, notes, "test_project")

    assert first_rows
    assert {meta["room"] for _, _, meta in first_rows} == {"billing"}
    assert all(meta["ingest_mode"] == "projects" for _, _, meta in first_rows)
    assert all(meta["source_signature"] for _, _, meta in first_rows)
    assert all(meta["pipeline_fingerprint"] for _, _, meta in first_rows)

    mine(str(project_dir), str(palace_path))
    unchanged_output = capsys.readouterr().out
    second_rows = get_source_rows(col, notes, "test_project")

    assert "Files unchanged: 1" in unchanged_output
    assert {row[0] for row in second_rows} == {row[0] for row in first_rows}

    notes.write_text(("auth oauth token login flow\n" * 35).strip())
    mine(str(project_dir), str(palace_path))
    updated_rows = get_source_rows(col, notes, "test_project")

    assert {meta["room"] for _, _, meta in updated_rows} == {"auth"}
    assert {row[0] for row in updated_rows}.isdisjoint({row[0] for row in first_rows})
    assert "oauth token" in search_memories("oauth token", palace_path=str(palace_path))["results"][0]["text"]


def test_project_mining_keeps_namespaces_per_wing():
    tmpdir = Path(tempfile.mkdtemp())
    project_dir = tmpdir / "project"
    project_dir.mkdir()
    write_project_config(project_dir, wing="alpha")
    source = project_dir / "notes.txt"
    source.write_text(("billing invoice payment details\n" * 30).strip())
    palace_path = tmpdir / "palace"

    mine(str(project_dir), str(palace_path), wing_override="alpha")
    mine(str(project_dir), str(palace_path), wing_override="beta")

    col = get_collection(palace_path)
    results = col.get(where={"source_file": str(source.resolve())}, include=["metadatas"])

    assert col.count() > 0
    assert {meta["wing"] for meta in results["metadatas"]} == {"alpha", "beta"}


def test_project_refresh_clears_empty_content_but_preserves_old_drawers_on_read_error(monkeypatch, capsys):
    tmpdir = Path(tempfile.mkdtemp())
    project_dir = tmpdir / "project"
    project_dir.mkdir()
    write_project_config(project_dir)
    source = project_dir / "notes.txt"
    source.write_text(("billing invoice payment details\n" * 30).strip())
    palace_path = tmpdir / "palace"

    mine(str(project_dir), str(palace_path))
    col = get_collection(palace_path)
    original_rows = get_source_rows(col, source, "test_project")
    assert original_rows

    source.write_text("")
    mine(str(project_dir), str(palace_path))
    cleared_output = capsys.readouterr().out
    assert "Files cleared: 1" in cleared_output
    assert get_source_rows(col, source, "test_project") == []

    source.write_text(("billing invoice payment details\n" * 30).strip())
    mine(str(project_dir), str(palace_path))
    restored_rows = get_source_rows(col, source, "test_project")
    assert restored_rows

    original_read_text = Path.read_text

    def broken_read_text(self, *args, **kwargs):
        if self.resolve() == source.resolve():
            raise OSError("boom")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", broken_read_text)
    mine(str(project_dir), str(palace_path))
    errored_output = capsys.readouterr().out

    assert "Files errored: 1" in errored_output
    assert {row[0] for row in get_source_rows(col, source, "test_project")} == {
        row[0] for row in restored_rows
    }


def test_manual_source_backed_drawers_survive_project_refresh():
    tmpdir = Path(tempfile.mkdtemp())
    project_dir = tmpdir / "project"
    project_dir.mkdir()
    write_project_config(project_dir)
    source = project_dir / "notes.txt"
    source.write_text(("billing invoice payment details\n" * 30).strip())
    palace_path = tmpdir / "palace"
    write_global_config(palace_path)

    response = tool_add_drawer(
        wing="test_project",
        room="manual_notes",
        content="Remember the migration checklist.",
        source_file=str(source.resolve()),
        added_by="test",
    )
    assert response["success"] is True

    mine(str(project_dir), str(palace_path))
    col = get_collection(palace_path)
    rows = get_source_rows(col, source, "test_project")

    assert any(doc == "Remember the migration checklist." for _, doc, _ in rows)
    assert any(meta.get("ingest_mode") == "manual" for _, _, meta in rows)
    assert any(meta.get("ingest_mode") == "projects" for _, _, meta in rows)


def test_legacy_project_rows_are_refreshed_and_rewritten_with_explicit_lifecycle_metadata():
    tmpdir = Path(tempfile.mkdtemp())
    project_dir = tmpdir / "project"
    project_dir.mkdir()
    write_project_config(project_dir)
    source = project_dir / "notes.txt"
    source.write_text(("billing invoice payment details\n" * 35).strip())
    palace_path = tmpdir / "palace"

    chunks = chunk_text(source.read_text(), str(source.resolve()))
    client = chromadb.PersistentClient(path=str(palace_path))
    col = client.get_or_create_collection(DEFAULT_COLLECTION_NAME)
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

    mine(str(project_dir), str(palace_path))
    rows = get_source_rows(col, source, "test_project")

    assert rows
    assert all(meta.get("ingest_mode") == "projects" for _, _, meta in rows)
    assert all(meta.get("refresh_owner") == "projects" for _, _, meta in rows)
    assert all(meta.get("source_signature") for _, _, meta in rows)


def test_collection_name_override_is_shared_across_mine_search_status_layers_and_mcp(capsys):
    tmpdir = Path(tempfile.mkdtemp())
    project_dir = tmpdir / "project"
    project_dir.mkdir()
    write_project_config(project_dir)
    source = project_dir / "notes.txt"
    source.write_text(("auth oauth token login flow\n" * 30).strip())
    palace_path = tmpdir / "custom-palace"
    write_global_config(palace_path, collection_name="custom_drawers")

    mine(str(project_dir), str(palace_path), collection_name="custom_drawers")

    custom_collection = get_collection(palace_path, "custom_drawers")
    assert custom_collection.count() > 0

    assert search_memories(
        "oauth token", palace_path=str(palace_path), collection_name="custom_drawers"
    )["results"]
    assert (
        MemoryStack(palace_path=str(palace_path), collection_name="custom_drawers").status()[
            "total_drawers"
        ]
        == custom_collection.count()
    )

    status(str(palace_path), collection_name="custom_drawers")
    status_output = capsys.readouterr().out
    assert "MemPalace Status" in status_output
    assert str(custom_collection.count()) in status_output

    mcp_status = tool_status()
    assert mcp_status["total_drawers"] == custom_collection.count()
    assert mcp_status["palace_path"] == str(palace_path)


def test_explicit_palace_path_defaults_to_primary_collection_even_with_custom_global_collection(capsys):
    tmpdir = Path(tempfile.mkdtemp())
    project_dir = tmpdir / "project"
    project_dir.mkdir()
    write_project_config(project_dir)
    source = project_dir / "notes.txt"
    source.write_text(("auth oauth token login flow\n" * 30).strip())
    configured_palace = tmpdir / "configured-palace"
    explicit_palace = tmpdir / "explicit-palace"
    write_global_config(configured_palace, collection_name="custom_drawers")

    mine(str(project_dir), str(explicit_palace))

    default_collection = get_collection(explicit_palace, DEFAULT_COLLECTION_NAME)
    assert default_collection.count() > 0

    assert search_memories("oauth token", palace_path=str(explicit_palace))["results"]
    assert MemoryStack(palace_path=str(explicit_palace)).status()["total_drawers"] == default_collection.count()

    status(str(explicit_palace))
    status_output = capsys.readouterr().out
    assert str(default_collection.count()) in status_output

    client = chromadb.PersistentClient(path=str(explicit_palace))
    with pytest.raises(Exception):
        client.get_collection("custom_drawers")


def test_status_counts_all_drawers_past_ten_thousand(capsys):
    tmpdir = Path(tempfile.mkdtemp())
    palace_path = tmpdir / "palace"
    client = chromadb.PersistentClient(path=str(palace_path))
    col = client.get_or_create_collection("mempalace_drawers")

    total = 10001
    for start in range(0, total, 2000):
        end = min(start + 2000, total)
        ids = [f"drawer-{index}" for index in range(start, end)]
        docs = [f"document {index}" for index in range(start, end)]
        metas = [
            {"wing": "bulk", "room": "general", "source_file": f"file-{index}.txt"}
            for index in range(start, end)
        ]
        col.upsert(ids=ids, documents=docs, metadatas=metas)

    status(str(palace_path))
    output = capsys.readouterr().out

    assert "10001 drawers" in output
