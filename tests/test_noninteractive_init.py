import builtins

from mempalace.entity_detector import confirm_entities
from mempalace.room_detector_local import get_user_approval


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
