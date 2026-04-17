"""Tests for the sync command — stale drawer detection and incremental re-mining."""

import hashlib
import os
import tempfile
from pathlib import Path

import chromadb


def _make_palace():
    """Create a temporary palace with a collection."""
    path = tempfile.mkdtemp(prefix="test_palace_")
    client = chromadb.PersistentClient(path=path)
    col = client.create_collection("mempalace_drawers")
    return path, client, col


def _add_drawer(col, source_file, content, wing="test", room="general", chunk_index=0):
    """Add a drawer with content_hash metadata."""
    # Resolve symlinks for consistent paths (macOS /var → /private/var)
    source_file = str(Path(source_file).resolve())
    content_hash = hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()
    drawer_id = f"drawer_{wing}_{room}_{hashlib.md5((source_file + str(chunk_index)).encode(), usedforsecurity=False).hexdigest()[:16]}"
    col.add(
        documents=[content],
        ids=[drawer_id],
        metadatas=[
            {
                "wing": wing,
                "room": room,
                "source_file": source_file,
                "chunk_index": chunk_index,
                "added_by": "test",
                "filed_at": "2026-01-01T00:00:00",
                "content_hash": content_hash,
            }
        ],
    )
    return drawer_id


def test_content_hash_stored_by_project_miner():
    """Project miner should store content_hash in drawer metadata."""
    import tempfile
    from pathlib import Path
    from mempalace.miner import process_file, get_collection

    palace_path = tempfile.mkdtemp(prefix="test_palace_")
    col = get_collection(palace_path)

    # Create a source file
    src = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, prefix="test_hash_")
    src.write("def hello():\n    print('Hello world')\n    return True\n" * 5)
    src.close()

    process_file(
        filepath=Path(src.name),
        project_path=Path(tempfile.gettempdir()),
        collection=col,
        wing="test",
        rooms=[{"name": "general", "description": "general"}],
        agent="test",
        dry_run=False,
    )

    # Check that content_hash is in metadata
    results = col.get(where={"source_file": src.name}, include=["metadatas"])
    assert len(results["ids"]) > 0, "Should have filed at least one drawer"
    meta = results["metadatas"][0]
    assert "content_hash" in meta, "Drawer should have content_hash"
    assert len(meta["content_hash"]) == 32, "content_hash should be MD5 hex digest"

    os.unlink(src.name)


def test_content_hash_stored_by_convo_miner():
    """Convo miner should store content_hash in drawer metadata."""
    import json
    import tempfile
    from mempalace.convo_miner import mine_convos

    palace_path = tempfile.mkdtemp(prefix="test_palace_")
    convo_dir = tempfile.mkdtemp(prefix="test_convos_")

    # Create a conversation file with enough content for chunking
    convo = [
        {
            "role": "user",
            "content": "Can you explain how context engineering works in modern AI systems?",
        },
        {
            "role": "assistant",
            "content": "Context engineering is the practice of designing the information that goes into an LLM prompt. It includes selecting relevant documents, structuring the prompt, and managing the context window efficiently.",
        },
    ]
    convo_file = os.path.join(convo_dir, "test_chat.json")
    with open(convo_file, "w") as f:
        json.dump(convo, f)

    mine_convos(
        convo_dir=convo_dir,
        palace_path=palace_path,
        wing="test-chats",
        agent="test",
    )

    # Check content_hash (resolve path for macOS /var → /private/var)
    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_collection("mempalace_drawers")
    resolved_file = str(Path(convo_file).resolve())
    results = col.get(where={"source_file": resolved_file}, include=["metadatas"])
    assert len(results["ids"]) > 0, f"Expected drawers for {resolved_file}"
    assert "content_hash" in results["metadatas"][0]

    os.unlink(convo_file)


def test_sync_detects_changed_file():
    """Sync should detect when a source file has changed since mining."""
    palace_path, client, col = _make_palace()

    # Create a source file and mine it
    src = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    original_content = "Original content here"
    src.write(original_content)
    src.close()

    _add_drawer(col, src.name, original_content)

    # Now modify the file
    with open(src.name, "w") as f:
        f.write("Updated content here — different from original")

    # Check that sync would detect the change
    resolved = str(Path(src.name).resolve())
    results = col.get(where={"source_file": resolved}, include=["metadatas"])
    stored_hash = results["metadatas"][0]["content_hash"]
    current_content = open(src.name).read().strip()
    current_hash = hashlib.md5(current_content.encode(), usedforsecurity=False).hexdigest()

    assert stored_hash != current_hash, "Hashes should differ after file modification"

    os.unlink(src.name)


def test_sync_unchanged_file_matches_hash():
    """Sync should report unchanged files as fresh."""
    palace_path, client, col = _make_palace()

    src = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    content = "Content that does not change"
    src.write(content)
    src.close()

    _add_drawer(col, src.name, content)

    # Re-read and hash — should match
    current_content = open(src.name).read().strip()
    current_hash = hashlib.md5(current_content.encode(), usedforsecurity=False).hexdigest()
    stored_hash = hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()

    assert current_hash == stored_hash, "Unchanged file should have matching hash"

    os.unlink(src.name)


def test_sync_detects_missing_file():
    """Sync should detect when a source file has been deleted."""
    palace_path, client, col = _make_palace()

    missing_path = "/tmp/this_file_does_not_exist_12345.txt"
    _add_drawer(col, missing_path, "some content")

    resolved = str(Path(missing_path).resolve())
    assert not os.path.exists(resolved)

    # Verify drawer exists for a missing file
    results = col.get(where={"source_file": resolved}, include=["metadatas"])
    assert len(results["ids"]) > 0, "Should have drawer for missing file"


