"""Tests for mempalace.llm_client.

HTTP is mocked throughout — these tests do not require a running Ollama
or network access. Live-provider smoke tests live outside the unit-test
suite.
"""

import json
from unittest.mock import patch, MagicMock

import pytest

from mempalace.llm_client import (
    AnthropicProvider,
    LLMError,
    OllamaProvider,
    OpenAICompatProvider,
    _http_post_json,
    get_provider,
)


# ── factory ─────────────────────────────────────────────────────────────


def test_get_provider_ollama():
    p = get_provider("ollama", "gemma4:e4b")
    assert isinstance(p, OllamaProvider)
    assert p.model == "gemma4:e4b"
    assert p.endpoint == OllamaProvider.DEFAULT_ENDPOINT


def test_get_provider_openai_compat():
    p = get_provider("openai-compat", "foo", endpoint="http://localhost:1234")
    assert isinstance(p, OpenAICompatProvider)


def test_get_provider_anthropic():
    p = get_provider("anthropic", "claude-haiku", api_key="sk-xxx")
    assert isinstance(p, AnthropicProvider)
    assert p.api_key == "sk-xxx"


def test_get_provider_unknown_raises():
    with pytest.raises(LLMError, match="Unknown provider"):
        get_provider("nonsense", "x")


# ── _http_post_json ─────────────────────────────────────────────────────


def test_http_post_json_success():
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"ok": true}'
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False
    with patch("mempalace.llm_client.urlopen", return_value=mock_resp):
        result = _http_post_json("http://x/y", {"a": 1}, {}, timeout=5)
    assert result == {"ok": True}


def test_http_post_json_http_error_wraps_as_llm_error():
    from urllib.error import HTTPError
    import io

    err = HTTPError("http://x", 404, "Not Found", {}, io.BytesIO(b"model missing"))
    with patch("mempalace.llm_client.urlopen", side_effect=err):
        with pytest.raises(LLMError, match="HTTP 404"):
            _http_post_json("http://x", {}, {}, timeout=5)


def test_http_post_json_url_error_wraps_as_llm_error():
    from urllib.error import URLError

    with patch("mempalace.llm_client.urlopen", side_effect=URLError("conn refused")):
        with pytest.raises(LLMError, match="Cannot reach"):
            _http_post_json("http://x", {}, {}, timeout=5)


def test_http_post_json_malformed_response():
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"not json"
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False
    with patch("mempalace.llm_client.urlopen", return_value=mock_resp):
        with pytest.raises(LLMError, match="Malformed"):
            _http_post_json("http://x", {}, {}, timeout=5)


# ── OllamaProvider ──────────────────────────────────────────────────────


def _mock_ollama_chat_response(content: str):
    mock = MagicMock()
    mock.read.return_value = json.dumps({"message": {"content": content}}).encode()
    mock.__enter__.return_value = mock
    mock.__exit__.return_value = False
    return mock


def test_ollama_check_available_finds_model():
    tags = {"models": [{"name": "gemma4:e4b"}, {"name": "other:latest"}]}
    mock = MagicMock()
    mock.read.return_value = json.dumps(tags).encode()
    mock.__enter__.return_value = mock
    mock.__exit__.return_value = False
    with patch("mempalace.llm_client.urlopen", return_value=mock):
        p = OllamaProvider(model="gemma4:e4b")
        ok, msg = p.check_available()
    assert ok
    assert msg == "ok"


def test_ollama_check_available_accepts_latest_suffix():
    tags = {"models": [{"name": "mymodel:latest"}]}
    mock = MagicMock()
    mock.read.return_value = json.dumps(tags).encode()
    mock.__enter__.return_value = mock
    mock.__exit__.return_value = False
    with patch("mempalace.llm_client.urlopen", return_value=mock):
        p = OllamaProvider(model="mymodel")
        ok, _ = p.check_available()
    assert ok


def test_ollama_check_available_missing_model():
    tags = {"models": [{"name": "other:latest"}]}
    mock = MagicMock()
    mock.read.return_value = json.dumps(tags).encode()
    mock.__enter__.return_value = mock
    mock.__exit__.return_value = False
    with patch("mempalace.llm_client.urlopen", return_value=mock):
        p = OllamaProvider(model="absent")
        ok, msg = p.check_available()
    assert not ok
    assert "ollama pull absent" in msg


def test_ollama_check_available_unreachable():
    from urllib.error import URLError

    with patch("mempalace.llm_client.urlopen", side_effect=URLError("refused")):
        p = OllamaProvider(model="gemma4:e4b")
        ok, msg = p.check_available()
    assert not ok
    assert "Cannot reach Ollama" in msg


def test_ollama_classify_sends_json_format():
    captured = {}

    def fake_urlopen(req, *, timeout):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())
        return _mock_ollama_chat_response('{"classifications": []}')

    with patch("mempalace.llm_client.urlopen", side_effect=fake_urlopen):
        p = OllamaProvider(model="gemma4:e4b")
        resp = p.classify("sys", "user", json_mode=True)

    assert captured["body"]["format"] == "json"
    assert captured["body"]["model"] == "gemma4:e4b"
    assert captured["url"].endswith("/api/chat")
    assert resp.provider == "ollama"
    assert resp.text == '{"classifications": []}'


def test_ollama_classify_empty_content_raises():
    with patch("mempalace.llm_client.urlopen", return_value=_mock_ollama_chat_response("")):
        p = OllamaProvider(model="x")
        with pytest.raises(LLMError, match="Empty response"):
            p.classify("s", "u")


