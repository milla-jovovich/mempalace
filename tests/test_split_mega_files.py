"""Tests for mempalace.split_mega_files — mega-file splitting."""

import pytest

from mempalace.split_mega_files import (
    extract_people,
    extract_subject,
    extract_timestamp,
    find_session_boundaries,
    is_true_session_start,
    split_file,
)


def _make_session(version="1.0.0", time_str=None, prompt="> Tell me about testing"):
    """Helper: build a minimal session block."""
    lines = [f"Claude Code v{version}\n"]
    if time_str:
        lines.append(f"⏺ {time_str}\n")
    lines.append("\n")
    lines.append(f"{prompt}\n")
    lines.extend(["Response line.\n"] * 15)
    return lines


class TestIsTrueSessionStart:
    def test_true_start(self):
        lines = ["Claude Code v1.0.0", "⏺ 2:30 PM Monday, March 30, 2026", "", "> Hi"]
        assert is_true_session_start(lines, 0) is True

    def test_context_restore(self):
        lines = [
            "Claude Code v1.0.0",
            "Ctrl+E to show 5 previous messages",
            "",
            "> Hi",
        ]
        assert is_true_session_start(lines, 0) is False


class TestFindSessionBoundaries:
    def test_two_sessions(self):
        session1 = _make_session()
        session2 = _make_session(version="1.0.1")
        lines = session1 + session2
        boundaries = find_session_boundaries(lines)
        assert len(boundaries) == 2

    def test_no_sessions(self):
        lines = ["Just some text\n", "No Claude Code here\n"]
        assert find_session_boundaries(lines) == []

    def test_context_restore_not_counted(self):
        lines = [
            "Claude Code v1.0.0\n",
            "⏺ 2:30 PM Monday, March 30, 2026\n",
            "> Real session\n",
        ] + ["content\n"] * 15 + [
            "Claude Code v1.0.0\n",
            "Ctrl+E to show 3 previous messages\n",
            "> context restore\n",
        ]
        boundaries = find_session_boundaries(lines)
        assert len(boundaries) == 1


class TestExtractTimestamp:
    def test_valid_timestamp(self):
        lines = ["some header", "⏺ 2:30 PM Monday, March 30, 2026", "content"]
        human, iso = extract_timestamp(lines)
        assert human is not None
        assert "2026" in human
        assert iso == "2026-03-30"

    def test_no_timestamp(self):
        lines = ["no timestamp here", "just text"]
        human, iso = extract_timestamp(lines)
        assert human is None
        assert iso is None


class TestExtractPeople:
    def test_detects_known_names(self):
        lines = ["Working with Alice and Ben on the project", "> Alice: Can you review this?"]
        people = extract_people(lines)
        assert "Alice" in people
        assert "Ben" in people

    def test_no_people(self):
        lines = ["Just some technical content about databases"]
        assert extract_people(lines) == []


class TestExtractSubject:
    def test_extracts_first_prompt(self):
        lines = [
            "some header",
            "> Can you help me fix the authentication bug in our API?",
            "Sure, let me look at that.",
        ]
        subject = extract_subject(lines)
        assert len(subject) > 5
        assert "authentication" in subject.lower() or "fix" in subject.lower()

    def test_skips_shell_commands(self):
        lines = [
            "> cd /home/user",
            "> python test.py",
            "> Can you explain how memory works?",
        ]
        subject = extract_subject(lines)
        assert "memory" in subject.lower() or "explain" in subject.lower()

    def test_fallback_session(self):
        lines = ["no prompts here", "just content"]
        assert extract_subject(lines) == "session"


class TestSplitFile:
    def test_splits_mega_file(self, tmp_path):
        session1 = _make_session(time_str="2:30 PM Monday, March 30, 2026")
        session2 = _make_session(version="1.0.1", time_str="4:00 PM Monday, March 30, 2026")
        mega = tmp_path / "mega.txt"
        mega.write_text("".join(session1 + session2))

        output_dir = tmp_path / "output"
        output_dir.mkdir()
        written = split_file(str(mega), str(output_dir))
        assert len(written) == 2

    def test_single_session_not_split(self, tmp_path):
        session = _make_session()
        f = tmp_path / "single.txt"
        f.write_text("".join(session))
        written = split_file(str(f), str(tmp_path / "out"))
        assert written == []

    def test_dry_run(self, tmp_path, capsys):
        session1 = _make_session()
        session2 = _make_session(version="1.0.1")
        mega = tmp_path / "mega.txt"
        mega.write_text("".join(session1 + session2))

        output_dir = tmp_path / "out"
        output_dir.mkdir()
        written = split_file(str(mega), str(output_dir), dry_run=True)
        assert len(written) == 2
        actual_files = list(output_dir.iterdir())
        assert len(actual_files) == 0
