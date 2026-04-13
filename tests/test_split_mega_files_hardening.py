"""Additional coverage for mega-file splitting, especially the CLI driver."""

import sys
from pathlib import Path

from mempalace import split_mega_files as smf


def _write_mega_file(path: Path, sessions: int = 2):
    chunks = []
    for idx in range(sessions):
        chunks.extend(
            [
                "Claude Code v1.0\n",
                f"⏺ 1:0{idx} PM Monday, January 0{idx + 1}, 2026\n",
                f"> What about deployment topic {idx}?\n",
            ]
            + [f"Line {line} for session {idx}\n" for line in range(12)]
        )
    path.write_text("".join(chunks), encoding="utf-8")


def test_split_file_skips_oversized_input(tmp_path, monkeypatch, capsys):
    source = tmp_path / "mega.txt"
    source.write_text("placeholder", encoding="utf-8")
    original_stat = Path.stat

    def _fake_stat(self, *args, **kwargs):
        stat = original_stat(self, *args, **kwargs)
        if self == source:
            class _FakeStat:
                st_size = 600 * 1024 * 1024

            return _FakeStat()
        return stat

    monkeypatch.setattr(Path, "stat", _fake_stat)

    assert smf.split_file(str(source), str(tmp_path)) == []
    assert "exceeds 500 MB limit" in capsys.readouterr().out


def test_main_reports_when_no_mega_files_are_found(tmp_path, monkeypatch, capsys):
    source = tmp_path / "single.txt"
    source.write_text("Claude Code v1.0\nJust one short session\n", encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["split_mega_files.py", "--source", str(tmp_path)])
    smf.main()

    assert "No mega-files found" in capsys.readouterr().out


def test_main_dry_run_scans_directory_without_renaming_original(tmp_path, monkeypatch, capsys):
    source = tmp_path / "mega.txt"
    _write_mega_file(source, sessions=2)

    monkeypatch.setattr(
        sys,
        "argv",
        ["split_mega_files.py", "--source", str(tmp_path), "--dry-run", "--min-sessions", "2"],
    )
    smf.main()

    output = capsys.readouterr().out
    assert "DRY RUN" in output
    assert source.exists()
    assert not source.with_suffix(".mega_backup").exists()


def test_main_splits_single_file_and_renames_original(tmp_path, monkeypatch, capsys):
    source = tmp_path / "mega.txt"
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    _write_mega_file(source, sessions=2)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "split_mega_files.py",
            "--file",
            str(source),
            "--source",
            str(tmp_path),
            "--output-dir",
            str(output_dir),
        ],
    )
    smf.main()

    output = capsys.readouterr().out
    assert "Done — created" in output
    assert source.with_suffix(".mega_backup").exists()
    assert list(output_dir.glob("*.txt"))