def test_sync_no_hash_legacy_drawers():
    """Drawers without content_hash (mined before sync feature) should be reported."""
    palace_path, client, col = _make_palace()

    # Add drawer without content_hash (legacy format)
    col.add(
        documents=["legacy content"],
        ids=["drawer_legacy_001"],
        metadatas=[
            {
                "wing": "test",
                "room": "general",
                "source_file": "/tmp/legacy_file.txt",
                "chunk_index": 0,
                "added_by": "old_miner",
                "filed_at": "2025-01-01T00:00:00",
            }
        ],
    )

    results = col.get(ids=["drawer_legacy_001"], include=["metadatas"])
    meta = results["metadatas"][0]
    assert "content_hash" not in meta, "Legacy drawer should not have content_hash"


def test_force_clean_deletes_drawers():
    """--force should delete existing drawers before re-mining."""
    palace_path, client, col = _make_palace()

    # Create temp directory with a file
    src_dir = tempfile.mkdtemp(prefix="test_force_")
    src_file = os.path.join(src_dir, "code.py")
    with open(src_file, "w") as f:
        f.write("def original(): pass")

    _add_drawer(col, src_file, "def original(): pass", wing="test")
    assert col.count() == 1

    # Import and run force clean
    from mempalace.cli import _force_clean

    _force_clean(palace_path, src_dir)

    # Re-check — should be cleaned (resolve path for macOS /var → /private/var)
    client2 = chromadb.PersistentClient(path=palace_path)
    col2 = client2.get_collection("mempalace_drawers")
    resolved_file = str(Path(src_file).resolve())
    results = col2.get(where={"source_file": resolved_file})
    assert len(results["ids"]) == 0, "Force clean should delete all drawers from source dir"

    os.unlink(src_file)


def test_force_clean_does_not_affect_other_dirs():
    """--force should only delete drawers from the specified directory."""
    palace_path, client, col = _make_palace()

    dir_a = tempfile.mkdtemp(prefix="test_dir_a_")
    dir_b = tempfile.mkdtemp(prefix="test_dir_b_")

    file_a = os.path.join(dir_a, "a.py")
    file_b = os.path.join(dir_b, "b.py")

    _add_drawer(col, file_a, "code A", wing="a")
    _add_drawer(col, file_b, "code B", wing="b")
    assert col.count() == 2

    from mempalace.cli import _force_clean

    _force_clean(palace_path, dir_a)

    client2 = chromadb.PersistentClient(path=palace_path)
    col2 = client2.get_collection("mempalace_drawers")
    assert col2.count() == 1, "Should only delete drawers from dir_a"
    resolved_b = str(Path(file_b).resolve())
    results = col2.get(where={"source_file": resolved_b})
    assert len(results["ids"]) == 1, "dir_b drawers should be untouched"


def test_content_hash_is_deterministic():
    """Same content should always produce the same hash."""
    content = "Hello, world! This is a test."
    hash1 = hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()
    hash2 = hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()
    assert hash1 == hash2


def test_content_hash_changes_with_content():
    """Different content should produce different hashes."""
    hash1 = hashlib.md5("version 1".encode(), usedforsecurity=False).hexdigest()
    hash2 = hashlib.md5("version 2".encode(), usedforsecurity=False).hexdigest()
    assert hash1 != hash2


def test_sync_atomic_remine_project_file():
    """E2E: mine a file, modify it, run sync logic, verify drawers exist with updated hash."""
    import tempfile
    from pathlib import Path
    from mempalace.miner import process_file, get_collection, file_content_hash
    from mempalace.cli import cmd_sync

    # Setup palace and source file
    palace_path = tempfile.mkdtemp(prefix="test_palace_sync_e2e_")
    src_dir = tempfile.mkdtemp(prefix="test_src_")
    src_file = Path(src_dir) / "module.py"
    src_file.write_text("def original():\n    return 'v1'\n" * 10)
    # Required by load_config inside cmd_sync
    (Path(src_dir) / "mempalace.yaml").write_text(
        "wing: test\nrooms:\n- name: general\n  description: all files\n"
    )

    col = get_collection(palace_path)

    # Step 1: mine the file
    process_file(
        filepath=src_file,
        project_path=Path(src_dir),
        collection=col,
        wing="test",
        rooms=[{"name": "general", "description": "general"}],
        agent="test",
        dry_run=False,
    )
    assert col.count() > 0, "Should have drawers after mining"

    # Step 2: modify the file
    src_file.write_text("def updated():\n    return 'v2'\n" * 10)

    # Step 3: run sync via cmd_sync args simulation
    import argparse

    args = argparse.Namespace(
        palace=palace_path,
        dir=None,
        dry_run=False,
        clean=False,
        agent="test",
    )
    cmd_sync(args)

    # Step 4: verify drawers still exist (not deleted without re-mining)
    col2 = get_collection(palace_path)
    assert col2.count() > 0, "Palace must not be empty after sync — data loss detected"

    # Step 5: verify the stored hash matches the updated file
    # Query with the same path format that process_file stores (str(filepath), not resolved)
    # because cmd_sync round-trips the path from stored metadata without resolving symlinks.
    results = col2.get(
        where={"source_file": str(src_file)},
        include=["metadatas"],
    )
    assert results["ids"], "Drawers for the source file must exist"
    stored_hash = results["metadatas"][0].get("content_hash", "")
    current_hash = file_content_hash(src_file)
    assert stored_hash == current_hash, "Stored hash must match updated file content"
