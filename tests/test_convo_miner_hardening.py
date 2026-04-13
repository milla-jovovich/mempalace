"""Additional coverage for conversation mining edge cases."""

from pathlib import Path
from unittest.mock import patch

from mempalace import convo_miner


def test_scan_convos_skips_symlinks_and_files_that_fail_stat(tmp_path, monkeypatch):
    real_file = tmp_path / "chat.txt"
    real_file.write_text("real transcript", encoding="utf-8")
    broken_file = tmp_path / "broken.md"
    broken_file.write_text("broken transcript", encoding="utf-8")
    symlink = tmp_path / "link.txt"
    symlink.symlink_to(real_file)

    original_stat = Path.stat

    def _fake_stat(self, *args, **kwargs):
        if self.name == "broken.md" and kwargs.get("follow_symlinks", True):
            raise OSError("gone")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", _fake_stat)

    files = convo_miner.scan_convos(str(tmp_path))

    names = {path.name for path in files}
    assert "chat.txt" in names
    assert "broken.md" not in names
    assert "link.txt" not in names


def test_mine_convos_dry_run_general_mode_tracks_memory_types(tmp_path, capsys):
    source = tmp_path / "chat.jsonl"
    source.write_text("placeholder", encoding="utf-8")

    memories = [
        {
            "content": "We decided to checkpoint schema writes before any background reindex work.",
            "chunk_index": 0,
            "memory_type": "decisions",
        },
        {
            "content": "The main problem is stale workers serving old assumptions during rollback.",
            "chunk_index": 1,
            "memory_type": "problems",
        },
    ]

    with patch("mempalace.convo_miner.scan_convos", return_value=[source, source]), patch(
        "mempalace.convo_miner.normalize",
        return_value=(
            "This normalized conversation is long enough for extraction and mentions migration "
            "guardrails, rollback planning, and owner handoff requirements."
        ),
    ), patch("mempalace.general_extractor.extract_memories", return_value=memories):
        convo_miner.mine_convos(
            str(tmp_path),
            str(tmp_path / "palace"),
            limit=1,
            dry_run=True,
            extract_mode="general",
        )

    output = capsys.readouterr().out
    assert "DRY RUN" in output
    assert "decisions:1" in output
    assert "problems:1" in output
    assert f"Wing:    {tmp_path.name}" in output


def test_mine_convos_skips_already_mined_unreadable_short_and_empty_chunks(tmp_path, capsys):
    skip_file = tmp_path / "skip.txt"
    error_file = tmp_path / "error.txt"
    short_file = tmp_path / "short.txt"
    empty_chunk_file = tmp_path / "empty.txt"
    for path in (skip_file, error_file, short_file, empty_chunk_file):
        path.write_text("placeholder", encoding="utf-8")

    def _already_mined(_collection, source_file):
        return source_file.endswith("skip.txt")

    def _normalize(path):
        if path.endswith("error.txt"):
            raise OSError("bad read")
        if path.endswith("short.txt"):
            return "tiny"
        return "This transcript is long enough to reach chunking, but the chunker returns nothing."

    with patch(
        "mempalace.convo_miner.scan_convos",
        return_value=[skip_file, error_file, short_file, empty_chunk_file],
    ), patch("mempalace.convo_miner.get_collection", return_value=object()), patch(
        "mempalace.convo_miner.get_support_collection",
        return_value=object(),
    ), patch(
        "mempalace.convo_miner.file_already_mined",
        side_effect=_already_mined,
    ), patch("mempalace.convo_miner.normalize", side_effect=_normalize), patch(
        "mempalace.convo_miner.chunk_exchanges",
        return_value=[],
    ):
        convo_miner.mine_convos(str(tmp_path), str(tmp_path / "palace"), wing="fixtures")

    output = capsys.readouterr().out
    assert "Files skipped (already filed): 1" in output
    assert "Drawers filed: 0" in output