# ── OpenAICompatProvider ────────────────────────────────────────────────


def _mock_openai_response(content: str):
    mock = MagicMock()
    payload = {"choices": [{"message": {"content": content}}]}
    mock.read.return_value = json.dumps(payload).encode()
    mock.__enter__.return_value = mock
    mock.__exit__.return_value = False
    return mock


def test_openai_compat_resolves_url_with_v1_suffix():
    captured = {}

    def fake_urlopen(req, *, timeout):
        captured["url"] = req.full_url
        return _mock_openai_response('{"ok": true}')

    with patch("mempalace.llm_client.urlopen", side_effect=fake_urlopen):
        p = OpenAICompatProvider(model="x", endpoint="http://h:1234")
        p.classify("s", "u")
    assert captured["url"] == "http://h:1234/v1/chat/completions"


def test_openai_compat_resolves_url_with_existing_v1():
    captured = {}

    def fake_urlopen(req, *, timeout):
        captured["url"] = req.full_url
        return _mock_openai_response('{"ok": true}')

    with patch("mempalace.llm_client.urlopen", side_effect=fake_urlopen):
        p = OpenAICompatProvider(model="x", endpoint="http://h:1234/v1")
        p.classify("s", "u")
    assert captured["url"] == "http://h:1234/v1/chat/completions"


def test_openai_compat_requires_endpoint():
    p = OpenAICompatProvider(model="x")
    with pytest.raises(LLMError, match="requires --llm-endpoint"):
        p.classify("s", "u")


def test_openai_compat_sends_authorization_when_key_present():
    captured = {}

    def fake_urlopen(req, *, timeout):
        captured["auth"] = req.get_header("Authorization")
        return _mock_openai_response('{"ok": true}')

    with patch("mempalace.llm_client.urlopen", side_effect=fake_urlopen):
        p = OpenAICompatProvider(model="x", endpoint="http://h", api_key="sk-aaa")
        p.classify("s", "u")
    assert captured["auth"] == "Bearer sk-aaa"


def test_openai_compat_uses_env_var_fallback(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    p = OpenAICompatProvider(model="x", endpoint="http://h")
    assert p.api_key == "sk-from-env"


def test_openai_compat_sends_response_format_json():
    captured = {}

    def fake_urlopen(req, *, timeout):
        captured["body"] = json.loads(req.data.decode())
        return _mock_openai_response('{"ok": true}')

    with patch("mempalace.llm_client.urlopen", side_effect=fake_urlopen):
        p = OpenAICompatProvider(model="x", endpoint="http://h")
        p.classify("s", "u", json_mode=True)
    assert captured["body"]["response_format"] == {"type": "json_object"}


def test_openai_compat_unexpected_shape_raises():
    mock = MagicMock()
    mock.read.return_value = b'{"nothing": "here"}'
    mock.__enter__.return_value = mock
    mock.__exit__.return_value = False
    with patch("mempalace.llm_client.urlopen", return_value=mock):
        p = OpenAICompatProvider(model="x", endpoint="http://h")
        with pytest.raises(LLMError, match="Unexpected response shape"):
            p.classify("s", "u")


# ── AnthropicProvider ───────────────────────────────────────────────────


def _mock_anthropic_response(text: str):
    mock = MagicMock()
    payload = {"content": [{"type": "text", "text": text}]}
    mock.read.return_value = json.dumps(payload).encode()
    mock.__enter__.return_value = mock
    mock.__exit__.return_value = False
    return mock


def test_anthropic_requires_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    p = AnthropicProvider(model="claude-haiku")
    ok, msg = p.check_available()
    assert not ok
    assert "ANTHROPIC_API_KEY" in msg


def test_anthropic_reads_env_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    p = AnthropicProvider(model="claude-haiku")
    assert p.api_key == "sk-ant-env"
    ok, _ = p.check_available()
    assert ok


def test_anthropic_classify_sends_version_and_key():
    captured = {}

    def fake_urlopen(req, *, timeout):
        captured["api_key"] = req.get_header("X-api-key")
        captured["version"] = req.get_header("Anthropic-version")
        return _mock_anthropic_response('{"ok": true}')

    with patch("mempalace.llm_client.urlopen", side_effect=fake_urlopen):
        p = AnthropicProvider(model="claude-haiku", api_key="sk-ant-abc")
        resp = p.classify("s", "u")
    assert captured["api_key"] == "sk-ant-abc"
    assert captured["version"] == AnthropicProvider.API_VERSION
    assert resp.text == '{"ok": true}'


def test_anthropic_joins_multiple_text_blocks():
    mock = MagicMock()
    payload = {
        "content": [
            {"type": "text", "text": "part one. "},
            {"type": "text", "text": "part two."},
        ]
    }
    mock.read.return_value = json.dumps(payload).encode()
    mock.__enter__.return_value = mock
    mock.__exit__.return_value = False
    with patch("mempalace.llm_client.urlopen", return_value=mock):
        p = AnthropicProvider(model="claude-haiku", api_key="sk-ant")
        resp = p.classify("s", "u")
    assert resp.text == "part one. part two."


def test_anthropic_no_key_raises_on_classify(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    p = AnthropicProvider(model="claude-haiku")
    with pytest.raises(LLMError, match="requires ANTHROPIC_API_KEY"):
        p.classify("s", "u")
