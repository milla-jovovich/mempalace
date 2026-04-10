import os
import shutil
import tempfile
from pathlib import Path

import chromadb
import yaml

from mempalace.miner import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    MIN_CHUNK_SIZE,
    chunk_text,
    detect_room,
    mine,
    scan_project,
)
from mempalace.palace import file_already_mined


def write_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def scanned_files(project_root: Path, **kwargs):
    files = scan_project(str(project_root), **kwargs)
    return sorted(path.relative_to(project_root).as_posix() for path in files)


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

        # Modify file and force a different mtime (Windows has low mtime resolution)
        with open(test_file, "w") as f:
            f.write("modified content")
        os.utime(test_file, (mtime + 10, mtime + 10))

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
        # Release ChromaDB file handles before cleanup (required on Windows)
        del col, client
        shutil.rmtree(tmpdir, ignore_errors=True)


# =============================================================================
# detect_room tests
# =============================================================================

SAMPLE_ROOMS = [
    {"name": "backend", "description": "Backend code", "keywords": ["api", "server"]},
    {"name": "frontend", "description": "Frontend code", "keywords": ["ui", "component"]},
    {"name": "tests", "description": "Test files", "keywords": ["test", "spec"]},
]


def _detect(relpath: str, content: str = "", rooms: list = None):
    """Helper: call detect_room with a fake project path."""
    project = Path("/fake/project")
    filepath = project / relpath
    return detect_room(filepath, content, rooms or SAMPLE_ROOMS, project)


def test_detect_room_priority1_exact_folder_match():
    """Folder named exactly 'backend' routes to backend room."""
    assert _detect("backend/app.py") == "backend"


def test_detect_room_priority1_keyword_folder_match():
    """Folder named exactly 'api' routes to backend room (keyword match)."""
    assert _detect("api/routes.py") == "backend"


def test_detect_room_priority1_no_substring_match():
    """Folder 'components' must NOT match room 'component' keyword via substring."""
    assert _detect("components/button.py") != "frontend"


def test_detect_room_priority1_no_short_name_false_positive():
    """Folder 'src' must NOT match any room just because 'src' is a substring of something."""
    result = _detect("src/main.py", content="unrelated stuff")
    assert result == "general"


def test_detect_room_priority2_exact_filename_match():
    """Filename 'backend.py' (stem='backend') routes to backend room."""
    assert _detect("lib/backend.py") == "backend"


def test_detect_room_priority2_keyword_filename_match():
    """Filename 'api.py' (stem='api') routes to backend via keyword."""
    assert _detect("lib/api.py") == "backend"


def test_detect_room_priority2_no_substring_match():
    """Filename 'testing.py' must NOT match 'tests' room via substring."""
    result = _detect("lib/testing.py", content="unrelated stuff")
    assert result != "tests"


def test_detect_room_priority3_keyword_scoring():
    """Content with repeated 'api' keyword routes to backend room."""
    content = "the api handles requests. api calls are fast. api is great."
    assert _detect("misc/readme.txt", content=content) == "backend"


def test_detect_room_priority3_word_boundary():
    """'test' inside 'testing'/'latest'/'contest' must NOT count as keyword hits."""
    # Only has 'test' embedded in other words, never standalone
    content = "testing the latest contest results for attestation"
    result = _detect("misc/notes.txt", content=content)
    assert result != "tests"


def test_detect_room_priority3_word_boundary_standalone():
    """Standalone 'test' words DO count as keyword hits."""
    content = "run the test suite. each test verifies correctness. test passed."
    assert _detect("misc/notes.txt", content=content) == "tests"


def test_detect_room_priority4_fallback_general():
    """No matches at all falls back to 'general'."""
    assert _detect("misc/random.txt", content="nothing relevant here") == "general"


def test_detect_room_priority4_empty_content():
    """Empty content with no path/filename match falls back to 'general'."""
    assert _detect("misc/random.txt", content="") == "general"


def test_detect_room_folder_beats_content():
    """Priority 1 (folder) wins even when content strongly matches another room."""
    content = "test test test test test test test"
    assert _detect("backend/app.py", content=content) == "backend"