def test_mine_convos_ignores_duplicate_upsert_errors_in_general_mode(tmp_path, capsys):
    source = tmp_path / "chat.jsonl"
    source.write_text("placeholder", encoding="utf-8")

    memories = [
        {
            "content": "Decision memory about rollback checkpoints and owner handoff.",
            "chunk_index": 0,
            "memory_type": "decisions",
        },
        {
            "content": "Problem memory about stale caches after migration rollback.",
            "chunk_index": 1,
            "memory_type": "problems",
        },
    ]

    class _Collection:
        def __init__(self):
            self.calls = 0

        def upsert(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise Exception("already exists")

    class _SupportCollection:
        def upsert(self, **kwargs):
            return None

    with patch("mempalace.convo_miner.scan_convos", return_value=[source]), patch(
        "mempalace.convo_miner.get_collection",
        return_value=_Collection(),
    ), patch(
        "mempalace.convo_miner.get_support_collection",
        return_value=_SupportCollection(),
    ), patch("mempalace.convo_miner.file_already_mined", return_value=False), patch(
        "mempalace.convo_miner.normalize",
        return_value="This conversation is long enough to extract memories about rollback and release safety.",
    ), patch("mempalace.general_extractor.extract_memories", return_value=memories):
        convo_miner.mine_convos(
            str(tmp_path),
            str(tmp_path / "palace"),
            wing="fixtures",
            extract_mode="general",
        )

    output = capsys.readouterr().out
    assert "Drawers filed: 1" in output
    assert "problems" in output


def test_mine_convos_raises_non_duplicate_upsert_errors(tmp_path):
    source = tmp_path / "chat.jsonl"
    source.write_text("placeholder", encoding="utf-8")

    memories = [{"content": "Decision memory about migration safety and rollback.", "chunk_index": 0}]

    class _Collection:
        def upsert(self, **kwargs):
            raise RuntimeError("disk full")

    class _SupportCollection:
        def upsert(self, **kwargs):
            return None

    with patch("mempalace.convo_miner.scan_convos", return_value=[source]), patch(
        "mempalace.convo_miner.get_collection",
        return_value=_Collection(),
    ), patch(
        "mempalace.convo_miner.get_support_collection",
        return_value=_SupportCollection(),
    ), patch("mempalace.convo_miner.file_already_mined", return_value=False), patch(
        "mempalace.convo_miner.normalize",
        return_value="This conversation is long enough to extract one memory about rollback preparedness.",
    ), patch("mempalace.general_extractor.extract_memories", return_value=memories):
        try:
            convo_miner.mine_convos(
                str(tmp_path),
                str(tmp_path / "palace"),
                wing="fixtures",
                extract_mode="general",
            )
            assert False, "Expected mine_convos to re-raise non-duplicate upsert errors"
        except RuntimeError as exc:
            assert "disk full" in str(exc)


def test_mine_convos_passes_support_collection_to_add_drawer(tmp_path):
    source = tmp_path / "chat.jsonl"
    source.write_text("placeholder", encoding="utf-8")
    raw_collection = object()
    support_collection = object()

    with patch("mempalace.convo_miner.scan_convos", return_value=[source]), patch(
        "mempalace.convo_miner.get_collection",
        return_value=raw_collection,
    ), patch(
        "mempalace.convo_miner.get_support_collection",
        return_value=support_collection,
    ), patch("mempalace.convo_miner.file_already_mined", return_value=False), patch(
        "mempalace.convo_miner.normalize",
        return_value="This conversation is long enough to reach chunking and contain a preference signal.",
    ), patch(
        "mempalace.convo_miner.chunk_exchanges",
        return_value=[{"content": "> I prefer long battery life\nWe should compare models.", "chunk_index": 0}],
    ), patch("mempalace.convo_miner.add_drawer") as mock_add_drawer:
        convo_miner.mine_convos(str(tmp_path), str(tmp_path / "palace"), wing="fixtures")

    assert mock_add_drawer.call_args.kwargs["collection"] is raw_collection
    assert mock_add_drawer.call_args.kwargs["support_collection"] is support_collection
    assert mock_add_drawer.call_args.kwargs["ingest_mode"] == "convos"
