"""
Tests for crash-resilient mining: checkpoint, batch writes, health check, repair.
"""

import os
import tempfile
import shutil
import yaml
import chromadb

from mempalace.miner import (
    mine,
    check_palace_health,
    repair_palace,
    get_collection,
    _find_hnsw_dir,
    DrawerBatch,
)
from mempalace.checkpoint import MineCheckpoint


def _make_project(tmpdir, num_files=5):
    """Create a minimal project with mempalace.yaml and some files."""
    os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
    for i in range(num_files):
        with open(os.path.join(tmpdir, "src", f"file_{i}.py"), "w") as f:
            f.write(f"# File {i}\n" + f"def func_{i}():\n    pass\n" * 20)
    with open(os.path.join(tmpdir, "mempalace.yaml"), "w") as f:
        yaml.dump(
            {
                "wing": "test_project",
                "rooms": [
                    {"name": "src", "description": "Source code"},
                    {"name": "general", "description": "General"},
                ],
            },
            f,
        )
    return tmpdir


# ── Checkpoint ──────────────────────────────────────────────────────


def test_checkpoint_round_trip():
    tmpdir = tempfile.mkdtemp()
    try:
        cp = MineCheckpoint(tmpdir)
        assert not cp.is_completed("/some/file.py")

        cp.mark_completed("/some/file.py", 10)
        cp.save()

        # Reload from disk
        cp2 = MineCheckpoint(tmpdir)
        assert cp2.is_completed("/some/file.py")
        assert not cp2.is_completed("/other/file.py")
        assert cp2.completed_count == 1
    finally:
        shutil.rmtree(tmpdir)


def test_checkpoint_survives_corruption():
    """If checkpoint JSON is corrupted, a fresh checkpoint is created."""
    tmpdir = tempfile.mkdtemp()
    try:
        path = os.path.join(tmpdir, "mine-checkpoint.json")
        with open(path, "w") as f:
            f.write("{corrupt json!!!}")

        cp = MineCheckpoint(tmpdir)
        assert cp.completed_count == 0  # graceful fallback
    finally:
        shutil.rmtree(tmpdir)


# ── Batch writes ────────────────────────────────────────────────────


def test_batch_flush():
    tmpdir = tempfile.mkdtemp()
    try:
        palace_path = os.path.join(tmpdir, "palace")
        collection = get_collection(palace_path)
        batch = DrawerBatch(collection, batch_size=3)

        for i in range(5):
            batch.add(
                f"id_{i}",
                f"content {i}",
                {"wing": "test", "room": "general", "source_file": "x.py", "chunk_index": i},
            )

        # 3 should have auto-flushed, 2 pending
        assert batch.pending == 2
        batch.flush()
        assert batch.pending == 0

        assert collection.count() == 5
    finally:
        shutil.rmtree(tmpdir)


def test_batch_handles_duplicates():
    tmpdir = tempfile.mkdtemp()
    try:
        palace_path = os.path.join(tmpdir, "palace")
        collection = get_collection(palace_path)

        # Pre-insert one
        collection.add(ids=["dup_0"], documents=["existing"], metadatas=[{"wing": "t", "room": "g"}])

        batch = DrawerBatch(collection, batch_size=10)
        batch.add("dup_0", "new content", {"wing": "t", "room": "g"})
        batch.add("dup_1", "another", {"wing": "t", "room": "g"})
        batch.flush()

        # Should have both entries (dup_0 keeps original, dup_1 added)
        assert collection.count() == 2
    finally:
        shutil.rmtree(tmpdir)


# ── Health check & repair ──────────────────────────────────────────


def test_health_check_healthy_palace():
    tmpdir = tempfile.mkdtemp()
    try:
        palace_path = os.path.join(tmpdir, "palace")
        collection = get_collection(palace_path)
        collection.add(
            ids=["test_1"],
            documents=["hello"],
            metadatas=[{"wing": "w", "room": "r"}],
        )
        assert check_palace_health(palace_path) is True
    finally:
        shutil.rmtree(tmpdir)


def test_health_check_no_palace():
    assert check_palace_health("/nonexistent/path/palace") is False


def test_repair_force():
    tmpdir = tempfile.mkdtemp()
    try:
        palace_path = os.path.join(tmpdir, "palace")
        collection = get_collection(palace_path)
        collection.add(
            ids=["test_1"],
            documents=["hello"],
            metadatas=[{"wing": "w", "room": "r"}],
        )

        hnsw_dir = _find_hnsw_dir(palace_path)
        assert hnsw_dir is not None
        assert os.path.exists(os.path.join(hnsw_dir, "link_lists.bin"))

        repaired = repair_palace(palace_path, force=True)
        assert repaired is True
        assert not os.path.exists(os.path.join(hnsw_dir, "link_lists.bin"))
    finally:
        shutil.rmtree(tmpdir)


# ── End-to-end: mine with checkpoint ───────────────────────────────


def test_mine_creates_checkpoint():
    tmpdir = tempfile.mkdtemp()
    try:
        project_dir = _make_project(os.path.join(tmpdir, "project"))
        palace_path = os.path.join(tmpdir, "palace")

        mine(project_dir, palace_path)

        # Checkpoint file should exist
        cp_path = os.path.join(palace_path, "mine-checkpoint.json")
        assert os.path.exists(cp_path)

        cp = MineCheckpoint(palace_path)
        assert cp.completed_count > 0
    finally:
        shutil.rmtree(tmpdir)


def test_mine_resumes_from_checkpoint():
    tmpdir = tempfile.mkdtemp()
    try:
        project_dir = _make_project(os.path.join(tmpdir, "project"), num_files=3)
        palace_path = os.path.join(tmpdir, "palace")

        # First run
        mine(project_dir, palace_path)
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
        count_after_first = col.count()

        # Second run — should skip all files via checkpoint
        mine(project_dir, palace_path)
        client2 = chromadb.PersistentClient(path=palace_path)
        col2 = client2.get_collection("mempalace_drawers")
        count_after_second = col2.count()

        assert count_after_second == count_after_first
    finally:
        shutil.rmtree(tmpdir)
