import argparse
import builtins
from pathlib import Path

from mempalace.cli import cmd_init
from mempalace.entity_detector import confirm_entities
from mempalace.prompts import prompt_text
from mempalace.room_detector_local import get_user_approval


def test_prompt_text_returns_default_on_eof(monkeypatch):
    def raise_eof(_prompt):
        raise EOFError

    monkeypatch.setattr(builtins, "input", raise_eof)
    assert prompt_text("prompt", default="fallback") == "fallback"


def test_room_approval_defaults_to_accept_on_eof(monkeypatch):
    rooms = [{"name": "src", "description": "Files from src/", "keywords": ["src"]}]

    def raise_eof(_prompt):
        raise EOFError

    monkeypatch.setattr(builtins, "input", raise_eof)
    assert get_user_approval(rooms) == rooms


def test_entity_confirmation_defaults_to_accept_on_eof(monkeypatch):
    detected = {
        "people": [{"name": "Alice", "confidence": 1.0, "source": "test", "signals": []}],
        "projects": [{"name": "MemPalace", "confidence": 1.0, "source": "test", "signals": []}],
        "uncertain": [],
    }

    def raise_eof(_prompt):
        raise EOFError

    monkeypatch.setattr(builtins, "input", raise_eof)
    confirmed = confirm_entities(detected)
    assert confirmed == {"people": ["Alice"], "projects": ["MemPalace"]}


def test_cmd_init_runs_onboarding_in_interactive_auto_mode(monkeypatch, tmp_path):
    called = []
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    monkeypatch.setattr("mempalace.cli.MempalaceConfig.init", lambda self: None)
    monkeypatch.setattr("mempalace.prompts.stdin_is_interactive", lambda: True)
    monkeypatch.setattr("mempalace.onboarding.run_onboarding", lambda directory: called.append(directory))
    monkeypatch.setattr("mempalace.entity_detector.scan_for_detection", lambda directory: [])
    monkeypatch.setattr("mempalace.room_detector_local.detect_rooms_local", lambda project_dir: None)

    args = argparse.Namespace(dir=str(project_dir), yes=False, onboarding="auto")
    cmd_init(args)

    assert called == [str(project_dir)]


def test_cmd_init_skips_onboarding_when_disabled(monkeypatch, tmp_path):
    called = []
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    monkeypatch.setattr("mempalace.cli.MempalaceConfig.init", lambda self: None)
    monkeypatch.setattr("mempalace.onboarding.run_onboarding", lambda directory: called.append(directory))
    monkeypatch.setattr("mempalace.entity_detector.scan_for_detection", lambda directory: [])
    monkeypatch.setattr("mempalace.room_detector_local.detect_rooms_local", lambda project_dir: None)

    args = argparse.Namespace(dir=str(project_dir), yes=True, onboarding=False)
    cmd_init(args)

    assert called == []
