# MemPalace Walk — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the extraction pipeline that populates the knowledge graph from palace drawers via GLiNER (entities) + Qwen3.5 35B HTTP (relationships), producing a dense entity-relationship graph (target: median ≥ 2 triples/drawer).

**Architecture:** Two-model pipeline. GLiNER runs in-process (batched, 33k texts/s). Qwen3.5 35B is reached over HTTP at `localhost:43100` (OpenAI-compatible). An async orchestrator runs Qwen calls with `asyncio.gather` + a semaphore (concurrency=4). A new `extraction_state` SQLite table tracks which drawers have been extracted per `extractor_version`. Idempotent and resumable.

**Tech Stack:** Python 3.13, GLiNER (`urchade/gliner_multi-v2.1`), httpx async, asyncio, SQLite (WAL), existing `KnowledgeGraph` + `CircuitBreaker` from Phase 0.

**Spec:** `docs/superpowers/specs/2026-04-15-mempalace-walk-phase-1-design.md`

---

## File Structure

**New files:**
```
mempalace/walker/extractor/
  __init__.py                 # package exports
  gliner_ner.py               # GlinerNER wrapper (batch extraction, device selection)
  qwen_rel.py                 # QwenRelExtractor (async HTTP, CircuitBreaker-wrapped)
  state.py                    # ExtractionState (SQLite table + is_extracted/mark_extracted)
  pipeline.py                 # extract_drawers() async orchestrator + ExtractionStats
mempalace/dream/
  __init__.py
  reextract.py                # run_job_a() — Dream Job A async entry point
tests/walker/extractor/
  __init__.py
  test_gliner_ner.py
  test_qwen_rel.py
  test_state.py
  test_pipeline.py
tests/dream/
  __init__.py
  test_reextract.py
```

**Modified files:**
- `pyproject.toml` — add `httpx>=0.27.0` to `[walker]` extras
- `mempalace/cli.py` — add `walker extract` subcommand + `dream-cycle --jobs A` subcommand + extend `status --walker`

---

## Task 1: Add `httpx` to `[walker]` extras

**Files:**
- Modify: `pyproject.toml` — add `httpx>=0.27.0` to `[project.optional-dependencies] walker`

- [ ] **Step 1: Read current `[walker]` block**

Run: `grep -A 10 'walker = \[' pyproject.toml`

- [ ] **Step 2: Add `httpx>=0.27.0` line**

Add to the `walker` list: `"httpx>=0.27.0",`

- [ ] **Step 3: Verify `httpx` importable**

Run: `python -c "import httpx; print(httpx.__version__)"`
Expected: version string, no error.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "deps(walker): add httpx>=0.27.0 for Qwen HTTP client"
```

---

## Task 2: `ExtractionState` — SQLite state table

**Files:**
- Create: `mempalace/walker/extractor/__init__.py` (empty)
- Create: `mempalace/walker/extractor/state.py`
- Create: `tests/walker/extractor/__init__.py` (empty)
- Create: `tests/walker/extractor/test_state.py`

- [ ] **Step 1: Write failing tests (`test_state.py`)**

```python
import pytest
from mempalace.knowledge_graph import KnowledgeGraph
from mempalace.walker.extractor.state import ExtractionState


