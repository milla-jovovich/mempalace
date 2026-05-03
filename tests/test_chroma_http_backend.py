"""Unit tests for ``mempalace.backends.chroma_http.HttpChromaBackend``.

These tests mock ``chromadb.HttpClient`` so they run anywhere — no live
chromadb server, no docker. Round-trip tests against a real chromadb HTTP
server live in ``tests/test_chroma_http_integration.py`` and are tagged
``@pytest.mark.chroma_http``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mempalace.backends.base import HealthStatus, PalaceRef
from mempalace.backends.chroma_http import (
    HttpChromaBackend,
    _detect_env_configured,
    _split_url,
)


@pytest.fixture(autouse=True)
def clear_chroma_env(monkeypatch):
    """Strip MEMPALACE_CHROMA_* env vars so each test starts clean."""
    for k in list(__import__("os").environ):
        if k.startswith("MEMPALACE_CHROMA_"):
            monkeypatch.delenv(k, raising=False)


# ── env-resolver helpers ─────────────────────────────────────────────────


def test_split_url_http():
    assert _split_url("http://chroma.svc:8001") == ("chroma.svc", 8001, False)


def test_split_url_https_default_port():
    assert _split_url("https://chroma.example.com") == ("chroma.example.com", 443, True)


def test_split_url_http_default_port():
    assert _split_url("http://chroma.example.com") == ("chroma.example.com", 8000, False)


def test_split_url_invalid_raises():
    with pytest.raises(ValueError):
        _split_url("not-a-url")


def test_detect_env_returns_false_without_env():
    assert _detect_env_configured() is False


def test_detect_env_returns_true_when_url_set(monkeypatch):
    monkeypatch.setenv("MEMPALACE_CHROMA_URL", "http://chroma:8000")
    assert _detect_env_configured() is True


def test_detect_env_returns_true_when_host_set(monkeypatch):
    monkeypatch.setenv("MEMPALACE_CHROMA_HOST", "chroma.svc")
    assert _detect_env_configured() is True


# ── Constructor + connection resolution ──────────────────────────────────


def test_constructor_args_win_over_env(monkeypatch):
    monkeypatch.setenv("MEMPALACE_CHROMA_HOST", "env-host")
    monkeypatch.setenv("MEMPALACE_CHROMA_PORT", "9999")
    b = HttpChromaBackend(host="ctor-host", port=8000)
    assert b.host == "ctor-host"
    assert b.port == 8000


def test_constructor_reads_full_env(monkeypatch):
    monkeypatch.setenv("MEMPALACE_CHROMA_URL", "https://chroma.svc:8443")
    monkeypatch.setenv("MEMPALACE_CHROMA_AUTH_TOKEN", "secret")
    monkeypatch.setenv("MEMPALACE_CHROMA_TENANT", "tenant1")
    monkeypatch.setenv("MEMPALACE_CHROMA_DATABASE", "memdb")
    b = HttpChromaBackend()
    assert b.url == "https://chroma.svc:8443"
    assert b.token == "secret"
    assert b.tenant == "tenant1"
    assert b.database == "memdb"


def test_resolved_split_url_overrides_host_port():
    b = HttpChromaBackend(url="https://chroma.svc:9000", host="ignored", port=1)
    assert b._split_resolved() == ("chroma.svc", 9000, True)


def test_resolved_defaults_to_localhost_8000():
    b = HttpChromaBackend()
    assert b._split_resolved() == ("localhost", 8000, False)


# ── Client construction (chromadb.HttpClient mocked) ─────────────────────


@patch("mempalace.backends.chroma_http.chromadb.HttpClient")
def test_get_client_passes_host_port_ssl(http_client_cls):
    b = HttpChromaBackend(host="chroma.svc", port=8001, ssl=True)
    b._get_client()
    http_client_cls.assert_called_once()
    kwargs = http_client_cls.call_args.kwargs
    assert kwargs["host"] == "chroma.svc"
    assert kwargs["port"] == 8001
    assert kwargs["ssl"] is True


@patch("mempalace.backends.chroma_http.chromadb.HttpClient")
def test_get_client_passes_token_as_authorization_header(http_client_cls):
    b = HttpChromaBackend(host="chroma.svc", port=8000, token="mytoken")
    b._get_client()
    kwargs = http_client_cls.call_args.kwargs
    assert kwargs["headers"] == {"Authorization": "Bearer mytoken"}


@patch("mempalace.backends.chroma_http.chromadb.HttpClient")
def test_get_client_uses_custom_auth_header(http_client_cls):
    b = HttpChromaBackend(
        host="chroma.svc", port=8000, token="mytoken", auth_header="X-Api-Key"
    )
    b._get_client()
    kwargs = http_client_cls.call_args.kwargs
    assert kwargs["headers"] == {"X-Api-Key": "Bearer mytoken"}


@patch("mempalace.backends.chroma_http.chromadb.HttpClient")
def test_get_client_passes_tenant_and_database(http_client_cls):
    b = HttpChromaBackend(
        host="chroma.svc", port=8000, tenant="t1", database="db1"
    )
    b._get_client()
    kwargs = http_client_cls.call_args.kwargs
    assert kwargs["tenant"] == "t1"
    assert kwargs["database"] == "db1"


@patch("mempalace.backends.chroma_http.chromadb.HttpClient")
def test_get_client_caches(http_client_cls):
    b = HttpChromaBackend(host="chroma.svc")
    b._get_client()
    b._get_client()
    assert http_client_cls.call_count == 1


# ── Collection name qualification ────────────────────────────────────────


def test_qualify_uses_namespace():
    ref = PalaceRef(id="/some/path", namespace="my-palace")
    assert HttpChromaBackend._qualify(ref, "drawers") == "my-palace__drawers"


def test_qualify_falls_back_to_id_when_no_namespace():
    ref = PalaceRef(id="abc123")
    assert HttpChromaBackend._qualify(ref, "drawers") == "abc123__drawers"


def test_qualify_sanitizes_unsafe_chars():
    ref = PalaceRef(id="abc", namespace="/path/to/palace")
    out = HttpChromaBackend._qualify(ref, "drawers")
    # Slashes converted to hyphens; leading non-alnum prefixed with 'p'.
    assert "/" not in out
    assert out.endswith("__drawers")


def test_qualify_default_when_namespace_blank():
    ref = PalaceRef(id="", namespace="")
    out = HttpChromaBackend._qualify(ref, "drawers")
    assert out == "default__drawers"


# ── Health probe ─────────────────────────────────────────────────────────


@patch("mempalace.backends.chroma_http.chromadb.HttpClient")
def test_health_returns_healthy_on_heartbeat(http_client_cls):
    fake = MagicMock()
    fake.heartbeat.return_value = 12345
    http_client_cls.return_value = fake

    b = HttpChromaBackend(host="chroma.svc")
    status = b.health()
    assert status.ok is True
    assert "chroma.svc" in status.detail


@patch("mempalace.backends.chroma_http.chromadb.HttpClient")
def test_health_returns_unhealthy_on_failure(http_client_cls):
    fake = MagicMock()
    fake.heartbeat.side_effect = ConnectionError("connection refused")
    http_client_cls.return_value = fake

    b = HttpChromaBackend(host="chroma.svc")
    status = b.health()
    assert status.ok is False
    assert "connection refused" in status.detail


def test_health_returns_unhealthy_after_close():
    b = HttpChromaBackend(host="chroma.svc")
    b.close()
    status = b.health()
    assert status.ok is False
    assert "closed" in status.detail.lower()


# ── detect() class method ────────────────────────────────────────────────


def test_detect_returns_false_without_env(tmp_path):
    assert HttpChromaBackend.detect(str(tmp_path)) is False


def test_detect_returns_true_with_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMPALACE_CHROMA_URL", "http://chroma:8000")
    assert HttpChromaBackend.detect(str(tmp_path)) is True


# ── Registry integration ─────────────────────────────────────────────────


def test_registered_under_chroma_http_name():
    from mempalace.backends.registry import available_backends, get_backend_class

    assert "chroma_http" in available_backends()
    assert get_backend_class("chroma_http") is HttpChromaBackend


# ── make_client static convenience ───────────────────────────────────────


@patch("mempalace.backends.chroma_http.chromadb.HttpClient")
def test_make_client_static_uses_env(http_client_cls, monkeypatch):
    monkeypatch.setenv("MEMPALACE_CHROMA_HOST", "static-host")
    monkeypatch.setenv("MEMPALACE_CHROMA_PORT", "7777")
    HttpChromaBackend.make_client()
    kwargs = http_client_cls.call_args.kwargs
    assert kwargs["host"] == "static-host"
    assert kwargs["port"] == 7777


def test_isinstance_health_status_type():
    b = HttpChromaBackend(host="chroma.svc")
    b.close()
    assert isinstance(b.health(), HealthStatus)
