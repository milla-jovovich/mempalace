import json
import pytest
import httpx
from mempalace.walker.extractor.qwen_rel import (
    QwenRelExtractor, Triple, SYSTEM_PROMPT, _parse_triples,
)
from mempalace.walker.extractor.gliner_ner import Entity
from mempalace.infra.circuit_breaker import CircuitBreaker, CircuitState


def _ok_json(triples):
    return httpx.Response(200, json={
        "choices": [{"message": {"content": json.dumps(triples)}, "finish_reason": "stop"}]
    })


def _ok_text(content):
    return httpx.Response(200, json={
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}]
    })


def _build_no_preflight(handler):
    transport = httpx.MockTransport(handler)
    ex = QwenRelExtractor.__new__(QwenRelExtractor)
    ex._base_url = "http://mock"
    ex._model = "qwen35"
    ex._concurrency = 1
    ex._timeout_secs = 5.0
    ex._client = httpx.AsyncClient(transport=transport, base_url="http://mock")
    ex._cb = CircuitBreaker("qwen_rel", failure_threshold=3, recovery_timeout_secs=30.0)
    return ex


# --- parser tests ---


def test_parse_plain_json():
    result = _parse_triples('[{"subject":"A","predicate":"knows","object":"B"}]')
    assert result == [Triple("A", "knows", "B")]


def test_parse_markdown_fenced():
    content = '```json\n[{"subject":"A","predicate":"knows","object":"B"}]\n```'
    assert len(_parse_triples(content)) == 1


def test_parse_text_before_array():
    content = 'Sure! [{"subject":"A","predicate":"knows","object":"B"}]'
    assert len(_parse_triples(content)) == 1


def test_parse_empty_array():
    assert _parse_triples("[]") == []


def test_parse_invalid_returns_none():
    assert _parse_triples("not json") is None


def test_parse_skips_malformed_items():
    content = '[{"subject":"A"},{"subject":"B","predicate":"knows","object":"C"}]'
    result = _parse_triples(content)
    assert len(result) == 1
    assert result[0].subject == "B"


# --- extractor behavior ---


def test_triple_dataclass():
    t = Triple("Alice", "works_at", "DeepMind")
    assert t.subject == "Alice"


def test_system_prompt_mentions_json():
    assert "JSON" in SYSTEM_PROMPT or "json" in SYSTEM_PROMPT


async def test_empty_entities_returns_empty():
    calls = []

    def handler(request):
        calls.append(request)
        return _ok_json([])

    ex = _build_no_preflight(handler)
    assert await ex.extract("text", entities=[]) == []
    assert len(calls) == 0


async def test_empty_text_returns_empty():
    calls = []

    def handler(request):
        calls.append(request)
        return _ok_json([])

    ex = _build_no_preflight(handler)
    assert await ex.extract("   ", [Entity("A", "person", 0.9)]) == []
    assert len(calls) == 0


async def test_valid_json_parsed():
    def handler(request):
        return _ok_json([{"subject": "Alice", "predicate": "works_at", "object": "DeepMind"}])

    ex = _build_no_preflight(handler)
    result = await ex.extract("Alice at DeepMind", [
        Entity("Alice", "person", 0.9), Entity("DeepMind", "organization", 0.9)
    ])
    assert len(result) == 1
    assert result[0].subject == "Alice"


async def test_parse_failure_retries_once():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return _ok_text("not json")

    ex = _build_no_preflight(handler)
    assert await ex.extract("text", [Entity("A", "person", 0.9)]) == []
    assert calls["n"] == 2


async def test_parse_failure_does_not_open_circuit():
    def handler(request):
        return _ok_text("not json")

    ex = _build_no_preflight(handler)
    for _ in range(5):
        await ex.extract("text", [Entity("A", "person", 0.9)])
    assert ex._cb.state == CircuitState.CLOSED


async def test_http_500_opens_circuit():
    def handler(request):
        return httpx.Response(500, json={"error": "boom"})

    ex = _build_no_preflight(handler)
    for _ in range(3):
        assert await ex.extract("t", [Entity("A", "person", 0.9)]) == []
    assert ex._cb.state == CircuitState.OPEN


async def test_timeout_returns_empty():
    def handler(request):
        raise httpx.TimeoutException("slow")

    ex = _build_no_preflight(handler)
    assert await ex.extract("t", [Entity("A", "person", 0.9)]) == []


def test_preflight_raises_on_unreachable():
    with pytest.raises(RuntimeError, match="unreachable"):
        QwenRelExtractor(base_url="http://127.0.0.1:1")


async def test_preflight_passes_with_mock(monkeypatch):
    called = {"n": 0}

    class FakeSync:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def get(self, path):
            called["n"] += 1
            assert path == "/v1/models"
            class R:
                status_code = 200
                def raise_for_status(self): pass
            return R()

    monkeypatch.setattr("httpx.Client", FakeSync)
    ex = QwenRelExtractor(base_url="http://mock:1")
    assert called["n"] == 1
    await ex.aclose()