def test_detect_room_filename_beats_content():
    """Priority 2 (filename) wins even when content strongly matches another room."""
    content = "test test test test test test test"
    assert _detect("misc/backend.py", content=content) == "backend"


# =============================================================================
# chunk_text tests
# =============================================================================


def test_chunk_text_short_content():
    """Content shorter than CHUNK_SIZE produces a single chunk."""
    content = "a" * (CHUNK_SIZE - 1)
    chunks = chunk_text(content, "/fake/file.py")
    assert len(chunks) == 1
    assert chunks[0]["content"] == content
    assert chunks[0]["chunk_index"] == 0


def test_chunk_text_exact_chunk_size():
    """Content exactly CHUNK_SIZE long produces a single chunk."""
    content = "a" * CHUNK_SIZE
    chunks = chunk_text(content, "/fake/file.py")
    assert len(chunks) == 1
    assert chunks[0]["content"] == content


def test_chunk_text_two_chunks():
    """Content slightly over CHUNK_SIZE produces two chunks with overlap."""
    content = "a" * (CHUNK_SIZE + 1)
    chunks = chunk_text(content, "/fake/file.py")
    assert len(chunks) == 2


def test_chunk_text_overlap_content():
    """The second chunk starts at CHUNK_SIZE - CHUNK_OVERLAP (overlap region)."""
    # Use digits so each position is unique and verifiable
    content = "".join(str(i % 10) for i in range(CHUNK_SIZE + 200))
    chunks = chunk_text(content, "/fake/file.py")
    assert len(chunks) >= 2
    # The overlap means the second chunk's content starts from the overlap region
    expected_start = CHUNK_SIZE - CHUNK_OVERLAP
    assert chunks[1]["content"].startswith(content[expected_start : expected_start + 10])


def test_chunk_text_chunk_indices():
    """chunk_index values increment sequentially starting from 0."""
    content = "a" * (CHUNK_SIZE * 3)
    chunks = chunk_text(content, "/fake/file.py")
    assert len(chunks) >= 3
    for i, chunk in enumerate(chunks):
        assert chunk["chunk_index"] == i


def test_chunk_text_empty_content():
    """Empty string returns an empty list."""
    chunks = chunk_text("", "/fake/file.py")
    assert chunks == []


def test_chunk_text_below_min_size():
    """Content below MIN_CHUNK_SIZE returns an empty list."""
    content = "a" * (MIN_CHUNK_SIZE - 1)
    chunks = chunk_text(content, "/fake/file.py")
    assert chunks == []


def test_chunk_text_whitespace_only():
    """Whitespace-only content returns an empty list (stripped to empty)."""
    chunks = chunk_text("   \n\n\t  \n  ", "/fake/file.py")
    assert chunks == []

def test_chunk_text_many_chunks():
    """Very long content (10x CHUNK_SIZE) produces the correct number of chunks."""
    content = "a" * (CHUNK_SIZE * 10)
    chunks = chunk_text(content, "/fake/file.py")
    # With overlap, each chunk after the first starts CHUNK_SIZE - CHUNK_OVERLAP ahead.
    # So we need ceil((total_len - CHUNK_OVERLAP) / (CHUNK_SIZE - CHUNK_OVERLAP)) chunks,
    # but the exact count depends on boundary logic. Just verify it's reasonable.
    total_len = len(content)
    step = CHUNK_SIZE - CHUNK_OVERLAP
    expected_min = total_len // CHUNK_SIZE  # at least this many
    expected_max = (total_len // step) + 1  # at most this many
    assert expected_min <= len(chunks) <= expected_max


def test_chunk_text_preserves_content():
    """All original content is covered by the union of chunks (nothing lost)."""
    # Use position-unique tokens so we can verify each segment appears in a chunk
    tokens = [f"[T{i:04d}]" for i in range(300)]
    content = " ".join(tokens)
    chunks = chunk_text(content, "/fake/file.py")
    assert len(chunks) >= 2
    # Every unique token must appear in at least one chunk
    all_chunk_text = "".join(c["content"] for c in chunks)
    for token in tokens:
        assert token in all_chunk_text, f"Token '{token}' not found in any chunk"
    # The joined chunks should contain at least as many characters as the original
    # (overlap means more, confirming nothing is dropped)
    assert len(all_chunk_text) >= len(content)
