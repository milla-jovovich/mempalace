"""Regression tests for issue #925 — diary re-ingest must detect same-length edits.

Before the fix, ``diary_ingest`` compared ``len(text)`` to the previously
recorded byte length to decide whether a file changed. Same-length edits
(typo fix ``teh`` -> ``the``, character swaps, equal-length word substitutions)
were silently skipped and the palace kept the stale drawer — violating the
verbatim-recall promise.

The fix records a sha256 of the file content in the state file instead.
"""

import json
from pathlib import Path

from mempalace.diary_ingest import _state_file_for, ingest_diaries


def _write_diary(diary_dir: Path, name: str, body: str) -> Path:
    path = diary_dir / name
    path.write_text(body, encoding="utf-8")
    return path


def _state_for(palace_path: str, diary_dir: Path) -> dict:
    state_file = _state_file_for(palace_path, diary_dir)
    return json.loads(state_file.read_text())


def test_same_length_edit_triggers_reingest(tmp_path, palace_path):
    """A typo fix (same byte length) must re-ingest the drawer.

    Without the fix this assertion failed: the second ingest reported
    ``days_updated == 0`` and the drawer kept the stale text.
    """
    diary_dir = tmp_path / "diary"
    diary_dir.mkdir()

    original = (
        "## Morning\n"
        "teh quick brown fox jumps over the lazy dog. "
        "Some padding so the file passes the 50-char minimum length check.\n"
    )
    diary_file = _write_diary(diary_dir, "2026-04-15.md", original)
    first = ingest_diaries(diary_dir=str(diary_dir), palace_path=palace_path)
    assert first["days_updated"] == 1

    corrected = original.replace("teh quick", "the quick", 1)
    assert len(corrected) == len(original), "test premise: same-length edit"
    diary_file.write_text(corrected, encoding="utf-8")

    second = ingest_diaries(diary_dir=str(diary_dir), palace_path=palace_path)
    assert second["days_updated"] == 1, "same-length typo fix must trigger re-ingest (issue #925)"


def test_unchanged_file_is_skipped(tmp_path, palace_path):
    """Re-running ingest on an unchanged file is still a no-op."""
    diary_dir = tmp_path / "diary"
    diary_dir.mkdir()

    body = (
        "## Notes\n"
        "Stable content that is not edited between ingest runs. "
        "Long enough to clear the 50-char minimum.\n"
    )
    _write_diary(diary_dir, "2026-04-16.md", body)

    first = ingest_diaries(diary_dir=str(diary_dir), palace_path=palace_path)
    second = ingest_diaries(diary_dir=str(diary_dir), palace_path=palace_path)

    assert first["days_updated"] == 1
    assert second["days_updated"] == 0


def test_state_file_records_sha256(tmp_path, palace_path):
    """State file must persist the content hash, not byte length."""
    diary_dir = tmp_path / "diary"
    diary_dir.mkdir()

    body = (
        "## Entry\n"
        "Content used to verify the on-disk state schema. "
        "Padding to clear the 50-char minimum length.\n"
    )
    _write_diary(diary_dir, "2026-04-17.md", body)

    ingest_diaries(diary_dir=str(diary_dir), palace_path=palace_path)
    state = _state_for(palace_path, diary_dir.resolve())
    entry = next(iter(state.values()))
    assert "sha256" in entry and len(entry["sha256"]) == 64
    assert "size" not in entry  # legacy key removed
