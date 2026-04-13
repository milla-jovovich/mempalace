from types import SimpleNamespace

from mempalace import chroma_runtime


def test_make_settings_disables_posthog(monkeypatch):
    fake_posthog = SimpleNamespace(disabled=False, capture=object())
    monkeypatch.setattr(chroma_runtime.chroma_posthog, "posthog", fake_posthog)

    settings = chroma_runtime.make_settings()

    assert settings.anonymized_telemetry is False
    assert fake_posthog.disabled is True
    assert fake_posthog.capture is chroma_runtime._noop_capture
    assert fake_posthog.capture("ignored") is None


def test_make_client_helpers_pass_settings(monkeypatch):
    fake_posthog = SimpleNamespace(disabled=False, capture=object())
    monkeypatch.setattr(chroma_runtime.chroma_posthog, "posthog", fake_posthog)

    calls = {}

    def fake_ephemeral_client(*, settings):
        calls["ephemeral"] = settings
        return "ephemeral-client"

    def fake_persistent_client(*, path, settings):
        calls["persistent"] = (path, settings)
        return "persistent-client"

    monkeypatch.setattr(chroma_runtime.chromadb, "EphemeralClient", fake_ephemeral_client)
    monkeypatch.setattr(chroma_runtime.chromadb, "PersistentClient", fake_persistent_client)

    assert chroma_runtime.make_ephemeral_client() == "ephemeral-client"
    assert calls["ephemeral"].anonymized_telemetry is False

    assert chroma_runtime.make_persistent_client("/tmp/palace") == "persistent-client"
    path, settings = calls["persistent"]
    assert path == "/tmp/palace"
    assert settings.anonymized_telemetry is False
    assert fake_posthog.capture is chroma_runtime._noop_capture
