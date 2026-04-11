"""
Tests for mine_epoch tracking and revision snapshots in miner.py.

Verifies two features added alongside #521's delete-before-insert fix:
  1. Epoch tracking — each mine run increments a counter in epoch.json and
     tags every chunk with its mine_epoch.
  2. Revision snapshots — chunks are saved to revisions.jsonl before upstream's
     delete-before-insert purge, preserving a queryable history of previous
     file versions.

Run with: python -m pytest tests/test_mine_epoch_tracking.py -v
"""

import json
import time
from pathlib import Path

import pytest

from mempalace import miner
from mempalace.palace import get_collection


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def palace_dir(tmp_path):
    """Create a temporary palace directory."""
    palace = tmp_path / "palace"
    palace.mkdir()
    return str(palace)


@pytest.fixture
def project_dir(tmp_path):
    """Create a temporary project directory with a mempalace.yaml."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "mempalace.yaml").write_text(
        "wing: test_wing\n"
        "rooms:\n"
        "  - name: general\n"
        "    description: Everything\n"
    )
    return project


def _big_content(n_paragraphs: int) -> str:
    """Generate content with N distinct paragraphs, each large enough to
    produce its own chunk (CHUNK_SIZE is 800 chars)."""
    paragraphs = []
    for i in range(n_paragraphs):
        # Each paragraph is ~900 chars so chunking produces roughly 1 chunk per paragraph.
        body = f"Paragraph {i}: " + (f"content_{i} " * 80)
        paragraphs.append(body)
    return "\n\n".join(paragraphs)


# =============================================================================
# EPOCH TRACKING TESTS
# =============================================================================


def test_epoch_starts_at_zero(palace_dir):
    """A fresh palace has epoch 0."""
    assert miner._load_epoch(palace_dir) == 0


def test_epoch_increments_on_mine(palace_dir, project_dir):
    """Each mine() call increments the epoch counter."""
    (project_dir / "a.txt").write_text(_big_content(2))

    miner.mine(str(project_dir), palace_dir)
    assert miner._load_epoch(palace_dir) == 1

    # Touch the file so it gets re-mined
    time.sleep(0.01)
    (project_dir / "a.txt").write_text(_big_content(2) + "\n\nmore stuff here")

    miner.mine(str(project_dir), palace_dir)
    assert miner._load_epoch(palace_dir) == 2

    time.sleep(0.01)
    (project_dir / "a.txt").write_text(_big_content(3))
    miner.mine(str(project_dir), palace_dir)
    assert miner._load_epoch(palace_dir) == 3


def test_epoch_persisted_to_file(palace_dir, project_dir):
    """epoch.json exists after a mine run and contains current + last_mine."""
    (project_dir / "a.txt").write_text(_big_content(2))
    miner.mine(str(project_dir), palace_dir)

    epoch_file = Path(palace_dir) / "epoch.json"
    assert epoch_file.exists()

    data = json.loads(epoch_file.read_text())
    assert data["current"] == 1
    assert "last_mine" in data


def test_chunks_tagged_with_mine_epoch(palace_dir, project_dir):
    """Every drawer stored during a mine run carries the mine_epoch metadata."""
    (project_dir / "a.txt").write_text(_big_content(2))
    miner.mine(str(project_dir), palace_dir)

    collection = get_collection(palace_dir)
    result = collection.get(include=["metadatas"])
    assert len(result["ids"]) > 0
    for meta in result["metadatas"]:
        assert meta.get("mine_epoch") == 1


# =============================================================================
# STALE CHUNK EVICTION TESTS
# =============================================================================


def test_shrinking_file_evicts_orphaned_chunks(palace_dir, project_dir):
    """When a file shrinks, high-index orphan chunks are deleted."""
    target = project_dir / "a.txt"
    target.write_text(_big_content(5))  # big file → many chunks

    miner.mine(str(project_dir), palace_dir)

    collection = get_collection(palace_dir)
    initial_result = collection.get(where={"source_file": str(target)}, include=["metadatas"])
    initial_count = len(initial_result["ids"])
    assert initial_count >= 5, f"expected >=5 chunks from 5 paragraphs, got {initial_count}"

    # Shrink the file to just 1 paragraph
    time.sleep(0.01)
    target.write_text(_big_content(1))

    miner.mine(str(project_dir), palace_dir)

    # Re-check — orphaned high-index chunks should be gone
    final_result = collection.get(where={"source_file": str(target)}, include=["metadatas"])
    final_count = len(final_result["ids"])

    assert final_count < initial_count, (
        f"expected fewer chunks after shrinking, "
        f"had {initial_count} before, {final_count} after"
    )

    # No chunk_index should exceed what the new content produces
    indices = [m.get("chunk_index", 0) for m in final_result["metadatas"]]
    assert max(indices) < initial_count, "orphaned high-index chunks not cleaned up"


def test_unchanged_file_not_reprocessed(palace_dir, project_dir):
    """Mining twice without changes doesn't create duplicate chunks."""
    (project_dir / "a.txt").write_text(_big_content(3))

    miner.mine(str(project_dir), palace_dir)
    collection = get_collection(palace_dir)
    first_count = len(collection.get()["ids"])

    # Mine again — the file hasn't changed
    miner.mine(str(project_dir), palace_dir)
    second_count = len(collection.get()["ids"])

    assert first_count == second_count, (
        f"unchanged file was re-processed: {first_count} → {second_count}"
    )


