"""Tests for mempalace.cli — CLI argument parsing and command dispatch."""

import sys

import pytest

from mempalace.cli import main


class TestMainNoArgs:
    def test_no_command_shows_help(self, capsys):
        sys.argv = ["mempalace"]
        main()
        out = capsys.readouterr().out
        assert "MemPalace" in out or "usage" in out.lower()


class TestMineCommand:
    def test_mine_projects_dry_run(self, sample_project, palace_path, capsys):
        sys.argv = [
            "mempalace",
            "--palace", palace_path,
            "mine", str(sample_project),
            "--dry-run",
        ]
        main()
        out = capsys.readouterr().out
        assert "DRY RUN" in out

    def test_mine_convos_dry_run(self, sample_convos, palace_path, capsys):
        sys.argv = [
            "mempalace",
            "--palace", palace_path,
            "mine", str(sample_convos),
            "--mode", "convos",
            "--dry-run",
        ]
        main()
        out = capsys.readouterr().out
        assert "DRY RUN" in out

    def test_mine_with_wing(self, sample_project, palace_path, capsys):
        sys.argv = [
            "mempalace",
            "--palace", palace_path,
            "mine", str(sample_project),
            "--wing", "custom",
            "--dry-run",
        ]
        main()
        out = capsys.readouterr().out
        assert "custom" in out


class TestSearchCommand:
    @pytest.mark.integration
    def test_search(self, palace_with_data, capsys):
        sys.argv = [
            "mempalace",
            "--palace", palace_with_data,
            "search", "GraphQL architecture",
        ]
        main()
        out = capsys.readouterr().out
        assert "Results for:" in out

    @pytest.mark.integration
    def test_search_with_filters(self, palace_with_data, capsys):
        sys.argv = [
            "mempalace",
            "--palace", palace_with_data,
            "search", "anything",
            "--wing", "personal",
            "--results", "2",
        ]
        main()
        out = capsys.readouterr().out
        assert "personal" in out.lower()


class TestStatusCommand:
    @pytest.mark.integration
    def test_status(self, palace_with_data, capsys):
        sys.argv = [
            "mempalace",
            "--palace", palace_with_data,
            "status",
        ]
        main()
        out = capsys.readouterr().out
        assert "drawers" in out.lower()

    def test_status_no_palace(self, tmp_path, capsys):
        sys.argv = [
            "mempalace",
            "--palace", str(tmp_path / "nope"),
            "status",
        ]
        main()
        out = capsys.readouterr().out
        assert "No palace" in out


class TestWakeUpCommand:
    @pytest.mark.integration
    def test_wakeup(self, palace_with_data, capsys):
        sys.argv = [
            "mempalace",
            "--palace", palace_with_data,
            "wake-up",
        ]
        main()
        out = capsys.readouterr().out
        assert "Wake-up" in out or "L0" in out or "L1" in out