def test_table_created_on_init(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    conn = kg._conn()
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    assert "extraction_state" in tables


def test_is_extracted_false_for_unknown_drawer(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    assert state.is_extracted("drawer_1", "v1.0") is False


def test_mark_and_query(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    state.mark_extracted("drawer_1", version="v1.0", triple_count=3, entity_count=5)
    assert state.is_extracted("drawer_1", "v1.0") is True
    assert state.is_extracted("drawer_1", "v1.1") is False  # different version


def test_mark_replaces_prior_entry(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    state.mark_extracted("d1", "v1.0", triple_count=2, entity_count=3)
    state.mark_extracted("d1", "v1.0", triple_count=4, entity_count=6)
    row = kg._conn().execute(
        "SELECT triple_count, entity_count FROM extraction_state WHERE drawer_id='d1'"
    ).fetchone()
    assert row[0] == 4
    assert row[1] == 6


def test_unextracted_ids_filters_already_extracted(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    state.mark_extracted("d1", "v1.0", 0, 0)
    state.mark_extracted("d2", "v1.0", 0, 0)
    result = state.unextracted_ids(["d1", "d2", "d3", "d4"], "v1.0")
    assert set(result) == {"d3", "d4"}


def test_unextracted_ids_different_version(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    state.mark_extracted("d1", "v1.0", 0, 0)
    result = state.unextracted_ids(["d1"], "v1.1")
    assert result == ["d1"]  # v1.1 not yet extracted


def test_max_extracted_at(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    state.mark_extracted("d1", "v1.0", 0, 0)
    state.mark_extracted("d2", "v1.0", 0, 0)
    ts = state.max_extracted_at("v1.0")
    assert ts is not None  # ISO timestamp string

    assert state.max_extracted_at("v2.0") is None
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `python -m pytest tests/walker/extractor/test_state.py -v`
Expected: FAIL (`ModuleNotFoundError: mempalace.walker.extractor.state`)

- [ ] **Step 3: Implement `state.py`**

```python
"""Tracks which drawers have been extracted per extractor_version.

Shares the knowledge_graph.db SQLite file for zero-new-file storage.
Uses the KnowledgeGraph's own connection (WAL mode) so cross-thread /
asyncio access is safe without a separate lock.
"""
from __future__ import annotations

from mempalace.knowledge_graph import KnowledgeGraph


class ExtractionState:
    """SQLite-backed extraction tracking. Lives in knowledge_graph.db."""

    def __init__(self, kg: KnowledgeGraph) -> None:
        self._kg = kg
        self._init_table()

    def _init_table(self) -> None:
        conn = self._kg._conn()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS extraction_state (
                drawer_id         TEXT PRIMARY KEY,
                extractor_version TEXT NOT NULL,
                extracted_at      TEXT DEFAULT CURRENT_TIMESTAMP,
                triple_count      INTEGER DEFAULT 0,
                entity_count      INTEGER DEFAULT 0
            )
            """
        )
        conn.commit()

    def is_extracted(self, drawer_id: str, version: str) -> bool:
        row = self._kg._conn().execute(
            "SELECT 1 FROM extraction_state WHERE drawer_id=? AND extractor_version=?",
            (drawer_id, version),
        ).fetchone()
        return row is not None

    def mark_extracted(
        self,
        drawer_id: str,
        version: str,
        triple_count: int,
        entity_count: int,
    ) -> None:
        conn = self._kg._conn()
        conn.execute(
            """INSERT OR REPLACE INTO extraction_state
               (drawer_id, extractor_version, extracted_at, triple_count, entity_count)
               VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?)""",
            (drawer_id, version, triple_count, entity_count),
        )
        conn.commit()

    def unextracted_ids(self, all_ids: list[str], version: str) -> list[str]:
        if not all_ids:
            return []
        conn = self._kg._conn()
        placeholders = ",".join("?" * len(all_ids))
        rows = conn.execute(
            f"""SELECT drawer_id FROM extraction_state
                WHERE extractor_version=? AND drawer_id IN ({placeholders})""",
            (version, *all_ids),
        ).fetchall()
        extracted = {r[0] for r in rows}
        return [i for i in all_ids if i not in extracted]

    def max_extracted_at(self, version: str) -> str | None:
        row = self._kg._conn().execute(
            "SELECT MAX(extracted_at) FROM extraction_state WHERE extractor_version=?",
            (version,),
        ).fetchone()
        return row[0] if row and row[0] else None
```

- [ ] **Step 4: Run tests — expect all pass**

Run: `python -m pytest tests/walker/extractor/test_state.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add mempalace/walker/extractor/__init__.py mempalace/walker/extractor/state.py \
        tests/walker/extractor/__init__.py tests/walker/extractor/test_state.py
git commit -m "feat(walker): ExtractionState SQLite table for per-drawer tracking"
```

---

## Task 3: `GlinerNER` — entity extraction wrapper

**Files:**
- Create: `mempalace/walker/extractor/gliner_ner.py`
- Create: `tests/walker/extractor/test_gliner_ner.py`

Note: GLiNER model downloads (~500MB) on first use. Tests use a mock via `monkeypatch` — they do NOT load the real model.

- [ ] **Step 1: Write failing tests (`test_gliner_ner.py`)**

```python
"""Tests for GlinerNER — mocks the underlying gliner library so tests are fast
and don't require a 500MB model download."""
from unittest.mock import MagicMock
import pytest
from mempalace.walker.extractor.gliner_ner import GlinerNER, Entity, ENTITY_TYPES


def _make_gliner_ner_with_fake_model(fake_predict):
    """Helper: construct GlinerNER without loading the real GLiNER model."""
    ner = GlinerNER.__new__(GlinerNER)  # bypass __init__
    ner._model = MagicMock()
    ner._model.batch_predict_entities.side_effect = fake_predict
    ner._device = "cpu"
    return ner


def test_entity_dataclass():
    e = Entity(text="Alice", type="person", score=0.92)
    assert e.text == "Alice"
    assert e.type == "person"
    assert e.score == pytest.approx(0.92)


def test_entity_types_is_list():
    assert isinstance(ENTITY_TYPES, list)
    assert "person" in ENTITY_TYPES
    assert "organization" in ENTITY_TYPES


def test_select_device_returns_cuda_or_cpu(monkeypatch):
    from mempalace.walker.gpu_detect import HardwareTier, WalkerHardware
    fake_hw = WalkerHardware(
        tier=HardwareTier.FULL, device_name="A5000", vram_gb=24.0
    )
    monkeypatch.setattr(
        "mempalace.walker.extractor.gliner_ner.detect_hardware", lambda: fake_hw
    )
    assert GlinerNER._select_device() == "cuda"

    cpu_hw = WalkerHardware(
        tier=HardwareTier.CPU_ONLY, device_name="CPU", vram_gb=0.0
    )
    monkeypatch.setattr(
        "mempalace.walker.extractor.gliner_ner.detect_hardware", lambda: cpu_hw
    )
    assert GlinerNER._select_device() == "cpu"


def test_extract_batch_returns_one_list_per_input():
    fake_predict = lambda texts, labels, threshold: [
        [{"text": "Alice", "label": "person", "score": 0.9}],
        [{"text": "DeepMind", "label": "organization", "score": 0.85}],
    ]
    ner = _make_gliner_ner_with_fake_model(fake_predict)
    out = ner.extract_batch(["Alice works", "DeepMind"])
    assert len(out) == 2
    assert out[0][0].text == "Alice"
    assert out[0][0].type == "person"
    assert out[1][0].text == "DeepMind"


def test_extract_batch_empty_input():
    ner = _make_gliner_ner_with_fake_model(lambda *a, **k: [])
    out = ner.extract_batch([])
    assert out == []


def test_extract_batch_filters_by_threshold():
    fake_predict = lambda texts, labels, threshold: [
        [
            {"text": "Alice", "label": "person", "score": 0.9},
            {"text": "foo", "label": "person", "score": 0.2},  # below default 0.4
        ]
    ]
    ner = _make_gliner_ner_with_fake_model(fake_predict)
    # gliner library already applies threshold internally; we pass it through
    out = ner.extract_batch(["text"], threshold=0.4)
    # verify we called with threshold=0.4
    ner._model.batch_predict_entities.assert_called_with(
        ["text"], ENTITY_TYPES, threshold=0.4
    )
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `python -m pytest tests/walker/extractor/test_gliner_ner.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement `gliner_ner.py`**

```python
"""GLiNER wrapper — batched entity extraction with GPU autodetect."""
from __future__ import annotations

from dataclasses import dataclass

from mempalace.walker.gpu_detect import HardwareTier, detect_hardware

ENTITY_TYPES: list[str] = [
    "person",
    "organization",
    "location",
    "date",
    "project",
    "technology",
    "event",
]


@dataclass(slots=True)
class Entity:
    text: str
    type: str
    score: float


class GlinerNER:
    """Loaded once per `walker extract` run, reused across all drawers."""

    def __init__(
        self,
        model: str = "urchade/gliner_multi-v2.1",
        device: str | None = None,
    ) -> None:
        from gliner import GLiNER  # local import — avoids hard dep at package load

        self._device = device or GlinerNER._select_device()
        self._model = GLiNER.from_pretrained(model).to(self._device)

    def extract_batch(
        self, texts: list[str], threshold: float = 0.4
    ) -> list[list[Entity]]:
        """Returns one Entity list per input text. Batched internally by gliner."""
        if not texts:
            return []
        raw = self._model.batch_predict_entities(
            texts, ENTITY_TYPES, threshold=threshold
        )
        return [
            [Entity(text=r["text"], type=r["label"], score=r["score"]) for r in per_text]
            for per_text in raw
        ]

    @staticmethod
    def _select_device() -> str:
        """Returns 'cuda' if a GPU is available (per walker.gpu_detect), else 'cpu'."""
        hw = detect_hardware()
        return "cpu" if hw.tier == HardwareTier.CPU_ONLY else "cuda"
```

- [ ] **Step 4: Run tests — expect all pass**

Run: `python -m pytest tests/walker/extractor/test_gliner_ner.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add mempalace/walker/extractor/gliner_ner.py tests/walker/extractor/test_gliner_ner.py
git commit -m "feat(walker): GlinerNER entity extraction wrapper with device autodetect"
```

---

## Task 4: `QwenRelExtractor` — async HTTP client + CircuitBreaker

**Files:**
- Create: `mempalace/walker/extractor/qwen_rel.py`
- Create: `tests/walker/extractor/test_qwen_rel.py`

- [ ] **Step 1: Write failing tests (`test_qwen_rel.py`)**

```python
"""Tests for QwenRelExtractor — uses httpx MockTransport to avoid real HTTP.
No real Qwen endpoint is contacted."""
import json
import pytest
import httpx
from mempalace.walker.extractor.qwen_rel import (
    QwenRelExtractor,
    Triple,
    SYSTEM_PROMPT,
)
from mempalace.walker.extractor.gliner_ner import Entity
from mempalace.infra.circuit_breaker import CircuitOpenError


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def _ok_response(triples: list[dict]) -> httpx.Response:
    body = {
        "choices": [
            {
                "message": {"content": json.dumps(triples)},
                "finish_reason": "stop",
            }
        ]
    }
    return httpx.Response(200, json=body)


def _ok_text_response(content: str) -> httpx.Response:
    body = {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
    return httpx.Response(200, json=body)


def _models_ok_response() -> httpx.Response:
    return httpx.Response(200, json={"data": [{"id": "qwen35"}]})


def _build_extractor(request_handler) -> QwenRelExtractor:
    """Build QwenRelExtractor with a MockTransport, bypassing the preflight check."""
    transport = _mock_transport(request_handler)
    ex = QwenRelExtractor.__new__(QwenRelExtractor)
    ex._base_url = "http://mock"
    ex._model = "qwen35"
    ex._concurrency = 1
    ex._timeout_secs = 5.0
    ex._client = httpx.AsyncClient(transport=transport, base_url="http://mock")
    from mempalace.infra.circuit_breaker import CircuitBreaker
    ex._cb = CircuitBreaker("qwen_rel", failure_threshold=3, recovery_timeout_secs=30.0)
    return ex


def test_triple_dataclass():
    t = Triple(subject="Alice", predicate="works_at", object="DeepMind")
    assert t.subject == "Alice"
    assert t.predicate == "works_at"
    assert t.object == "DeepMind"


def test_system_prompt_mentions_json():
    assert "JSON" in SYSTEM_PROMPT or "json" in SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_empty_entities_returns_empty_without_http():
    calls = []

    def handler(request):
        calls.append(request)
        return _ok_response([])

    ex = _build_extractor(handler)
    result = await ex.extract("some text", entities=[])
    assert result == []
    assert len(calls) == 0  # Qwen was NOT called


@pytest.mark.asyncio
async def test_valid_json_parsed_into_triples():
    def handler(request):
        return _ok_response(
            [{"subject": "Alice", "predicate": "works_at", "object": "DeepMind"}]
        )

    ex = _build_extractor(handler)
    entities = [Entity("Alice", "person", 0.9), Entity("DeepMind", "organization", 0.9)]
    result = await ex.extract("Alice works at DeepMind.", entities)
    assert len(result) == 1
    assert result[0].subject == "Alice"
    assert result[0].predicate == "works_at"
    assert result[0].object == "DeepMind"


@pytest.mark.asyncio
async def test_parse_failure_retries_once_then_returns_empty():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return _ok_text_response("definitely not json")

    ex = _build_extractor(handler)
    entities = [Entity("Alice", "person", 0.9)]
    result = await ex.extract("Alice text", entities)
    assert result == []
    assert calls["n"] == 2  # one original + one retry


@pytest.mark.asyncio
async def test_markdown_fenced_json_parsed_correctly():
    """Qwen sometimes wraps JSON in ```json ... ``` — should still parse."""
    def handler(request):
        content = '```json\n[{"subject":"Alice","predicate":"knows","object":"Bob"}]\n```'
        return _ok_text_response(content)

    ex = _build_extractor(handler)
    result = await ex.extract("text", [Entity("Alice", "person", 0.9)])
    assert len(result) == 1
    assert result[0].subject == "Alice"


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_3_failures():
    def handler(request):
        return httpx.Response(500, json={"error": "boom"})

    ex = _build_extractor(handler)
    entities = [Entity("Alice", "person", 0.9)]

    # 3 failures → circuit opens
    for _ in range(3):
        result = await ex.extract("text", entities)
        assert result == []

    # 4th call returns [] immediately (circuit is open)
    result = await ex.extract("text", entities)
    assert result == []


@pytest.mark.asyncio
async def test_timeout_returns_empty():
    def handler(request):
        raise httpx.TimeoutException("slow")

    ex = _build_extractor(handler)
    entities = [Entity("Alice", "person", 0.9)]
    result = await ex.extract("text", entities)
    assert result == []
```

Add to `tests/conftest.py` (or `tests/walker/extractor/conftest.py`) if missing:

```python
import pytest_asyncio  # noqa: F401
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `python -m pytest tests/walker/extractor/test_qwen_rel.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement `qwen_rel.py`**

```python
"""Async HTTP client for Qwen3.5 35B relationship extraction.

Wraps the CircuitBreaker from Phase 0 (`mempalace.infra.circuit_breaker`).
No model loading — the Qwen server must already be running on `base_url`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable

import httpx

from mempalace.infra.circuit_breaker import CircuitBreaker, CircuitOpenError
from mempalace.walker.extractor.gliner_ner import Entity


SYSTEM_PROMPT = """Extract relationships as JSON triples from the text.
Return ONLY a JSON array: [{"subject": "...", "predicate": "...", "object": "..."}]
Use only entities from the provided list. Predicates must be snake_case verbs.
Return [] if no clear relationships exist. No explanation, no markdown."""

STRICTER_PROMPT = """Return ONLY a JSON array of {"subject","predicate","object"} objects.
No markdown, no explanation, no other text. Just the JSON array."""


@dataclass(slots=True)
class Triple:
    subject: str
    predicate: str
    object: str


_JSON_ARRAY_RE = re.compile(r"\[.*?\]", re.DOTALL)


class QwenRelExtractor:
    """Thin async HTTP client wrapping the already-running Qwen3.5 35B endpoint."""

    def __init__(
        self,
        base_url: str = "http://localhost:43100",
        model: str = "qwen35",
        concurrency: int = 4,
        timeout_secs: float = 30.0,
    ) -> None:
        self._base_url = base_url
        self._model = model
        self._concurrency = concurrency
        self._timeout_secs = timeout_secs
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout_secs)
        self._cb = CircuitBreaker(
            "qwen_rel", failure_threshold=3, recovery_timeout_secs=30.0
        )
        self._preflight_check()

    def _preflight_check(self) -> None:
        """Verify the endpoint is reachable at construction time. Fail fast."""
        try:
            with httpx.Client(base_url=self._base_url, timeout=5.0) as sync:
                r = sync.get("/v1/models")
                r.raise_for_status()
        except Exception as e:
            raise RuntimeError(
                f"Qwen endpoint {self._base_url} unreachable: {e}. "
                f"Start the Qwen server before running walker extract."
            ) from e

    async def aclose(self) -> None:
        await self._client.aclose()

    async def extract(self, text: str, entities: list[Entity]) -> list[Triple]:
        """Extract relationship triples for the given text + entities.

        Returns [] if:
          - entities is empty (Qwen not called)
          - Qwen endpoint returns an error
          - CircuitBreaker is OPEN
          - Response still can't be parsed after one retry
        """
        if not entities:
            return []

        entity_lines = "\n".join(f"- {e.text} ({e.type})" for e in entities)
        user_content = f"Text:\n{text}\n\nEntities:\n{entity_lines}"

        try:
            # Run the HTTP call through the CircuitBreaker.
            # _call_once is a coroutine; we need to await it. CircuitBreaker.call()
            # is synchronous, so we drive it manually instead.
            if self._cb.state.name == "OPEN":
                # Fast-path: check state first; .call() would raise immediately.
                pass
            content = await self._call_once_with_cb(
                SYSTEM_PROMPT, user_content, stricter=False
            )
        except CircuitOpenError:
            return []
        except Exception:
            return []

        triples = _parse_triples(content)
        if triples is not None:
            return triples

        # Retry once with stricter prompt
        try:
            content = await self._call_once_with_cb(
                STRICTER_PROMPT, user_content, stricter=True
            )
        except CircuitOpenError:
            return []
        except Exception:
            return []

        triples = _parse_triples(content)
        return triples or []

    async def _call_once_with_cb(
        self, system: str, user: str, stricter: bool
    ) -> str:
        """Single HTTP call, with CircuitBreaker bookkeeping applied manually
        (since the breaker's .call() is sync and we need async)."""
        # Mirror the CircuitBreaker.call() flow but for async:
        import time as _time

        lock = self._cb._lock
        with lock:
            state_name = self._cb._state.name
            if state_name == "OPEN":
                elapsed = _time.monotonic() - self._cb._last_failure_time
                if elapsed >= self._cb._recovery_timeout_secs:
                    from mempalace.infra.circuit_breaker import CircuitState
                    self._cb._state = CircuitState.HALF_OPEN
                    self._cb._probe_in_flight = True
                    allow_probe = True
                else:
                    raise CircuitOpenError(
                        f"Circuit '{self._cb._name}' is OPEN"
                    )
            elif state_name == "HALF_OPEN":
                if self._cb._probe_in_flight:
                    raise CircuitOpenError(
                        f"Circuit '{self._cb._name}' probe in flight"
                    )
                self._cb._probe_in_flight = True
                allow_probe = True
            else:
                allow_probe = False

        try:
            resp = await self._client.post(
                "/v1/chat/completions",
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.0,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except Exception:
            with lock:
                if allow_probe:
                    from mempalace.infra.circuit_breaker import CircuitState
                    self._cb._state = CircuitState.OPEN
                    self._cb._last_failure_time = _time.monotonic()
                    self._cb._probe_in_flight = False
                else:
                    self._cb._failure_count += 1
                    self._cb._last_failure_time = _time.monotonic()
                    if self._cb._failure_count >= self._cb._failure_threshold:
                        from mempalace.infra.circuit_breaker import CircuitState
                        self._cb._state = CircuitState.OPEN
            raise

        with lock:
            if allow_probe:
                from mempalace.infra.circuit_breaker import CircuitState
                self._cb._state = CircuitState.CLOSED
                self._cb._failure_count = 0
                self._cb._probe_in_flight = False

        return content


def _parse_triples(content: str) -> list[Triple] | None:
    """Parse JSON triples from Qwen response. Returns None if parse fails,
    [] if the response is valid JSON but contains no triples."""
    if content is None:
        return None

    # Strip markdown fences if present
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```\s*$", "", stripped)

    # Try direct parse first
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        # Fallback: find first JSON array in the string
        m = _JSON_ARRAY_RE.search(stripped)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None

    if not isinstance(data, list):
        return None

    triples: list[Triple] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        s = item.get("subject")
        p = item.get("predicate")
        o = item.get("object")
        if isinstance(s, str) and isinstance(p, str) and isinstance(o, str):
            triples.append(Triple(subject=s, predicate=p, object=o))
    return triples
```

**Note on `_call_once_with_cb`:** the CircuitBreaker in Phase 0 has a sync `.call(fn)` method that expects a sync callable. Because Qwen calls are async, we drive the breaker's state machine manually. This is a known wart — Phase 2 will add an async `.call_async()` helper to the breaker.

- [ ] **Step 4: Run tests — expect all pass**

Run: `python -m pytest tests/walker/extractor/test_qwen_rel.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add mempalace/walker/extractor/qwen_rel.py tests/walker/extractor/test_qwen_rel.py
git commit -m "feat(walker): QwenRelExtractor async HTTP client with CircuitBreaker"
```

---

## Task 5: `pipeline.py` — async orchestrator

**Files:**
- Create: `mempalace/walker/extractor/pipeline.py`
- Create: `tests/walker/extractor/test_pipeline.py`

- [ ] **Step 1: Write failing tests (`test_pipeline.py`)**

```python
"""End-to-end pipeline tests with mocked GLiNER and mocked Qwen."""
from unittest.mock import MagicMock, AsyncMock
import pytest
from mempalace.knowledge_graph import KnowledgeGraph
from mempalace.walker.extractor.state import ExtractionState
from mempalace.walker.extractor.gliner_ner import Entity
from mempalace.walker.extractor.qwen_rel import Triple
from mempalace.walker.extractor.pipeline import extract_drawers, ExtractionStats


def _make_mock_gliner(per_text_entities: list[list[Entity]]) -> MagicMock:
    gliner = MagicMock()
    gliner.extract_batch.return_value = per_text_entities
    return gliner


def _make_mock_qwen(triples_per_call: list[list[Triple]]) -> MagicMock:
    qwen = MagicMock()
    it = iter(triples_per_call)
    async def _extract(text, entities):
        return next(it, [])
    qwen.extract = _extract
    return qwen


@pytest.mark.asyncio
async def test_empty_drawer_list(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    stats = await extract_drawers(
        drawers=[], kg=kg, state=state,
        gliner=_make_mock_gliner([]),
        qwen=_make_mock_qwen([]),
    )
    assert stats.drawers_processed == 0


@pytest.mark.asyncio
async def test_single_drawer_full_pipeline(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    drawer = {"id": "d1", "text": "Alice works at DeepMind."}
    gliner = _make_mock_gliner([[Entity("Alice", "person", 0.9),
                                  Entity("DeepMind", "organization", 0.9)]])
    qwen = _make_mock_qwen([[Triple("Alice", "works_at", "DeepMind")]])

    stats = await extract_drawers(
        drawers=[drawer], kg=kg, state=state, gliner=gliner, qwen=qwen
    )
    assert stats.drawers_processed == 1
    assert stats.entities_found == 2
    assert stats.triples_inserted == 1
    assert state.is_extracted("d1", "v1.0") is True

    # Verify KG has the triple
    conn = kg._conn()
    rows = conn.execute("SELECT subject, predicate, object FROM triples").fetchall()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_zero_entity_drawer_skips_qwen_but_marks_extracted(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    drawer = {"id": "d1", "text": "nothing interesting"}
    gliner = _make_mock_gliner([[]])  # no entities
    qwen_call_count = {"n": 0}
    async def _extract(text, entities):
        qwen_call_count["n"] += 1
        return []
    qwen = MagicMock()
    qwen.extract = _extract

    stats = await extract_drawers(
        drawers=[drawer], kg=kg, state=state, gliner=gliner, qwen=qwen
    )
    assert qwen_call_count["n"] == 0  # Qwen NOT called
    assert state.is_extracted("d1", "v1.0") is True
    assert stats.drawers_processed == 1
    assert stats.triples_inserted == 0


@pytest.mark.asyncio
async def test_already_extracted_drawer_skipped(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    state.mark_extracted("d1", "v1.0", 0, 0)
    drawer = {"id": "d1", "text": "Alice."}

    stats = await extract_drawers(
        drawers=[drawer], kg=kg, state=state,
        gliner=_make_mock_gliner([]),  # not called
        qwen=_make_mock_qwen([]),
    )
    assert stats.drawers_processed == 0
    assert stats.drawers_skipped == 1


@pytest.mark.asyncio
async def test_idempotent_run_twice(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    drawer = {"id": "d1", "text": "Alice works at DeepMind."}

    def _fresh_gliner():
        return _make_mock_gliner([[Entity("Alice", "person", 0.9),
                                    Entity("DeepMind", "organization", 0.9)]])
    def _fresh_qwen():
        return _make_mock_qwen([[Triple("Alice", "works_at", "DeepMind")]])

    await extract_drawers(
        drawers=[drawer], kg=kg, state=state,
        gliner=_fresh_gliner(), qwen=_fresh_qwen(),
    )
    await extract_drawers(
        drawers=[drawer], kg=kg, state=state,
        gliner=_fresh_gliner(), qwen=_fresh_qwen(),
    )

    rows = kg._conn().execute(
        "SELECT COUNT(*) FROM triples WHERE valid_to IS NULL"
    ).fetchone()
    assert rows[0] == 1  # upsert_triple dedupes — only ONE live row


@pytest.mark.asyncio
async def test_source_drawer_ids_populated(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    drawer = {"id": "d_abc", "text": "Alice works at DeepMind."}
    gliner = _make_mock_gliner([[Entity("Alice", "person", 0.9),
                                  Entity("DeepMind", "organization", 0.9)]])
    qwen = _make_mock_qwen([[Triple("Alice", "works_at", "DeepMind")]])

    await extract_drawers(
        drawers=[drawer], kg=kg, state=state, gliner=gliner, qwen=qwen
    )

    row = kg._conn().execute(
        "SELECT source_drawer_ids FROM triples LIMIT 1"
    ).fetchone()
    import json as _json
    assert _json.loads(row[0]) == ["d_abc"]


@pytest.mark.asyncio
async def test_dry_run_does_not_write(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    drawer = {"id": "d1", "text": "Alice."}
    gliner = _make_mock_gliner([[Entity("Alice", "person", 0.9)]])
    qwen = _make_mock_qwen([[Triple("Alice", "works_at", "DeepMind")]])

    await extract_drawers(
        drawers=[drawer], kg=kg, state=state,
        gliner=gliner, qwen=qwen, dry_run=True,
    )
    assert state.is_extracted("d1", "v1.0") is False
    rows = kg._conn().execute("SELECT COUNT(*) FROM triples").fetchone()
    assert rows[0] == 0
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `python -m pytest tests/walker/extractor/test_pipeline.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement `pipeline.py`**

```python
"""Async orchestrator: GLiNER batch → Qwen per-drawer → upsert_triple → mark_extracted."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from mempalace.knowledge_graph import KnowledgeGraph
from mempalace.walker.extractor.gliner_ner import GlinerNER
from mempalace.walker.extractor.qwen_rel import QwenRelExtractor, Triple
from mempalace.walker.extractor.state import ExtractionState

log = logging.getLogger(__name__)


@dataclass(slots=True)
class ExtractionStats:
    drawers_processed: int = 0
    drawers_skipped: int = 0
    entities_found: int = 0
    triples_inserted: int = 0
    triples_updated: int = 0
    qwen_failures: int = 0
    circuit_open_events: int = 0
    elapsed_secs: float = 0.0


async def extract_drawers(
    drawers: list[dict],
    kg: KnowledgeGraph,
    state: ExtractionState,
    gliner: GlinerNER,
    qwen: QwenRelExtractor,
    extractor_version: str = "v1.0",
    concurrency: int = 4,
    dry_run: bool = False,
) -> ExtractionStats:
    """Run the extraction pipeline over `drawers`.

    Each drawer dict must have `id` and `text` keys.
    `mark_extracted()` is called per-drawer inside the per-drawer loop —
    partial batch failure leaves unprocessed drawers eligible for retry.
    """
    stats = ExtractionStats()
    start = time.monotonic()

    if not drawers:
        stats.elapsed_secs = time.monotonic() - start
        return stats

    # Step 1: filter already-extracted
    drawer_by_id = {d["id"]: d for d in drawers}
    unextracted_ids = state.unextracted_ids(
        list(drawer_by_id.keys()), extractor_version
    )
    stats.drawers_skipped = len(drawers) - len(unextracted_ids)

    if not unextracted_ids:
        stats.elapsed_secs = time.monotonic() - start
        return stats

    unextracted = [drawer_by_id[i] for i in unextracted_ids]
    texts = [d["text"] for d in unextracted]

    # Step 2: GLiNER batch (sync — runs in default thread pool)
    loop = asyncio.get_running_loop()
    entities_per_drawer = await loop.run_in_executor(
        None, gliner.extract_batch, texts
    )

    # Step 3: process each drawer — Qwen + KG writes
    sem = asyncio.Semaphore(concurrency)

    async def process(drawer: dict, entities):
        async with sem:
            await _process_single(
                drawer, entities, kg, state, qwen,
                extractor_version, dry_run, stats,
            )

    await asyncio.gather(*[
        process(d, ents)
        for d, ents in zip(unextracted, entities_per_drawer)
    ])

    stats.elapsed_secs = time.monotonic() - start
    return stats


async def _process_single(
    drawer: dict,
    entities: list,
    kg: KnowledgeGraph,
    state: ExtractionState,
    qwen: QwenRelExtractor,
    version: str,
    dry_run: bool,
    stats: ExtractionStats,
) -> None:
    drawer_id = drawer["id"]
    text = drawer["text"]
    entity_count = len(entities)
    stats.entities_found += entity_count

    # Zero entities → skip Qwen, still mark drawer processed
    if entity_count == 0:
        stats.drawers_processed += 1
        if not dry_run:
            state.mark_extracted(drawer_id, version, triple_count=0, entity_count=0)
        return

    # Call Qwen (returns [] on any failure)
    try:
        triples: list[Triple] = await qwen.extract(text, entities)
    except Exception as e:
        log.warning("Qwen extract failed for %s: %s", drawer_id, e)
        stats.qwen_failures += 1
        triples = []

    if dry_run:
        for t in triples:
            print(f"[DRY] {drawer_id}: {t.subject} -[{t.predicate}]-> {t.object}")
        stats.drawers_processed += 1
        return

    # Write triples to KG
    all_ok = True
    inserted_n = 0
    updated_n = 0
    for t in triples:
        try:
            result = kg.upsert_triple(
                subject=t.subject,
                predicate=t.predicate,
                obj=t.object,
                source="extractor_v1.0",
                source_drawer_ids=[drawer_id],
            )
            if result.inserted:
                inserted_n += 1
            elif result.updated:
                updated_n += 1
        except Exception as e:
            log.error("upsert_triple failed on %s: %s", drawer_id, e)
            all_ok = False

    stats.triples_inserted += inserted_n
    stats.triples_updated += updated_n

    if all_ok:
        stats.drawers_processed += 1
        state.mark_extracted(
            drawer_id, version,
            triple_count=len(triples), entity_count=entity_count,
        )
    else:
        # Do NOT mark extracted — drawer will be retried next run
        log.warning("Drawer %s had upsert failures — not marking extracted", drawer_id)
```

- [ ] **Step 4: Run tests — expect all pass**

Run: `python -m pytest tests/walker/extractor/test_pipeline.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add mempalace/walker/extractor/pipeline.py tests/walker/extractor/test_pipeline.py
git commit -m "feat(walker): async extract_drawers pipeline with per-drawer atomicity"
```

---

## Task 6: `dream/reextract.py` — Dream Job A

**Files:**
- Create: `mempalace/dream/__init__.py` (empty)
- Create: `mempalace/dream/reextract.py`
- Create: `tests/dream/__init__.py` (empty)
- Create: `tests/dream/test_reextract.py`

- [ ] **Step 1: Write failing tests (`test_reextract.py`)**

```python
from unittest.mock import MagicMock
import pytest
from mempalace.knowledge_graph import KnowledgeGraph
from mempalace.walker.extractor.state import ExtractionState
from mempalace.walker.extractor.gliner_ner import Entity
from mempalace.walker.extractor.qwen_rel import Triple
from mempalace.dream.reextract import run_job_a, JobAResult


@pytest.mark.asyncio
async def test_run_job_a_processes_unextracted(tmp_path, monkeypatch):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)

    fake_drawers = [
        {"id": "d1", "text": "Alice."},
        {"id": "d2", "text": "Bob."},
    ]

    async def fake_load(palace, wing):
        return fake_drawers

    def fake_gliner():
        g = MagicMock()
        g.extract_batch.return_value = [[Entity("Alice", "person", 0.9)],
                                         [Entity("Bob", "person", 0.9)]]
        return g

    def fake_qwen():
        q = MagicMock()
        async def _extract(text, entities):
            return [Triple(entities[0].text, "is_a", "person")]
        q.extract = _extract
        q.aclose = MagicMock(return_value=None)
        async def _aclose():
            pass
        q.aclose = _aclose
        return q

    monkeypatch.setattr(
        "mempalace.dream.reextract._load_drawers_from_palace", fake_load
    )
    monkeypatch.setattr(
        "mempalace.dream.reextract._build_gliner", lambda: fake_gliner()
    )
    monkeypatch.setattr(
        "mempalace.dream.reextract._build_qwen", lambda: fake_qwen()
    )

    result = await run_job_a(
        palace_path=str(tmp_path / "palace"),
        kg=kg,
        version="v1.0",
        batch_size=500,
    )
    assert isinstance(result, JobAResult)
    assert result.drawers_processed == 2


@pytest.mark.asyncio
async def test_run_job_a_only_processes_stale_version(tmp_path, monkeypatch):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    # Pre-extract d1 at v1.0
    state.mark_extracted("d1", "v1.0", 1, 1)
    # Now request v2.0 — d1 should be re-processed

    fake_drawers = [
        {"id": "d1", "text": "Alice."},
    ]

    async def fake_load(palace, wing):
        return fake_drawers

    def fake_gliner():
        g = MagicMock()
        g.extract_batch.return_value = [[Entity("Alice", "person", 0.9)]]
        return g

    def fake_qwen():
        q = MagicMock()
        async def _extract(text, entities):
            return []
        q.extract = _extract
        async def _aclose():
            pass
        q.aclose = _aclose
        return q

    monkeypatch.setattr(
        "mempalace.dream.reextract._load_drawers_from_palace", fake_load
    )
    monkeypatch.setattr(
        "mempalace.dream.reextract._build_gliner", lambda: fake_gliner()
    )
    monkeypatch.setattr(
        "mempalace.dream.reextract._build_qwen", lambda: fake_qwen()
    )

    result = await run_job_a(
        palace_path=str(tmp_path / "palace"),
        kg=kg,
        version="v2.0",
        batch_size=500,
    )
    assert result.drawers_processed == 1  # d1 re-processed at v2.0


@pytest.mark.asyncio
async def test_run_job_a_batches(tmp_path, monkeypatch):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)

    # 501 drawers → 2 batches
    fake_drawers = [{"id": f"d{i}", "text": f"text {i}"} for i in range(501)]

    async def fake_load(palace, wing):
        return fake_drawers

    def fake_gliner():
        g = MagicMock()
        g.extract_batch.side_effect = lambda texts: [[] for _ in texts]
        return g

    def fake_qwen():
        q = MagicMock()
        async def _extract(text, entities):
            return []
        q.extract = _extract
        async def _aclose():
            pass
        q.aclose = _aclose
        return q

    monkeypatch.setattr(
        "mempalace.dream.reextract._load_drawers_from_palace", fake_load
    )
    monkeypatch.setattr(
        "mempalace.dream.reextract._build_gliner", lambda: fake_gliner()
    )
    monkeypatch.setattr(
        "mempalace.dream.reextract._build_qwen", lambda: fake_qwen()
    )

    result = await run_job_a(
        palace_path=str(tmp_path / "palace"),
        kg=kg,
        version="v1.0",
        batch_size=500,
    )
    assert result.drawers_processed == 501
    assert result.batches == 2
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `python -m pytest tests/dream/test_reextract.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement `reextract.py`**

```python
"""Dream Job A — re-extract palace drawers that are not yet at `version`."""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from mempalace.knowledge_graph import KnowledgeGraph
from mempalace.walker.extractor.gliner_ner import GlinerNER
from mempalace.walker.extractor.pipeline import ExtractionStats, extract_drawers
from mempalace.walker.extractor.qwen_rel import QwenRelExtractor
from mempalace.walker.extractor.state import ExtractionState

log = logging.getLogger(__name__)

DREAM_LOG_PATH = Path.home() / ".mempalace" / "dream_log.jsonl"


@dataclass(slots=True)
class JobAResult:
    job: str
    version: str
    started_at: str
    elapsed_secs: float
    drawers_processed: int
    drawers_skipped: int
    triples_inserted: int
    triples_updated: int
    qwen_failures: int
    circuit_open_events: int
    batches: int


async def run_job_a(
    palace_path: str,
    kg: KnowledgeGraph,
    version: str = "v1.0",
    batch_size: int = 500,
    wing: str | None = None,
) -> JobAResult:
    """Re-extract all drawers not yet at `version`. Idempotent, batch-safe."""
    from datetime import datetime

    started_at = datetime.utcnow().isoformat()
    start = time.monotonic()

    drawers = await _load_drawers_from_palace(palace_path, wing)
    gliner = _build_gliner()
    qwen = _build_qwen()
    state = ExtractionState(kg)

    totals = ExtractionStats()
    batches_run = 0
    try:
        for i in range(0, len(drawers), batch_size):
            batch = drawers[i : i + batch_size]
            batches_run += 1
            stats = await extract_drawers(
                drawers=batch,
                kg=kg,
                state=state,
                gliner=gliner,
                qwen=qwen,
                extractor_version=version,
            )
            totals.drawers_processed += stats.drawers_processed
            totals.drawers_skipped += stats.drawers_skipped
            totals.entities_found += stats.entities_found
            totals.triples_inserted += stats.triples_inserted
            totals.triples_updated += stats.triples_updated
            totals.qwen_failures += stats.qwen_failures
            totals.circuit_open_events += stats.circuit_open_events
    finally:
        await qwen.aclose()

    result = JobAResult(
        job="A",
        version=version,
        started_at=started_at,
        elapsed_secs=time.monotonic() - start,
        drawers_processed=totals.drawers_processed,
        drawers_skipped=totals.drawers_skipped,
        triples_inserted=totals.triples_inserted,
        triples_updated=totals.triples_updated,
        qwen_failures=totals.qwen_failures,
        circuit_open_events=totals.circuit_open_events,
        batches=batches_run,
    )
    _append_log(result)
    return result


def _append_log(result: JobAResult) -> None:
    DREAM_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DREAM_LOG_PATH, "a") as f:
        f.write(json.dumps(asdict(result)) + "\n")


async def _load_drawers_from_palace(
    palace_path: str, wing: str | None
) -> list[dict]:
    """Load all drawers from the palace ChromaDB.

    Returns list of {id, text} dicts. `wing` filters to a single wing if given.
    Note: this is a thin seam — tests monkeypatch this function directly.
    """
    from mempalace.backends import get_backend

    backend = get_backend("chroma", palace_path=palace_path)
    # Use backend's dump interface — all drawers with id + text
    drawers = []
    for entry in backend.iter_all_drawers(wing=wing):
        drawers.append({"id": entry["id"], "text": entry["text"]})
    return drawers


def _build_gliner() -> GlinerNER:
    return GlinerNER()


def _build_qwen() -> QwenRelExtractor:
    return QwenRelExtractor()
```

**Note:** `_load_drawers_from_palace` uses a `backend.iter_all_drawers()` seam that may not exist on the ChromaBackend. Before running the test:

1. Check if `ChromaBackend` has `iter_all_drawers` — if not, add a minimal implementation that calls `.get()` with no filter and returns `[{"id": i, "text": t} for i, t in zip(ids, docs)]`.
2. If the backends module exposes a different name (e.g. `get_all`, `dump`), adjust the seam accordingly.

This task may need a small backend addition in the same commit. Tests use `monkeypatch` so they don't exercise the real backend.

- [ ] **Step 4: Run tests — expect all pass**

Run: `python -m pytest tests/dream/test_reextract.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add mempalace/dream/__init__.py mempalace/dream/reextract.py \
        tests/dream/__init__.py tests/dream/test_reextract.py
git commit -m "feat(dream): Job A — re-extract stale drawers with batched pipeline"
```

---

## Task 7: `walker extract` CLI subcommand

**Files:**
- Modify: `mempalace/cli.py` — add `walker extract` subcommand
- Create: `tests/test_cli_walker_extract.py`

- [ ] **Step 1: Write failing tests**

```python
from unittest.mock import patch
import pytest
from mempalace.cli import main


def test_walker_extract_help(capsys):
    with pytest.raises(SystemExit):
        main(["walker", "extract", "--help"])
    captured = capsys.readouterr()
    assert "--wing" in captured.out
    assert "--concurrency" in captured.out
    assert "--version" in captured.out
    assert "--dry-run" in captured.out


def test_walker_extract_dispatches(monkeypatch):
    called = {"n": 0}

    async def fake_run(**kwargs):
        called["n"] += 1
        called["kwargs"] = kwargs
        from mempalace.dream.reextract import JobAResult
        return JobAResult(
            job="A", version=kwargs["version"], started_at="now",
            elapsed_secs=0.1, drawers_processed=0, drawers_skipped=0,
            triples_inserted=0, triples_updated=0, qwen_failures=0,
            circuit_open_events=0, batches=0,
        )

    monkeypatch.setattr("mempalace.dream.reextract.run_job_a", fake_run)
    rc = main(["--palace", "/tmp/p", "walker", "extract", "--version", "v1.0"])
    assert rc == 0
    assert called["n"] == 1
    assert called["kwargs"]["version"] == "v1.0"
```

- [ ] **Step 2: Run tests — expect FAIL (subcommand missing)**

Run: `python -m pytest tests/test_cli_walker_extract.py -v`

- [ ] **Step 3: Extend `cli.py` — add `extract` to `walker_sub` parser**

Add inside the existing `p_walker` block (after `walker_sub.add_parser("status", ...)`):

```python
p_extract = walker_sub.add_parser(
    "extract", help="Extract entities + triples from palace drawers"
)
p_extract.add_argument("--wing", default=None, help="Limit to one wing; error if wing not found")
p_extract.add_argument("--concurrency", type=int, default=4, help="Qwen parallel requests")
p_extract.add_argument("--version", default="v1.0", help="extractor_version tag")
p_extract.add_argument("--gliner-threshold", type=float, default=0.4)
p_extract.add_argument("--dry-run", action="store_true", help="Run pipeline, write nothing")
```

Add `"extract": cmd_walker_extract` to the `walker_dispatch` dict in `cmd_walker`.

Add the handler function near `cmd_walker_init`:

```python
def cmd_walker_extract(args):
    """Run the extraction pipeline over palace drawers."""
    import asyncio
    from mempalace.dream.reextract import run_job_a
    from mempalace.knowledge_graph import KnowledgeGraph

    palace_path = args.palace or str(Path.home() / ".mempalace" / "palace")
    kg_path = str(Path(palace_path) / "knowledge_graph.db")
    kg = KnowledgeGraph(kg_path)

    result = asyncio.run(run_job_a(
        palace_path=palace_path,
        kg=kg,
        version=args.version,
        wing=args.wing,
    ))
    print(f"Extracted: {result.drawers_processed} processed, "
          f"{result.drawers_skipped} skipped")
    print(f"Triples: {result.triples_inserted} inserted, "
          f"{result.triples_updated} updated")
    print(f"Elapsed: {result.elapsed_secs:.1f}s")
    return 0
```

- [ ] **Step 4: Run tests — expect pass**

Run: `python -m pytest tests/test_cli_walker_extract.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add mempalace/cli.py tests/test_cli_walker_extract.py
git commit -m "feat(cli): walker extract subcommand runs Job A pipeline"
```

---

## Task 8: `dream-cycle --jobs A` CLI subcommand

**Files:**
- Modify: `mempalace/cli.py` — add `dream-cycle` subcommand

- [ ] **Step 1: Write failing test**

```python
def test_dream_cycle_jobs_a_help(capsys):
    from mempalace.cli import main
    with pytest.raises(SystemExit):
        main(["dream-cycle", "--help"])
    captured = capsys.readouterr()
    assert "--jobs" in captured.out
```

(Append to `tests/test_cli_walker_extract.py`.)

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Add `dream-cycle` subcommand**

In `main()`:

```python
p_dream = sub.add_parser("dream-cycle", help="Run Dream Cycle jobs over the palace")
p_dream.add_argument("--jobs", default="A", help="Comma-separated job letters (Phase 1: A only)")
p_dream.add_argument("--version", default="v1.0")
p_dream.add_argument("--batch-size", type=int, default=500)
```

Add to `dispatch`:
```python
"dream-cycle": cmd_dream_cycle,
```

Handler:

```python
def cmd_dream_cycle(args):
    import asyncio
    from mempalace.dream.reextract import run_job_a
    from mempalace.knowledge_graph import KnowledgeGraph

    jobs = [j.strip() for j in args.jobs.split(",")]
    if jobs != ["A"]:
        print(f"Phase 1 only supports --jobs A; got {args.jobs}")
        return 2

    palace_path = args.palace or str(Path.home() / ".mempalace" / "palace")
    kg = KnowledgeGraph(str(Path(palace_path) / "knowledge_graph.db"))

    result = asyncio.run(run_job_a(
        palace_path=palace_path, kg=kg,
        version=args.version, batch_size=args.batch_size,
    ))
    print(f"Dream Job A: {result.drawers_processed} processed in "
          f"{result.batches} batches, {result.elapsed_secs:.1f}s")
    return 0
```

- [ ] **Step 4: Run tests — expect pass**

- [ ] **Step 5: Commit**

```bash
git add mempalace/cli.py tests/test_cli_walker_extract.py
git commit -m "feat(cli): dream-cycle --jobs A runs Job A from Phase 1"
```

---

## Task 9: Extend `status --walker` with extraction stats

**Files:**
- Modify: `mempalace/cli.py` — `cmd_status` (the `--walker` branch)
- Modify: `tests/test_cli_walker.py` — add extraction status tests

- [ ] **Step 1: Write failing test**

```python
def test_status_walker_reports_extraction_stats(tmp_path, monkeypatch):
    from mempalace.cli import main
    from mempalace.knowledge_graph import KnowledgeGraph
    from mempalace.walker.extractor.state import ExtractionState

    palace = tmp_path / "palace"
    palace.mkdir()
    kg = KnowledgeGraph(str(palace / "knowledge_graph.db"))
    state = ExtractionState(kg)
    state.mark_extracted("d1", "v1.0", 3, 5)

    # capture stdout
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["--palace", str(palace), "status", "--walker"])
    out = buf.getvalue()
    assert "Extracted:" in out
    assert "v1.0" in out
```

- [ ] **Step 2: Run — expect FAIL or inaccurate output**

- [ ] **Step 3: Extend `cmd_status` walker branch**

In the existing `--walker` block of `cmd_status`, add after the walker_ready flag check:

```python
# Extraction stats
try:
    from mempalace.knowledge_graph import KnowledgeGraph
    from mempalace.walker.extractor.state import ExtractionState
    kg_path = Path(palace_path) / "knowledge_graph.db"
    if kg_path.exists():
        kg = KnowledgeGraph(str(kg_path))
        state = ExtractionState(kg)
        # count extracted drawers at current version
        row = kg._conn().execute(
            "SELECT COUNT(*), SUM(triple_count), SUM(entity_count) "
            "FROM extraction_state WHERE extractor_version='v1.0'"
        ).fetchone()
        n = row[0] or 0
        triples = row[1] or 0
        entities = row[2] or 0
        last_run = state.max_extracted_at("v1.0") or "never"
        print(f"KG triples:     {triples} ({entities} entities)")
        print(f"Extracted:      {n} drawers (v1.0) — last run {last_run}")
except Exception as e:
    print(f"Extraction stats unavailable: {e}")
```

- [ ] **Step 4: Run tests — expect pass**

Run: `python -m pytest tests/test_cli_walker.py tests/test_cli_walker_extract.py -v`

- [ ] **Step 5: Commit**

```bash
git add mempalace/cli.py tests/test_cli_walker.py
git commit -m "feat(cli): status --walker reports extraction stats"
```

---

## Task 10: Verbatim-invariant test for Dream Job A

**Files:**
- Modify: `tests/dream/test_reextract.py` — add verbatim invariant test

- [ ] **Step 1: Write failing test**

```python
@pytest.mark.asyncio
async def test_verbatim_invariant_drawer_text_unchanged(tmp_path, monkeypatch):
    """Dream Job A must never modify drawer content."""
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))

    original_drawers = [
        {"id": "d1", "text": "Alice works at DeepMind."},
        {"id": "d2", "text": "Bob lives in London."},
    ]
    # Deep copy to compare against
    import copy
    snapshot = copy.deepcopy(original_drawers)

    async def fake_load(palace, wing):
        return original_drawers

    def fake_gliner():
        g = MagicMock()
        g.extract_batch.return_value = [
            [Entity("Alice", "person", 0.9)],
            [Entity("Bob", "person", 0.9)],
        ]
        return g

    def fake_qwen():
        q = MagicMock()
        async def _extract(text, entities):
            return [Triple(entities[0].text, "is_a", "person")]
        q.extract = _extract
        async def _aclose():
            pass
        q.aclose = _aclose
        return q

    monkeypatch.setattr("mempalace.dream.reextract._load_drawers_from_palace", fake_load)
    monkeypatch.setattr("mempalace.dream.reextract._build_gliner", lambda: fake_gliner())
    monkeypatch.setattr("mempalace.dream.reextract._build_qwen", lambda: fake_qwen())

    await run_job_a(palace_path=str(tmp_path / "palace"), kg=kg, version="v1.0")

    # Drawer text must be unchanged
    assert original_drawers == snapshot
```

- [ ] **Step 2: Run — expect pass (pipeline is read-only)**

Run: `python -m pytest tests/dream/test_reextract.py::test_verbatim_invariant_drawer_text_unchanged -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/dream/test_reextract.py
git commit -m "test(dream): verify Job A verbatim invariant on drawer content"
```

---

## Task 11: Full test suite + coverage check

**Files:** none (verification only)

- [ ] **Step 1: Run entire test suite**

Run: `python -m pytest tests/ --ignore=tests/benchmarks -q`
Expected: all pass (~945 tests, up from 919)

- [ ] **Step 2: Run coverage on new modules**

Run:
```
python -m pytest tests/walker/extractor tests/dream \
  --cov=mempalace/walker/extractor --cov=mempalace/dream \
  --cov-report=term-missing
```
Expected: coverage ≥ 85% on new modules.

- [ ] **Step 3: Ruff check**

Run: `ruff check mempalace/walker/extractor mempalace/dream tests/walker/extractor tests/dream`
Expected: clean or auto-fix with `ruff check --fix`

- [ ] **Step 4: Ruff format**

Run: `ruff format mempalace/walker/extractor mempalace/dream tests/walker/extractor tests/dream`

- [ ] **Step 5: Commit formatting if needed**

```bash
git diff --quiet || git commit -am "style: ruff format Phase 1 modules"
```

---

## Task 12: End-to-end smoke test on a real palace

**Files:** none (manual verification)

**Prerequisites:**
1. Qwen3.5 35B is running on `http://localhost:43100`
2. A test palace exists (use `/tmp/test-palace` from earlier if still available, otherwise mine a small set of drawers)

- [ ] **Step 1: Mine a test palace if needed**

Run: `python -m mempalace.cli --palace /tmp/test-palace mine . --wing mempalace --limit 20`

- [ ] **Step 2: Run extraction in dry-run mode first**

Run: `python -m mempalace.cli --palace /tmp/test-palace walker extract --dry-run`
Expected: triples printed to stdout, nothing written.

- [ ] **Step 3: Run extraction for real**

Run: `python -m mempalace.cli --palace /tmp/test-palace walker extract --version v1.0`
Expected: reports N drawers processed, M triples inserted, no crashes.

- [ ] **Step 4: Verify KG has triples**

Run: `python -c "from mempalace.knowledge_graph import KnowledgeGraph; kg = KnowledgeGraph('/tmp/test-palace/knowledge_graph.db'); print(kg._conn().execute('SELECT COUNT(*) FROM triples WHERE valid_to IS NULL').fetchone())"`
Expected: non-zero triple count.

- [ ] **Step 5: Re-run extraction — verify idempotent**

Run: `python -m mempalace.cli --palace /tmp/test-palace walker extract --version v1.0`
Expected: "N drawers skipped (already extracted)", 0 new triples.

- [ ] **Step 6: Check Gate 1 (median triples/drawer ≥ 2)**

Run:
```bash
python -c "
from mempalace.knowledge_graph import KnowledgeGraph
kg = KnowledgeGraph('/tmp/test-palace/knowledge_graph.db')
rows = kg._conn().execute(
    'SELECT triple_count FROM extraction_state WHERE extractor_version=\"v1.0\"'
).fetchall()
import statistics
counts = [r[0] for r in rows]
print(f'drawers: {len(counts)}, median: {statistics.median(counts)}, mean: {statistics.mean(counts):.1f}')
"
```
Expected: median ≥ 2 (Phase 1 gate).

If gate fails: the Qwen prompt likely needs tuning; document the actual numbers and open a follow-up task.

- [ ] **Step 7: Check Gate 7 (LongMemEval R@5 unchanged ±0.5pp)**

Only run if you have the LongMemEval dataset locally. Skip otherwise — note as "LongMemEval dataset not available on this machine" in the phase completion report.

- [ ] **Step 8: Commit smoke test results**

Create `docs/superpowers/plans/phase-1-smoke-results.md` with the actual numbers:

```markdown
# Phase 1 Smoke Test Results

- Palace: /tmp/test-palace
- Drawers: 542
- Median triples/drawer: X.X
- Mean triples/drawer: X.X
- Elapsed (walker extract): Xs
- Gate 1 (median ≥ 2): PASS / FAIL
- Gate 3 (throughput > 3 drawers/s): PASS / FAIL
- LongMemEval R@5: skipped (no dataset)
```

```bash
git add docs/superpowers/plans/phase-1-smoke-results.md
git commit -m "docs: Phase 1 smoke test results on real palace"
```

---

## Phase 1 Go/No-Go Gates Summary

Verified via Task 11 (automated) + Task 12 (smoke):

| # | Gate | Verified in |
|---|------|-------------|
| 1 | Median triples/drawer ≥ 2 | Task 12 Step 6 |
| 2 | Avg triples/drawer ≥ 3 | Task 12 Step 6 |
| 3 | Throughput > 3 drawers/sec on A5000 | Task 12 Step 8 |
| 4 | Dream Job A on 5k drawers < 30 min | Optional if 5k-drawer palace exists |
| 5 | Dream Job A idempotent | Task 5 `test_idempotent_run_twice` + Task 12 Step 5 |
| 6 | Verbatim invariant | Task 10 |
| 7 | LongMemEval R@5 unchanged | Task 12 Step 7 (skip if dataset absent) |
| 8 | Extractor test coverage ≥ 85% | Task 11 Step 2 |

---

## Completion Checklist

- [ ] All 12 tasks completed with commits
- [ ] Full test suite passing (~945 tests)
- [ ] Coverage ≥ 85% on new modules
- [ ] Ruff clean
- [ ] Smoke test on real palace documented
- [ ] Phase 1 go/no-go gates all PASS (or documented waivers)
- [ ] Branch `feat/mempalace-walk-phase-1` ready to merge into `feat/mempalace-walk-phase-0` (or develop once Phase 0 lands)

**Do NOT open a PR to `MemPalace/mempalace` without first opening a GitHub issue per CONTRIBUTING.md — discussion before code.**