def test_growing_file_keeps_all_chunks(palace_dir, project_dir):
    """When a file grows, new chunks are added alongside existing ones."""
    target = project_dir / "a.txt"
    target.write_text(_big_content(2))

    miner.mine(str(project_dir), palace_dir)
    collection = get_collection(palace_dir)
    initial_count = len(
        collection.get(where={"source_file": str(target)})["ids"]
    )

    time.sleep(0.01)
    target.write_text(_big_content(5))  # grow
    miner.mine(str(project_dir), palace_dir)

    final_count = len(
        collection.get(where={"source_file": str(target)})["ids"]
    )
    assert final_count > initial_count, "growing file should produce more chunks"


# =============================================================================
# REVISION SNAPSHOT TESTS
# =============================================================================


def test_revisions_jsonl_created_when_chunks_evicted(palace_dir, project_dir):
    """Shrinking a file produces entries in revisions.jsonl."""
    target = project_dir / "a.txt"
    target.write_text(_big_content(5))

    miner.mine(str(project_dir), palace_dir)

    revisions_path = Path(palace_dir) / "revisions.jsonl"
    assert not revisions_path.exists(), "no revisions expected before any shrinking"

    # Shrink
    time.sleep(0.01)
    target.write_text(_big_content(1))
    miner.mine(str(project_dir), palace_dir)

    assert revisions_path.exists(), "revisions.jsonl should exist after chunks evicted"

    lines = revisions_path.read_text().strip().splitlines()
    assert len(lines) > 0, "expected at least one revision record"

    for line in lines:
        record = json.loads(line)
        # All required fields present
        assert "superseded_at" in record
        assert "superseded_by_epoch" in record
        assert "source_file" in record
        assert "chunk_index" in record
        assert "content" in record
        assert "original_epoch" in record
        assert record["superseded_by_epoch"] == 2  # second mine run
        assert record["original_epoch"] == 1       # from first mine run


def test_revision_content_preserves_original_text(palace_dir, project_dir):
    """The snapshotted revision contains the exact content that was deleted."""
    target = project_dir / "a.txt"
    # Put unique, recognizable content in the file
    unique = "UNIQUE_MARKER_STRING_XYZZY_12345"
    content = (
        _big_content(3)
        + "\n\n"
        + f"Special paragraph with {unique}: " + ("data " * 150)
    )
    target.write_text(content)

    miner.mine(str(project_dir), palace_dir)

    # Shrink to remove the special paragraph
    time.sleep(0.01)
    target.write_text(_big_content(1))
    miner.mine(str(project_dir), palace_dir)

    revisions_path = Path(palace_dir) / "revisions.jsonl"
    records = [json.loads(line) for line in revisions_path.read_text().splitlines() if line.strip()]

    # At least one revision should contain our unique marker
    found = any(unique in r["content"] for r in records)
    assert found, (
        f"unique marker {unique!r} not found in any revision record — "
        "revision content was not preserved correctly"
    )


def test_revisions_accumulate_across_multiple_mines(palace_dir, project_dir):
    """Each shrinking run adds to revisions.jsonl without clobbering previous ones."""
    target = project_dir / "a.txt"

    target.write_text(_big_content(5))
    miner.mine(str(project_dir), palace_dir)

    time.sleep(0.01)
    target.write_text(_big_content(3))
    miner.mine(str(project_dir), palace_dir)

    revisions_path = Path(palace_dir) / "revisions.jsonl"
    first_count = len(revisions_path.read_text().strip().splitlines())

    time.sleep(0.01)
    target.write_text(_big_content(1))
    miner.mine(str(project_dir), palace_dir)

    second_count = len(revisions_path.read_text().strip().splitlines())
    assert second_count > first_count, (
        f"revisions.jsonl should grow across mine runs: {first_count} → {second_count}"
    )


# =============================================================================
# BACKWARD COMPATIBILITY TESTS
# =============================================================================


def test_mining_works_without_palace_path_arg():
    """process_file still works when palace_path is not provided (old callers)."""
    # Just verify the default argument path — the function signature accepts
    # palace_path="" and mine_epoch=0 as defaults, so old callers don't break.
    import inspect
    sig = inspect.signature(miner.process_file)
    assert sig.parameters["palace_path"].default == ""
    assert sig.parameters["mine_epoch"].default == 0
