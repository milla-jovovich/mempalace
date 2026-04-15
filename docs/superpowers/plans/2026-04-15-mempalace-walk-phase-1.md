# MemPalace Walk — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the extraction pipeline that populates the knowledge graph from palace drawers via GLiNER (entities) + Qwen3.5 35B HTTP (relationships), producing a dense entity-relationship graph (target: median ≥ 2 triples/drawer).

**Architecture:** Two-model pipeline. GLiNER runs in-process (batched, 33k texts/s). Qwen3.5 35B is reached over HTTP at `localhost:43100` (OpenAI-compatible). An async orchestrator runs Qwen calls with `asyncio.gather` + a semaphore (concurrency=4). A new `extraction_state` SQLite table tracks which drawers have been extracted per `extractor_version`. Idempotent and resumable.

**Tech Stack:** Python 3.13, GLiNER, httpx async, asyncio, SQLite (WAL), existing `KnowledgeGraph` + `CircuitBreaker` from Phase 0.

**Spec:** `docs/superpowers/specs/2026-04-15-mempalace-walk-phase-1-design.md`

---

## Task Dependency Graph

Subagent-driven-development must respect this ordering. Parallel groups may run concurrently; each group must complete before the next starts.

```
Group A (parallel):  Task 1, Task 1b, Task 2, Task 3
Group B (parallel):  Task 4 (needs 1, 1b, 3), Task 5a (needs 1)
Group C:             Task 5 (needs 2, 3, 4)
Group D:             Task 6 (needs 5, 5a)
Group E (parallel):  Task 7, Task 8, Task 9 (all need 6; 9 also needs 2)
Group F:             Task 10 (needs all above)
Group G:             Task 11 smoke (needs 10)
```

Each task header declares its dependencies explicitly.

---

## File Structure

**New/modified files:**
```
mempalace/infra/circuit_breaker.py      # MODIFY — add async call_async()
mempalace/backends/chroma.py            # MODIFY — add iter_drawers()
mempalace/walker/extractor/
  __init__.py
  gliner_ner.py                         # GlinerNER
  qwen_rel.py                           # QwenRelExtractor (async + CircuitBreaker)
  state.py                              # ExtractionState
  pipeline.py                           # extract_drawers() + ExtractionStats
mempalace/dream/
  __init__.py
  reextract.py                          # run_job_a()
pyproject.toml                          # httpx + pytest-asyncio + asyncio_mode
mempalace/cli.py                        # walker extract, dream-cycle, status --walker
tests/walker/extractor/{__init__,test_state,test_gliner_ner,test_qwen_rel,test_pipeline}.py
tests/dream/{__init__,test_reextract}.py
tests/infra/test_circuit_breaker_async.py
tests/backends/test_chroma_iter_drawers.py
tests/test_cli_walker_extract.py
```

---

## Task 1: Dependencies — httpx + pytest-asyncio

**Depends on:** nothing

**Files:** modify `pyproject.toml`

- [ ] **Step 1:** Add `"httpx>=0.27.0",` to the `[project.optional-dependencies].walker` list.
- [ ] **Step 2:** Add `"pytest-asyncio>=0.23",` to the `[project.optional-dependencies].dev` list.
- [ ] **Step 3:** In `[tool.pytest.ini_options]` add `asyncio_mode = "auto"`. Create the block if missing.
- [ ] **Step 4:** Run `pip install -e ".[dev]"` — expect success.
- [ ] **Step 5:** Verify: `python -c "import httpx, pytest_asyncio; print(httpx.__version__, pytest_asyncio.__version__)"`.
- [ ] **Step 6:** Commit:
  ```bash
  git add pyproject.toml
  git commit -m "deps: httpx (walker) + pytest-asyncio (dev) + asyncio_mode=auto"
  ```

---

## Task 1b: Extend `CircuitBreaker` with `call_async()`

**Depends on:** nothing (modifies Phase 0 file)

**Files:**
- Modify: `mempalace/infra/circuit_breaker.py`
- Create: `tests/infra/__init__.py` (empty if missing)
- Create: `tests/infra/test_circuit_breaker_async.py`

**Why:** Phase 0 `CircuitBreaker.call(fn)` is synchronous; Task 4 needs async wrapping.

- [ ] **Step 1: Write failing tests**

```python
import asyncio
import pytest
from mempalace.infra.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState


async def _ok(v): return v
async def _fail(): raise RuntimeError("boom")


async def test_async_closed_passes_through():
    cb = CircuitBreaker("t", failure_threshold=3, recovery_timeout_secs=1.0)
    assert await cb.call_async(lambda: _ok("hi")) == "hi"
    assert cb.state == CircuitState.CLOSED


async def test_async_opens_after_threshold():
    cb = CircuitBreaker("t", failure_threshold=2, recovery_timeout_secs=1.0)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            await cb.call_async(lambda: _fail())
    assert cb.state == CircuitState.OPEN


async def test_async_open_rejects_immediately():
    cb = CircuitBreaker("t", failure_threshold=1, recovery_timeout_secs=10.0)
    with pytest.raises(RuntimeError):
        await cb.call_async(lambda: _fail())
    with pytest.raises(CircuitOpenError):
        await cb.call_async(lambda: _ok("x"))


async def test_async_half_open_success_closes():
    cb = CircuitBreaker("t", failure_threshold=1, recovery_timeout_secs=0.1)
    with pytest.raises(RuntimeError):
        await cb.call_async(lambda: _fail())
    await asyncio.sleep(0.15)
    assert await cb.call_async(lambda: _ok("probe")) == "probe"
    assert cb.state == CircuitState.CLOSED


async def test_async_half_open_failure_reopens():
    cb = CircuitBreaker("t", failure_threshold=1, recovery_timeout_secs=0.1)
    with pytest.raises(RuntimeError):
        await cb.call_async(lambda: _fail())
    await asyncio.sleep(0.15)
    with pytest.raises(RuntimeError):
        await cb.call_async(lambda: _fail())
    assert cb.state == CircuitState.OPEN


async def test_async_concurrent_probe_guard():
    cb = CircuitBreaker("t", failure_threshold=1, recovery_timeout_secs=0.05)
    with pytest.raises(RuntimeError):
        await cb.call_async(lambda: _fail())
    await asyncio.sleep(0.1)

    async def slow():
        await asyncio.sleep(0.05)
        return "slow"

    async def runner():
        try:
            return await cb.call_async(slow)
        except CircuitOpenError:
            return "blocked"

    results = await asyncio.gather(runner(), runner())
    assert results.count("slow") == 1
    assert results.count("blocked") == 1
```

- [ ] **Step 2:** Run: `python -m pytest tests/infra/test_circuit_breaker_async.py -v` — expect FAIL.

- [ ] **Step 3: Implement**

In `mempalace/infra/circuit_breaker.py`, inside the `CircuitBreaker` class (same indent as the existing `call` method), add:

```python
    async def call_async(self, afn):
        """Async analog of .call(): awaits afn() under the same state machine.

        afn must be a zero-arg callable returning an awaitable.
        The breaker wraps ONLY the awaited call — any post-processing the
        caller does with the result is NOT counted as a failure.
        """
        with self._lock:
            if self._state == CircuitState.OPEN:
                elapsed = time.monotonic() - self._last_failure_time
                if elapsed >= self._recovery_timeout_secs:
                    self._state = CircuitState.HALF_OPEN
                    self._probe_in_flight = True
                    allow_probe = True
                else:
                    raise CircuitOpenError(
                        f"Circuit '{self._name}' is OPEN "
                        f"(retry after {self._recovery_timeout_secs}s)"
                    )
            elif self._state == CircuitState.HALF_OPEN:
                if self._probe_in_flight:
                    raise CircuitOpenError(
                        f"Circuit '{self._name}' is HALF_OPEN — probe already in flight"
                    )
                self._probe_in_flight = True
                allow_probe = True
            else:
                allow_probe = False

        try:
            result = await afn()
        except Exception:
            with self._lock:
                if allow_probe:
                    self._state = CircuitState.OPEN
                    self._last_failure_time = time.monotonic()
                    self._probe_in_flight = False
                else:
                    self._failure_count += 1
                    self._last_failure_time = time.monotonic()
                    if self._failure_count >= self._failure_threshold:
                        self._state = CircuitState.OPEN
            raise

        with self._lock:
            if allow_probe:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._probe_in_flight = False

        return result
```

- [ ] **Step 4:** Run tests — expect 6 passed.
- [ ] **Step 5:** Verify Phase 0 sync tests still pass: `python -m pytest tests/infra/ -v`.
- [ ] **Step 6:** Commit:
  ```bash
  git add mempalace/infra/circuit_breaker.py tests/infra/test_circuit_breaker_async.py tests/infra/__init__.py
  git commit -m "feat(infra): CircuitBreaker.call_async() for async wrapping"
  ```

---

## Task 2: `ExtractionState` — SQLite table with shared write lock

**Depends on:** nothing

**Files:**
- Create: `mempalace/walker/extractor/__init__.py` (empty)
- Create: `mempalace/walker/extractor/state.py`
- Create: `tests/walker/extractor/__init__.py` (empty)
- Create: `tests/walker/extractor/test_state.py`

**Design note:** `ExtractionState` must acquire `KnowledgeGraph._write_lock` for every write. Both `upsert_triple()` and `mark_extracted()` share the same SQLite connection under WAL. Without the shared lock, a `mark_extracted()` INSERT can execute mid-transaction of a `BEGIN IMMEDIATE ... COMMIT` on `upsert_triple()`.

- [ ] **Step 1: Write failing tests (`test_state.py`)**

```python
import threading
import pytest
from mempalace.knowledge_graph import KnowledgeGraph
from mempalace.walker.extractor.state import ExtractionState


def test_table_created_with_correct_schema(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    ExtractionState(kg)
    cols = kg._conn().execute("PRAGMA table_info(extraction_state)").fetchall()
    names = [c[1] for c in cols]
    assert names == [
        "drawer_id", "extractor_version", "extracted_at",
        "triple_count", "entity_count",
    ]
    pk = [c for c in cols if c[5] == 1]
    assert len(pk) == 1
    assert pk[0][1] == "drawer_id"


def test_is_extracted_unknown_drawer(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    assert state.is_extracted("drawer_1", "v1.0") is False


def test_mark_and_query(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    state.mark_extracted("d1", "v1.0", triple_count=3, entity_count=5)
    assert state.is_extracted("d1", "v1.0") is True
    assert state.is_extracted("d1", "v1.1") is False


def test_mark_replaces_prior(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    state.mark_extracted("d1", "v1.0", 2, 3)
    state.mark_extracted("d1", "v1.0", 4, 6)
    row = kg._conn().execute(
        "SELECT triple_count, entity_count FROM extraction_state WHERE drawer_id='d1'"
    ).fetchone()
    assert row[0] == 4 and row[1] == 6


def test_unextracted_ids_filters(tmp_path):
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
    assert state.unextracted_ids(["d1"], "v1.1") == ["d1"]


def test_max_extracted_at(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    state.mark_extracted("d1", "v1.0", 0, 0)
    assert state.max_extracted_at("v1.0") is not None
    assert state.max_extracted_at("v2.0") is None


def test_concurrent_writes_no_errors(tmp_path):
    """Verify shared-lock prevents mid-transaction collisions."""
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    errors = []

    def upsert_worker(i):
        try:
            kg.upsert_triple(f"Alice{i}", "knows", f"Bob{i}")
        except Exception as e:
            errors.append(e)

    def state_worker(i):
        try:
            state.mark_extracted(f"d{i}", "v1.0", 1, 2)
        except Exception as e:
            errors.append(e)

    threads = []
    for i in range(20):
        threads.append(threading.Thread(target=upsert_worker, args=(i,)))
        threads.append(threading.Thread(target=state_worker, args=(i,)))
    for t in threads: t.start()
    for t in threads: t.join()
    assert errors == []
```

- [ ] **Step 2:** Run: expect ImportError.

- [ ] **Step 3: Implement `state.py`**

```python
"""Tracks which drawers have been extracted per extractor_version."""
from __future__ import annotations

from mempalace.knowledge_graph import KnowledgeGraph


class ExtractionState:
    """SQLite-backed extraction tracking. Shares knowledge_graph.db."""

    def __init__(self, kg: KnowledgeGraph) -> None:
        self._kg = kg
        self._init_table()

    def _init_table(self) -> None:
        with self._kg._write_lock:
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
        self, drawer_id: str, version: str,
        triple_count: int, entity_count: int,
    ) -> None:
        with self._kg._write_lock:
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

- [ ] **Step 4:** Run tests — expect 8 passed.
- [ ] **Step 5:** Commit:
  ```bash
  git add mempalace/walker/extractor/__init__.py mempalace/walker/extractor/state.py \
          tests/walker/extractor/__init__.py tests/walker/extractor/test_state.py
  git commit -m "feat(walker): ExtractionState with shared KG write lock"
  ```

---

## Task 3: `GlinerNER` — entity extraction wrapper

**Depends on:** nothing

**Files:**
- Create: `mempalace/walker/extractor/gliner_ner.py`
- Create: `tests/walker/extractor/test_gliner_ner.py`

**Note:** Real GLiNER downloads a 500MB model. Tests mock via `__new__` bypass.

- [ ] **Step 1:** Enumerate `HardwareTier` values:
  ```bash
  python -c "from mempalace.walker.gpu_detect import HardwareTier; print(list(HardwareTier))"
  ```
  Expected: `[HardwareTier.FULL, HardwareTier.REDUCED, HardwareTier.CPU_ONLY]`. Adjust the parametrized test in Step 2 if different.

- [ ] **Step 2: Write failing tests**

```python
from unittest.mock import MagicMock
import pytest
from mempalace.walker.extractor.gliner_ner import GlinerNER, Entity, ENTITY_TYPES
from mempalace.walker.gpu_detect import HardwareTier, WalkerHardware


def _fake_ner(fake_predict):
    ner = GlinerNER.__new__(GlinerNER)
    ner._model = MagicMock()
    ner._model.batch_predict_entities.side_effect = fake_predict
    ner._device = "cpu"
    return ner


def test_entity_dataclass():
    e = Entity("Alice", "person", 0.92)
    assert e.text == "Alice" and e.type == "person"


def test_entity_types_contains_core():
    for t in ("person", "organization", "location", "date"):
        assert t in ENTITY_TYPES


@pytest.mark.parametrize("tier,expected", [
    (HardwareTier.FULL, "cuda"),
    (HardwareTier.REDUCED, "cuda"),
    (HardwareTier.CPU_ONLY, "cpu"),
])
def test_select_device_for_tier(monkeypatch, tier, expected):
    fake = WalkerHardware(tier=tier, device_name="x", vram_gb=0.0)
    monkeypatch.setattr(
        "mempalace.walker.extractor.gliner_ner.detect_hardware", lambda: fake
    )
    assert GlinerNER._select_device() == expected


def test_select_device_fallback_on_error(monkeypatch):
    def boom(): raise RuntimeError("no cuda")
    monkeypatch.setattr(
        "mempalace.walker.extractor.gliner_ner.detect_hardware", boom
    )
    assert GlinerNER._select_device() == "cpu"


def test_extract_batch_maps_entities():
    fake_predict = lambda texts, labels, threshold: [
        [{"text": "Alice", "label": "person", "score": 0.9}],
        [{"text": "DeepMind", "label": "organization", "score": 0.85}],
    ]
    ner = _fake_ner(fake_predict)
    out = ner.extract_batch(["a", "b"])
    assert len(out) == 2
    assert out[0][0].text == "Alice"
    assert out[1][0].type == "organization"


def test_extract_batch_empty_input():
    ner = _fake_ner(lambda *a, **k: [])
    assert ner.extract_batch([]) == []
    ner._model.batch_predict_entities.assert_not_called()


def test_extract_batch_passes_threshold():
    ner = _fake_ner(lambda texts, labels, threshold: [[]])
    ner.extract_batch(["t"], threshold=0.6)
    ner._model.batch_predict_entities.assert_called_with(
        ["t"], ENTITY_TYPES, threshold=0.6
    )
```

- [ ] **Step 3:** Run — expect ImportError.

- [ ] **Step 4: Implement `gliner_ner.py`**

```python
"""GLiNER wrapper — batched entity extraction with GPU autodetect."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from mempalace.walker.gpu_detect import HardwareTier, detect_hardware

log = logging.getLogger(__name__)

ENTITY_TYPES: list[str] = [
    "person", "organization", "location",
    "date", "project", "technology", "event",
]


@dataclass(slots=True)
class Entity:
    text: str
    type: str
    score: float


class GlinerNER:
    def __init__(
        self,
        model: str = "urchade/gliner_multi-v2.1",
        device: str | None = None,
    ) -> None:
        from gliner import GLiNER
        self._device = device or GlinerNER._select_device()
        try:
            self._model = GLiNER.from_pretrained(model).to(self._device)
        except Exception as e:
            if self._device == "cuda":
                log.warning("GLiNER failed on cuda (%s); falling back to cpu", e)
                self._device = "cpu"
                self._model = GLiNER.from_pretrained(model).to("cpu")
            else:
                raise

    def extract_batch(
        self, texts: list[str], threshold: float = 0.4
    ) -> list[list[Entity]]:
        if not texts:
            return []
        raw = self._model.batch_predict_entities(
            texts, ENTITY_TYPES, threshold=threshold
        )
        return [
            [Entity(r["text"], r["label"], r["score"]) for r in per_text]
            for per_text in raw
        ]

    @staticmethod
    def _select_device() -> str:
        """Returns 'cuda' if a GPU is available, else 'cpu'. Fallback on error."""
        try:
            hw = detect_hardware()
        except Exception as e:
            log.warning("detect_hardware failed: %s — falling back to cpu", e)
            return "cpu"
        return "cpu" if hw.tier == HardwareTier.CPU_ONLY else "cuda"
```

- [ ] **Step 5:** Run tests — expect 9 passed.
- [ ] **Step 6:** Commit:
  ```bash
  git add mempalace/walker/extractor/gliner_ner.py tests/walker/extractor/test_gliner_ner.py
  git commit -m "feat(walker): GlinerNER with device autodetect + CPU fallback"
  ```

---

## Task 4: `QwenRelExtractor` — async HTTP via `call_async`

**Depends on:** Task 1, Task 1b, Task 3

**Files:**
- Create: `mempalace/walker/extractor/qwen_rel.py`
- Create: `tests/walker/extractor/test_qwen_rel.py`

- [ ] **Step 0:** Verify exports:
  ```bash
  python -c "from mempalace.infra.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState"
  ```

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2:** Run — expect ImportError.

- [ ] **Step 3: Implement `qwen_rel.py`**

```python
"""Async HTTP client for Qwen3.5 35B relationship extraction.

Uses CircuitBreaker.call_async() from Phase 0+Task 1b.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import httpx

from mempalace.infra.circuit_breaker import CircuitBreaker, CircuitOpenError
from mempalace.walker.extractor.gliner_ner import Entity

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Extract relationships as JSON triples from the text.\n"
    'Return ONLY a JSON array: [{"subject": "...", "predicate": "...", "object": "..."}]\n'
    "Use only entities from the provided list. Predicates must be snake_case verbs.\n"
    "Return [] if no clear relationships exist. No explanation, no markdown."
)

STRICTER_PROMPT = (
    'Return ONLY a JSON array of {"subject","predicate","object"} objects.\n'
    "No markdown, no explanation, no other text. Just the JSON array."
)


@dataclass(slots=True)
class Triple:
    subject: str
    predicate: str
    object: str


class QwenRelExtractor:
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
        self._cb = CircuitBreaker("qwen_rel", failure_threshold=3, recovery_timeout_secs=30.0)
        self._preflight_check()

    def _preflight_check(self) -> None:
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
        if not entities or not text or not text.strip():
            return []

        entity_lines = "\n".join(f"- {e.text} ({e.type})" for e in entities)
        user_content = f"Text:\n{text}\n\nEntities:\n{entity_lines}"

        content = await self._http_call(SYSTEM_PROMPT, user_content)
        if content is None:
            return []

        triples = _parse_triples(content)
        if triples is not None:
            return triples

        # Parse failures do NOT count as HTTP failures — breaker stays closed.
        content = await self._http_call(STRICTER_PROMPT, user_content)
        if content is None:
            return []

        return _parse_triples(content) or []

    async def _http_call(self, system: str, user: str) -> str | None:
        try:
            return await self._cb.call_async(lambda: self._do_post(system, user))
        except CircuitOpenError:
            log.warning("Qwen circuit OPEN — skipping call")
            return None
        except Exception as e:
            log.warning("Qwen HTTP call failed: %s", e)
            return None

    async def _do_post(self, system: str, user: str) -> str:
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
        return data["choices"][0]["message"]["content"]


def _parse_triples(content: str) -> list[Triple] | None:
    """Parse JSON triples from Qwen response. Returns None if unparseable."""
    if content is None:
        return None

    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```\s*$", "", stripped)
        stripped = stripped.strip()

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        data = _extract_first_json_array(stripped)
        if data is None:
            return None

    if not isinstance(data, list):
        return None

    triples: list[Triple] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        s, p, o = item.get("subject"), item.get("predicate"), item.get("object")
        if isinstance(s, str) and isinstance(p, str) and isinstance(o, str):
            triples.append(Triple(s, p, o))
    return triples


def _extract_first_json_array(text: str):
    """Find the first balanced JSON array honoring string quoting."""
    start = text.find("[")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None
```

- [ ] **Step 4:** Run tests — expect all pass (~16 tests).
- [ ] **Step 5:** Commit:
  ```bash
  git add mempalace/walker/extractor/qwen_rel.py tests/walker/extractor/test_qwen_rel.py
  git commit -m "feat(walker): QwenRelExtractor via CircuitBreaker.call_async()"
  ```

---

## Task 5a: `ChromaBackend.iter_drawers()` helper

**Depends on:** nothing (can run in Group A)

**Files:**
- Modify: `mempalace/backends/chroma.py`
- Create: `tests/backends/test_chroma_iter_drawers.py`

- [ ] **Step 1:** Read current `ChromaBackend` class and identify the drawer collection name. Grep for `mempalace_` in `palace.py`, `miner.py`, `backends/chroma.py`. Note the exact collection name used when filing drawers (typically `mempalace_drawers` but verify — it may include the wing name or use a different convention).

- [ ] **Step 2: Write failing tests**

```python
"""Verify ChromaBackend.iter_drawers() against a real temp palace."""
from pathlib import Path
import pytest


@pytest.fixture
def tiny_palace(tmp_path):
    """Write 3 drawers directly via ChromaBackend, bypassing miner."""
    pytest.importorskip("chromadb")
    from mempalace.backends.chroma import ChromaBackend

    palace_path = tmp_path / "palace"
    palace_path.mkdir()
    backend = ChromaBackend()
    col = backend.get_or_create_collection(str(palace_path), "mempalace_drawers")
    col.add(
        ids=["d0", "d1", "d2"],
        documents=["Text zero about Alice.", "Text one about Bob.", "Text two about Carol."],
        metadatas=[{"wing": "w1"}, {"wing": "w1"}, {"wing": "w2"}],
    )
    return str(palace_path)


def test_iter_drawers_returns_all(tiny_palace):
    from mempalace.backends.chroma import ChromaBackend
    drawers = list(ChromaBackend().iter_drawers(tiny_palace))
    assert len(drawers) == 3
    ids = {d["id"] for d in drawers}
    assert ids == {"d0", "d1", "d2"}
    for d in drawers:
        assert "text" in d and d["text"].startswith("Text")


def test_iter_drawers_filters_by_wing(tiny_palace):
    from mempalace.backends.chroma import ChromaBackend
    w1 = list(ChromaBackend().iter_drawers(tiny_palace, wing="w1"))
    assert len(w1) == 2
    w_none = list(ChromaBackend().iter_drawers(tiny_palace, wing="nope"))
    assert w_none == []


def test_iter_drawers_empty_palace(tmp_path):
    pytest.importorskip("chromadb")
    from mempalace.backends.chroma import ChromaBackend
    empty = tmp_path / "empty"
    empty.mkdir()
    assert list(ChromaBackend().iter_drawers(str(empty))) == []
```

- [ ] **Step 3:** Run — expect `AttributeError`.

- [ ] **Step 4: Implement `iter_drawers()`**

Add to `mempalace/backends/chroma.py`:

```python
    def iter_drawers(
        self,
        palace_path: str,
        wing: str | None = None,
        batch_size: int = 500,
    ):
        """Yield {'id', 'text', 'metadata'} for every drawer.

        Filters by wing if given. Pages via limit/offset when supported.
        """
        try:
            col = self.get_collection(palace_path, "mempalace_drawers")
        except Exception:
            return
        try:
            total = col.count()
        except Exception:
            total = 0
        if total == 0:
            return

        offset = 0
        while offset < total:
            try:
                page = col.get(
                    limit=batch_size,
                    offset=offset,
                    include=["documents", "metadatas"],
                )
            except TypeError:
                page = col.get(include=["documents", "metadatas"])
                ids = page.get("ids", [])
                docs = page.get("documents", []) or [""] * len(ids)
                metas = page.get("metadatas", []) or [{}] * len(ids)
                for i, d, m in zip(ids, docs, metas):
                    if wing is not None and (m or {}).get("wing") != wing:
                        continue
                    yield {"id": i, "text": d, "metadata": m or {}}
                return

            ids = page.get("ids", [])
            docs = page.get("documents", []) or [""] * len(ids)
            metas = page.get("metadatas", []) or [{}] * len(ids)
            if not ids:
                break
            for i, d, m in zip(ids, docs, metas):
                if wing is not None and (m or {}).get("wing") != wing:
                    continue
                yield {"id": i, "text": d, "metadata": m or {}}
            offset += len(ids)
```

**Collection name caveat:** if the project uses a different collection name (e.g. `mempalace_{wing}_drawers`), adapt `get_collection(...)` accordingly. If drawers are split across multiple collections, iterate every collection whose name matches the pattern.

- [ ] **Step 5:** Run tests — expect 3 passed.
- [ ] **Step 6:** Commit:
  ```bash
  git add mempalace/backends/chroma.py tests/backends/test_chroma_iter_drawers.py
  git commit -m "feat(backends): ChromaBackend.iter_drawers() with wing filter + paging"
  ```

---

## Task 5: `pipeline.py` — async orchestrator

**Depends on:** Tasks 2, 3, 4

**Files:**
- Create: `mempalace/walker/extractor/pipeline.py`
- Create: `tests/walker/extractor/test_pipeline.py`

- [ ] **Step 1: Write failing tests**

```python
import json
from unittest.mock import MagicMock, AsyncMock
import pytest
from mempalace.knowledge_graph import KnowledgeGraph
from mempalace.walker.extractor.state import ExtractionState
from mempalace.walker.extractor.gliner_ner import Entity
from mempalace.walker.extractor.qwen_rel import Triple
from mempalace.walker.extractor.pipeline import extract_drawers


def _mock_gliner(per_drawer):
    g = MagicMock()
    g.extract_batch.return_value = per_drawer
    return g


def _mock_qwen(triples_sequence):
    q = AsyncMock()
    q.extract = AsyncMock(side_effect=triples_sequence)
    return q


async def test_empty_drawer_list(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    g = _mock_gliner([])
    q = _mock_qwen([])
    stats = await extract_drawers(drawers=[], kg=kg, state=state, gliner=g, qwen=q)
    assert stats.drawers_processed == 0
    g.extract_batch.assert_not_called()
    q.extract.assert_not_called()


async def test_single_drawer_full_pipeline(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    drawer = {"id": "d1", "text": "Alice works at DeepMind."}
    g = _mock_gliner([[Entity("Alice", "person", 0.9), Entity("DeepMind", "organization", 0.9)]])
    q = _mock_qwen([[Triple("Alice", "works_at", "DeepMind")]])

    stats = await extract_drawers(drawers=[drawer], kg=kg, state=state, gliner=g, qwen=q)

    assert stats.drawers_processed == 1
    assert stats.entities_found == 2
    assert stats.triples_inserted == 1
    assert state.is_extracted("d1", "v1.0")

    row = kg._conn().execute(
        "SELECT source, source_drawer_ids FROM triples"
    ).fetchone()
    assert row[0] == "extractor_v1.0"
    assert json.loads(row[1]) == ["d1"]

    row = kg._conn().execute(
        "SELECT triple_count, entity_count FROM extraction_state WHERE drawer_id='d1'"
    ).fetchone()
    assert row[0] == 1 and row[1] == 2


async def test_zero_entity_skips_qwen_marks_extracted(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    g = _mock_gliner([[]])
    q = _mock_qwen([])

    stats = await extract_drawers(
        drawers=[{"id": "d1", "text": "bland"}],
        kg=kg, state=state, gliner=g, qwen=q,
    )
    q.extract.assert_not_called()
    assert state.is_extracted("d1", "v1.0")
    assert stats.drawers_processed == 1
    assert stats.triples_inserted == 0


async def test_already_extracted_skipped(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    state.mark_extracted("d1", "v1.0", 0, 0)
    g = _mock_gliner([])
    q = _mock_qwen([])

    stats = await extract_drawers(
        drawers=[{"id": "d1", "text": "x"}],
        kg=kg, state=state, gliner=g, qwen=q,
    )
    assert stats.drawers_skipped == 1
    g.extract_batch.assert_not_called()
    q.extract.assert_not_called()


async def test_idempotent_run_twice(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    drawer = {"id": "d1", "text": "Alice works at DeepMind."}
    entities = [Entity("Alice", "person", 0.9), Entity("DeepMind", "organization", 0.9)]
    triples = [Triple("Alice", "works_at", "DeepMind")]

    for _ in range(2):
        await extract_drawers(
            drawers=[drawer], kg=kg, state=state,
            gliner=_mock_gliner([entities]),
            qwen=_mock_qwen([triples]),
        )

    live = kg._conn().execute(
        "SELECT COUNT(*) FROM triples WHERE valid_to IS NULL"
    ).fetchone()[0]
    assert live == 1


async def test_dry_run_prints_and_does_not_write(tmp_path, capsys):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    g = _mock_gliner([[Entity("Alice", "person", 0.9)]])
    q = _mock_qwen([[Triple("Alice", "works_at", "DeepMind")]])

    stats = await extract_drawers(
        drawers=[{"id": "d1", "text": "Alice."}],
        kg=kg, state=state, gliner=g, qwen=q, dry_run=True,
    )
    out = capsys.readouterr().out
    assert "[DRY]" in out and "d1" in out and "Alice" in out
    assert stats.drawers_processed == 1
    assert not state.is_extracted("d1", "v1.0")
    assert kg._conn().execute("SELECT COUNT(*) FROM triples").fetchone()[0] == 0


async def test_custom_version_propagates(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    g = _mock_gliner([[Entity("Alice", "person", 0.9)]])
    q = _mock_qwen([[Triple("Alice", "is_a", "person")]])

    await extract_drawers(
        drawers=[{"id": "d1", "text": "Alice."}],
        kg=kg, state=state, gliner=g, qwen=q,
        extractor_version="v2.5",
    )
    source = kg._conn().execute("SELECT source FROM triples").fetchone()[0]
    assert source == "extractor_v2.5"
    assert state.is_extracted("d1", "v2.5")
    assert not state.is_extracted("d1", "v1.0")
```

- [ ] **Step 2:** Run — expect ImportError.

- [ ] **Step 3: Implement `pipeline.py`**

```python
"""Async orchestrator: GLiNER batch -> Qwen per-drawer -> upsert_triple -> mark_extracted."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

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
    elapsed_secs: float = 0.0
    # Note: circuit_open_events intentionally omitted in Phase 1 — the
    # pipeline cannot observe breaker state from inside. Wire up in Phase 2.


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
    """Run the extraction pipeline over drawers. Per-drawer atomicity."""
    stats = ExtractionStats()
    start = time.monotonic()

    if not drawers:
        stats.elapsed_secs = time.monotonic() - start
        return stats

    drawer_by_id = {d["id"]: d for d in drawers}
    unextracted_ids = state.unextracted_ids(list(drawer_by_id.keys()), extractor_version)
    stats.drawers_skipped = len(drawers) - len(unextracted_ids)

    if not unextracted_ids:
        stats.elapsed_secs = time.monotonic() - start
        return stats

    unextracted = [drawer_by_id[i] for i in unextracted_ids]
    texts = [d["text"] for d in unextracted]

    loop = asyncio.get_running_loop()
    entities_per_drawer = await loop.run_in_executor(
        None, gliner.extract_batch, texts
    )

    stats_lock = asyncio.Lock()
    sem = asyncio.Semaphore(concurrency)

    async def process(drawer, entities):
        async with sem:
            await _process_single(
                drawer, entities, kg, state, qwen,
                extractor_version, dry_run, stats, stats_lock,
            )

    await asyncio.gather(*[
        process(d, ents) for d, ents in zip(unextracted, entities_per_drawer)
    ])

    stats.elapsed_secs = time.monotonic() - start
    return stats


async def _process_single(
    drawer, entities, kg, state, qwen,
    version, dry_run, stats, stats_lock,
):
    drawer_id = drawer["id"]
    text = drawer["text"]
    entity_count = len(entities)

    async with stats_lock:
        stats.entities_found += entity_count

    if entity_count == 0:
        async with stats_lock:
            stats.drawers_processed += 1
        if not dry_run:
            state.mark_extracted(drawer_id, version, triple_count=0, entity_count=0)
        return

    try:
        triples: list[Triple] = await qwen.extract(text, entities)
    except Exception as e:
        log.warning("Qwen extract failed for %s: %s", drawer_id, e)
        async with stats_lock:
            stats.qwen_failures += 1
        triples = []

    if dry_run:
        for t in triples:
            print(f"[DRY] {drawer_id}: {t.subject} -[{t.predicate}]-> {t.object}")
        async with stats_lock:
            stats.drawers_processed += 1
        return

    all_ok = True
    inserted_n = 0
    updated_n = 0
    source_tag = f"extractor_{version}"
    for t in triples:
        try:
            result = kg.upsert_triple(
                subject=t.subject,
                predicate=t.predicate,
                obj=t.object,
                source=source_tag,
                source_drawer_ids=[drawer_id],
            )
            if result.inserted:
                inserted_n += 1
            elif result.updated:
                updated_n += 1
        except Exception as e:
            log.error("upsert_triple failed on %s: %s", drawer_id, e)
            all_ok = False

    async with stats_lock:
        stats.triples_inserted += inserted_n
        stats.triples_updated += updated_n

    if all_ok:
        async with stats_lock:
            stats.drawers_processed += 1
        state.mark_extracted(
            drawer_id, version,
            triple_count=len(triples), entity_count=entity_count,
        )
    else:
        log.warning("Drawer %s had upsert failures — not marking extracted", drawer_id)
```

- [ ] **Step 4:** Run tests — expect 7 passed.
- [ ] **Step 5:** Commit:
  ```bash
  git add mempalace/walker/extractor/pipeline.py tests/walker/extractor/test_pipeline.py
  git commit -m "feat(walker): async extract_drawers with per-drawer atomicity"
  ```

---

## Task 6: `dream/reextract.py` — Dream Job A

**Depends on:** Tasks 5, 5a

**Files:**
- Create: `mempalace/dream/__init__.py` (empty)
- Create: `mempalace/dream/reextract.py`
- Create: `tests/dream/__init__.py` (empty)
- Create: `tests/dream/test_reextract.py`

- [ ] **Step 1: Write failing tests**

```python
from unittest.mock import MagicMock, AsyncMock
import pytest
from mempalace.knowledge_graph import KnowledgeGraph
from mempalace.walker.extractor.state import ExtractionState
from mempalace.walker.extractor.gliner_ner import Entity
from mempalace.walker.extractor.qwen_rel import Triple
from mempalace.dream.reextract import run_job_a, JobAResult


def _mock_gliner(per_drawer):
    g = MagicMock()
    g.extract_batch.return_value = per_drawer
    return g


def _mock_qwen(triples_seq):
    q = AsyncMock()
    q.extract = AsyncMock(side_effect=triples_seq)
    q.aclose = AsyncMock()
    return q


async def test_processes_unextracted(tmp_path, monkeypatch):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))

    monkeypatch.setattr(
        "mempalace.dream.reextract._load_drawers_from_palace",
        AsyncMock(return_value=[
            {"id": "d1", "text": "Alice."},
            {"id": "d2", "text": "Bob."},
        ]),
    )
    gliner = _mock_gliner([
        [Entity("Alice", "person", 0.9)],
        [Entity("Bob", "person", 0.9)],
    ])
    qwen = _mock_qwen([
        [Triple("Alice", "is_a", "person")],
        [Triple("Bob", "is_a", "person")],
    ])
    monkeypatch.setattr("mempalace.dream.reextract._build_gliner", lambda: gliner)
    monkeypatch.setattr("mempalace.dream.reextract._build_qwen", lambda url: qwen)

    result = await run_job_a(
        palace_path=str(tmp_path / "palace"),
        kg=kg, version="v1.0", batch_size=500,
    )
    assert isinstance(result, JobAResult)
    assert result.drawers_processed == 2
    assert result.batches == 1
    qwen.aclose.assert_called()


async def test_only_processes_stale_version(tmp_path, monkeypatch):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    state = ExtractionState(kg)
    state.mark_extracted("d1", "v1.0", 1, 1)

    monkeypatch.setattr(
        "mempalace.dream.reextract._load_drawers_from_palace",
        AsyncMock(return_value=[{"id": "d1", "text": "Alice."}]),
    )
    monkeypatch.setattr(
        "mempalace.dream.reextract._build_gliner",
        lambda: _mock_gliner([[Entity("Alice", "person", 0.9)]]),
    )
    monkeypatch.setattr(
        "mempalace.dream.reextract._build_qwen",
        lambda url: _mock_qwen([[]]),
    )

    result = await run_job_a(
        palace_path=str(tmp_path / "palace"), kg=kg, version="v2.0",
    )
    assert result.drawers_processed == 1  # re-processed at v2.0


async def test_batches(tmp_path, monkeypatch):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    fake = [{"id": f"d{i}", "text": f"t{i}"} for i in range(501)]

    gliner = MagicMock()
    gliner.extract_batch.side_effect = lambda texts: [[] for _ in texts]

    monkeypatch.setattr(
        "mempalace.dream.reextract._load_drawers_from_palace",
        AsyncMock(return_value=fake),
    )
    monkeypatch.setattr("mempalace.dream.reextract._build_gliner", lambda: gliner)
    monkeypatch.setattr("mempalace.dream.reextract._build_qwen", lambda url: _mock_qwen([]))

    result = await run_job_a(
        palace_path=str(tmp_path / "palace"), kg=kg,
        version="v1.0", batch_size=500,
    )
    assert result.drawers_processed == 501
    assert result.batches == 2


async def test_dry_run_propagates(tmp_path, monkeypatch):
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    monkeypatch.setattr(
        "mempalace.dream.reextract._load_drawers_from_palace",
        AsyncMock(return_value=[{"id": "d1", "text": "A."}]),
    )
    monkeypatch.setattr(
        "mempalace.dream.reextract._build_gliner",
        lambda: _mock_gliner([[Entity("A", "person", 0.9)]]),
    )
    monkeypatch.setattr(
        "mempalace.dream.reextract._build_qwen",
        lambda url: _mock_qwen([[Triple("A", "is_a", "person")]]),
    )

    await run_job_a(
        palace_path=str(tmp_path / "palace"), kg=kg, version="v1.0", dry_run=True,
    )
    assert kg._conn().execute("SELECT COUNT(*) FROM triples").fetchone()[0] == 0


async def test_verbatim_invariant_real_backend(tmp_path, monkeypatch):
    """Dream Job A must not mutate drawer content in the real ChromaBackend."""
    pytest.importorskip("chromadb")
    from mempalace.backends.chroma import ChromaBackend

    palace_path = tmp_path / "palace"
    palace_path.mkdir()
    backend = ChromaBackend()
    col = backend.get_or_create_collection(str(palace_path), "mempalace_drawers")
    originals = {
        "d1": "Alice works at DeepMind.",
        "d2": "Bob lives in London.",
    }
    col.add(
        ids=list(originals.keys()),
        documents=list(originals.values()),
        metadatas=[{"wing": "w"}, {"wing": "w"}],
    )

    kg = KnowledgeGraph(str(palace_path / "knowledge_graph.db"))
    monkeypatch.setattr(
        "mempalace.dream.reextract._build_gliner",
        lambda: _mock_gliner([
            [Entity("Alice", "person", 0.9)],
            [Entity("Bob", "person", 0.9)],
        ]),
    )
    monkeypatch.setattr(
        "mempalace.dream.reextract._build_qwen",
        lambda url: _mock_qwen([
            [Triple("Alice", "is_a", "person")],
            [Triple("Bob", "is_a", "person")],
        ]),
    )

    await run_job_a(palace_path=str(palace_path), kg=kg, version="v1.0")

    col2 = backend.get_collection(str(palace_path), "mempalace_drawers")
    result = col2.get(include=["documents"])
    assert col2.count() == 2
    for i, doc in zip(result["ids"], result["documents"]):
        assert doc == originals[i]
```

- [ ] **Step 2:** Run — expect ImportError.

- [ ] **Step 3: Implement `reextract.py`**

```python
"""Dream Job A — re-extract palace drawers not yet at `version`."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
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
    batches: int


async def run_job_a(
    palace_path: str,
    kg: KnowledgeGraph,
    version: str = "v1.0",
    batch_size: int = 500,
    wing: str | None = None,
    dry_run: bool = False,
    qwen_url: str = "http://localhost:43100",
) -> JobAResult:
    """Re-extract drawers not yet at version. Idempotent, batch-safe."""
    started_at = datetime.now(timezone.utc).isoformat()
    start = time.monotonic()

    drawers = await _load_drawers_from_palace(palace_path, wing)
    gliner = _build_gliner()
    qwen = _build_qwen(qwen_url)
    state = ExtractionState(kg)

    totals = ExtractionStats()
    batches_run = 0
    try:
        for i in range(0, len(drawers), batch_size):
            batch = drawers[i : i + batch_size]
            batches_run += 1
            stats = await extract_drawers(
                drawers=batch, kg=kg, state=state,
                gliner=gliner, qwen=qwen,
                extractor_version=version, dry_run=dry_run,
            )
            totals.drawers_processed += stats.drawers_processed
            totals.drawers_skipped += stats.drawers_skipped
            totals.entities_found += stats.entities_found
            totals.triples_inserted += stats.triples_inserted
            totals.triples_updated += stats.triples_updated
            totals.qwen_failures += stats.qwen_failures
    finally:
        try:
            await qwen.aclose()
        except Exception:
            pass

    result = JobAResult(
        job="A", version=version, started_at=started_at,
        elapsed_secs=time.monotonic() - start,
        drawers_processed=totals.drawers_processed,
        drawers_skipped=totals.drawers_skipped,
        triples_inserted=totals.triples_inserted,
        triples_updated=totals.triples_updated,
        qwen_failures=totals.qwen_failures,
        batches=batches_run,
    )
    _append_log(result)
    return result


def _append_log(result: JobAResult) -> None:
    try:
        DREAM_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DREAM_LOG_PATH, "a") as f:
            f.write(json.dumps(asdict(result)) + "\n")
    except Exception as e:
        log.warning("Failed to write dream log: %s", e)


async def _load_drawers_from_palace(palace_path: str, wing: str | None) -> list[dict]:
    """Seam for tests — real impl uses ChromaBackend.iter_drawers()."""
    from mempalace.backends.chroma import ChromaBackend
    backend = ChromaBackend()
    return [
        {"id": d["id"], "text": d["text"]}
        for d in backend.iter_drawers(palace_path, wing=wing)
    ]


def _build_gliner() -> GlinerNER:
    return GlinerNER()


def _build_qwen(url: str) -> QwenRelExtractor:
    return QwenRelExtractor(base_url=url)
```

- [ ] **Step 4:** Run tests — expect 5 passed (last one auto-skips if chromadb missing).
- [ ] **Step 5:** Commit:
  ```bash
  git add mempalace/dream/__init__.py mempalace/dream/reextract.py \
          tests/dream/__init__.py tests/dream/test_reextract.py
  git commit -m "feat(dream): Job A with real-backend verbatim invariant test"
  ```

---

## Task 7: `walker extract` CLI subcommand

**Depends on:** Task 6

**Files:**
- Modify: `mempalace/cli.py`
- Create: `tests/test_cli_walker_extract.py`

- [ ] **Step 1: Write failing tests**

```python
import pytest
from mempalace.cli import main
from mempalace.dream.reextract import JobAResult


def _fake_result(version="v1.0"):
    return JobAResult(
        job="A", version=version, started_at="now",
        elapsed_secs=0.1, drawers_processed=0, drawers_skipped=0,
        triples_inserted=0, triples_updated=0, qwen_failures=0,
        batches=0,
    )


def test_walker_extract_help(capsys):
    with pytest.raises(SystemExit):
        main(["walker", "extract", "--help"])
    out = capsys.readouterr().out
    for flag in ("--wing", "--concurrency", "--version", "--dry-run", "--qwen-url"):
        assert flag in out


def test_walker_extract_dispatches(monkeypatch, capsys):
    captured = {}

    async def fake_run(**kwargs):
        captured.update(kwargs)
        return _fake_result(version=kwargs.get("version", "v1.0"))

    monkeypatch.setattr("mempalace.dream.reextract.run_job_a", fake_run)
    rc = main([
        "--palace", "/tmp/p",
        "walker", "extract",
        "--version", "v1.5",
        "--wing", "mywing",
        "--qwen-url", "http://example:1234",
    ])
    assert rc == 0
    assert captured["version"] == "v1.5"
    assert captured["wing"] == "mywing"
    assert captured["qwen_url"] == "http://example:1234"
    assert captured["palace_path"] == "/tmp/p"
    assert "Extracted" in capsys.readouterr().out


def test_walker_extract_dry_run_propagates(monkeypatch):
    captured = {}

    async def fake_run(**kwargs):
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr("mempalace.dream.reextract.run_job_a", fake_run)
    main(["walker", "extract", "--dry-run"])
    assert captured["dry_run"] is True


def test_walker_extract_preflight_error_friendly(monkeypatch, capsys):
    async def boom(**kwargs):
        raise RuntimeError("Qwen endpoint http://localhost:43100 unreachable")

    monkeypatch.setattr("mempalace.dream.reextract.run_job_a", boom)
    rc = main(["walker", "extract"])
    assert rc != 0
    out = capsys.readouterr().out
    assert "unreachable" in out or "Qwen" in out
```

- [ ] **Step 2:** Run — expect FAIL.

- [ ] **Step 3: Extend `cli.py`**

Inside `main()`, add these flags to the existing `walker_sub` parser (after `walker_sub.add_parser("status", ...)`):

```python
p_extract = walker_sub.add_parser(
    "extract", help="Extract entities + triples from palace drawers"
)
p_extract.add_argument("--wing", default=None)
p_extract.add_argument("--concurrency", type=int, default=4)
p_extract.add_argument("--version", default="v1.0")
p_extract.add_argument("--gliner-threshold", type=float, default=0.4)
p_extract.add_argument("--dry-run", action="store_true")
p_extract.add_argument("--qwen-url", default="http://localhost:43100")
p_extract.add_argument("--batch-size", type=int, default=500)
```

Update `walker_dispatch` in `cmd_walker`:
```python
walker_dispatch = {
    "init": cmd_walker_init,
    "status": cmd_walker_status,
    "extract": cmd_walker_extract,
}
```

Add the shared helper + handler:

```python
def _resolve_palace_and_kg(args):
    from pathlib import Path
    from mempalace.knowledge_graph import KnowledgeGraph
    palace_path = args.palace or str(Path.home() / ".mempalace" / "palace")
    kg_path = str(Path(palace_path) / "knowledge_graph.db")
    return palace_path, KnowledgeGraph(kg_path)


def cmd_walker_extract(args):
    import asyncio
    import logging
    logging.basicConfig(level=logging.INFO)
    from mempalace.dream import reextract as _reextract

    palace_path, kg = _resolve_palace_and_kg(args)
    try:
        result = asyncio.run(_reextract.run_job_a(
            palace_path=palace_path,
            kg=kg,
            version=args.version,
            wing=args.wing,
            dry_run=args.dry_run,
            qwen_url=args.qwen_url,
            batch_size=args.batch_size,
        ))
    except RuntimeError as e:
        print(f"Error: {e}")
        print(f"Hint: start Qwen at {args.qwen_url} or pass --qwen-url <url>")
        return 2

    print(f"Extracted: {result.drawers_processed} processed, "
          f"{result.drawers_skipped} skipped")
    print(f"Triples: {result.triples_inserted} inserted, "
          f"{result.triples_updated} updated")
    print(f"Elapsed: {result.elapsed_secs:.1f}s ({result.batches} batches)")
    return 0
```

**Note on monkeypatching:** The test monkeypatches `mempalace.dream.reextract.run_job_a`. For the monkeypatch to affect `cmd_walker_extract`, the handler must reference `_reextract.run_job_a` via the module (as shown above) — NOT import it directly (`from mempalace.dream.reextract import run_job_a` would capture the original function).

- [ ] **Step 4:** Run tests — expect 4 passed.
- [ ] **Step 5:** Commit:
  ```bash
  git add mempalace/cli.py tests/test_cli_walker_extract.py
  git commit -m "feat(cli): walker extract with --qwen-url, --dry-run, friendly errors"
  ```

---

## Task 8: `dream-cycle --jobs A` CLI subcommand

**Depends on:** Task 6, Task 7 (uses `_resolve_palace_and_kg`)

**Files:**
- Modify: `mempalace/cli.py`
- Modify: `tests/test_cli_walker_extract.py` (append)

- [ ] **Step 1: Append failing tests**

```python
def test_dream_cycle_help(capsys):
    with pytest.raises(SystemExit):
        main(["dream-cycle", "--help"])
    out = capsys.readouterr().out
    for flag in ("--jobs", "--wing", "--dry-run"):
        assert flag in out


def test_dream_cycle_jobs_a(monkeypatch):
    captured = {}

    async def fake_run(**kwargs):
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr("mempalace.dream.reextract.run_job_a", fake_run)
    rc = main(["dream-cycle", "--jobs", "A", "--wing", "mywing", "--dry-run"])
    assert rc == 0
    assert captured["wing"] == "mywing"
    assert captured["dry_run"] is True


def test_dream_cycle_unsupported_jobs(capsys):
    rc = main(["dream-cycle", "--jobs", "B"])
    assert rc == 2
    assert "Phase 1" in capsys.readouterr().out
```

- [ ] **Step 2: Add `dream-cycle` parser + handler**

In `main()`:

```python
p_dream = sub.add_parser("dream-cycle", help="Run Dream Cycle jobs")
p_dream.add_argument("--jobs", default="A")
p_dream.add_argument("--version", default="v1.0")
p_dream.add_argument("--batch-size", type=int, default=500)
p_dream.add_argument("--wing", default=None)
p_dream.add_argument("--dry-run", action="store_true")
p_dream.add_argument("--qwen-url", default="http://localhost:43100")
```

Add to `dispatch`:
```python
"dream-cycle": cmd_dream_cycle,
```

Handler:

```python
def cmd_dream_cycle(args):
    import asyncio
    import logging
    logging.basicConfig(level=logging.INFO)
    from mempalace.dream import reextract as _reextract

    jobs = [j.strip() for j in args.jobs.split(",")]
    if jobs != ["A"]:
        print(f"Phase 1 only supports --jobs A; got {args.jobs}")
        return 2

    palace_path, kg = _resolve_palace_and_kg(args)
    try:
        result = asyncio.run(_reextract.run_job_a(
            palace_path=palace_path, kg=kg,
            version=args.version, batch_size=args.batch_size,
            wing=args.wing, dry_run=args.dry_run, qwen_url=args.qwen_url,
        ))
    except RuntimeError as e:
        print(f"Error: {e}")
        return 2

    print(f"Dream Job A: {result.drawers_processed} processed in "
          f"{result.batches} batches, {result.elapsed_secs:.1f}s")
    return 0
```

- [ ] **Step 3:** Run tests — expect pass.
- [ ] **Step 4:** Commit:
  ```bash
  git add mempalace/cli.py tests/test_cli_walker_extract.py
  git commit -m "feat(cli): dream-cycle --jobs A with shared palace helper"
  ```

---

## Task 9: Extend `status --walker` with extraction stats

**Depends on:** Task 2, Task 6

**Files:**
- Modify: `mempalace/cli.py` (walker status branch)
- Modify: `tests/test_cli_walker.py`

- [ ] **Step 1: Append failing tests**

```python
def test_status_walker_reports_latest_version_dynamically(tmp_path):
    from mempalace.cli import main
    from mempalace.knowledge_graph import KnowledgeGraph
    from mempalace.walker.extractor.state import ExtractionState

    palace = tmp_path / "palace"
    palace.mkdir()
    kg = KnowledgeGraph(str(palace / "knowledge_graph.db"))
    state = ExtractionState(kg)
    state.mark_extracted("d1", "v1.0", 3, 5)
    state.mark_extracted("d2", "v2.0", 4, 6)  # newer

    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["--palace", str(palace), "status", "--walker"])
    out = buf.getvalue()
    assert "Extracted" in out
    assert "v2.0" in out


def test_status_walker_no_extraction(tmp_path):
    from mempalace.cli import main

    palace = tmp_path / "palace"
    palace.mkdir()
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["--palace", str(palace), "status", "--walker"])
    # Must not crash
```

- [ ] **Step 2:** Run — expect FAIL.

- [ ] **Step 3: Extend `cmd_status` walker block**

In the existing `--walker` branch of `cmd_status`, after the existing walker_ready flag reporting, add:

```python
try:
    from pathlib import Path as _Path
    from mempalace.knowledge_graph import KnowledgeGraph
    palace_dir = _Path(args.palace or (_Path.home() / ".mempalace" / "palace"))
    kg_path = palace_dir / "knowledge_graph.db"
    if kg_path.exists():
        kg = KnowledgeGraph(str(kg_path))
        row = kg._conn().execute(
            """
            SELECT extractor_version, COUNT(*), SUM(triple_count),
                   SUM(entity_count), MAX(extracted_at)
            FROM extraction_state
            GROUP BY extractor_version
            ORDER BY MAX(extracted_at) DESC
            LIMIT 1
            """
        ).fetchone()
        if row:
            version, n, triples, entities, last_run = row
            print(f"KG triples:     {triples or 0} ({entities or 0} entities)")
            print(f"Extracted:      {n} drawers ({version}) — last run {last_run}")
        else:
            print("Extracted:      0 drawers")
except Exception as e:
    print(f"Extraction stats unavailable: {e}")
```

- [ ] **Step 4:** Run tests — expect pass.
- [ ] **Step 5:** Commit:
  ```bash
  git add mempalace/cli.py tests/test_cli_walker.py
  git commit -m "feat(cli): status --walker reads latest extractor_version dynamically"
  ```

---

## Task 10: Full test suite + coverage + ruff

**Depends on:** Tasks 1–9

- [ ] **Step 1:** `python -m pytest tests/ --ignore=tests/benchmarks -q` — expect all pass.
- [ ] **Step 2:** Coverage:
  ```bash
  python -m pytest tests/walker/extractor tests/dream tests/infra/test_circuit_breaker_async.py \
    --cov=mempalace/walker/extractor --cov=mempalace/dream \
    --cov-report=term-missing
  ```
  Expected: coverage ≥ 85%.
- [ ] **Step 3:** Ruff: `ruff check mempalace/walker/extractor mempalace/dream tests/walker/extractor tests/dream tests/infra/test_circuit_breaker_async.py` — apply `--fix` if safe.
- [ ] **Step 4:** Format: `ruff format mempalace/walker/extractor mempalace/dream tests/walker/extractor tests/dream`.
- [ ] **Step 5:** Commit formatting if any: `git diff --quiet || git commit -am "style: ruff format Phase 1 modules"`.

---

## Task 11: End-to-end smoke test on a real palace

**Depends on:** Task 10

**Prerequisites:** Qwen3.5 35B running at `http://localhost:43100`.

- [ ] **Step 1:** Mine a small palace:
  ```bash
  python -m mempalace.cli --palace /tmp/test-palace mine . --wing mempalace --limit 20
  ```
- [ ] **Step 2:** Dry run:
  ```bash
  python -m mempalace.cli --palace /tmp/test-palace walker extract --dry-run
  ```
  Expected: triples printed, nothing written.
- [ ] **Step 3:** Real run + timing:
  ```bash
  time python -m mempalace.cli --palace /tmp/test-palace walker extract --version v1.0
  ```
- [ ] **Step 4:** Verify KG:
  ```bash
  python -c "
  from mempalace.knowledge_graph import KnowledgeGraph
  kg = KnowledgeGraph('/tmp/test-palace/knowledge_graph.db')
  n = kg._conn().execute('SELECT COUNT(*) FROM triples WHERE valid_to IS NULL').fetchone()[0]
  print(f'live triples: {n}')
  "
  ```
- [ ] **Step 5:** Idempotent re-run:
  ```bash
  python -m mempalace.cli --palace /tmp/test-palace walker extract --version v1.0
  ```
  Expected: skipped count == drawer count, 0 new triples.
- [ ] **Step 6:** Median/mean triples per drawer:
  ```bash
  python -c "
  import statistics
  from mempalace.knowledge_graph import KnowledgeGraph
  kg = KnowledgeGraph('/tmp/test-palace/knowledge_graph.db')
  counts = [r[0] for r in kg._conn().execute(
      'SELECT triple_count FROM extraction_state WHERE extractor_version=\"v1.0\"'
  ).fetchall()]
  print(f'drawers: {len(counts)}')
  print(f'median: {statistics.median(counts)}')
  print(f'mean: {statistics.mean(counts):.1f}')
  "
  ```
- [ ] **Step 7:** Throughput from dream log:
  ```bash
  python -c "
  import json
  from pathlib import Path
  logs = [json.loads(l) for l in open(Path.home() / '.mempalace' / 'dream_log.jsonl')]
  last = logs[-1]
  print(f'drawers: {last[\"drawers_processed\"]}, elapsed: {last[\"elapsed_secs\"]:.1f}s, throughput: {last[\"drawers_processed\"]/last[\"elapsed_secs\"]:.2f} drawers/s')
  "
  ```
- [ ] **Step 8:** Document results in `docs/superpowers/plans/phase-1-smoke-results.md` and commit.

---

## Phase 1 Go/No-Go Gates Summary

| # | Gate | Target | Verified in |
|---|------|--------|-------------|
| 1 | Median triples/drawer | ≥ 2 | Task 11 Step 6 |
| 2 | Mean triples/drawer | ≥ 3 | Task 11 Step 6 |
| 3 | Throughput | > 3 drawers/sec on A5000 | Task 11 Step 7 |
| 4 | Dream Job A on 5k drawers | < 30 min | Optional (needs 5k-drawer palace) |
| 5 | Dream Job A idempotent | same KG state on rerun | Task 5 tests + Task 11 Step 5 |
| 6 | Verbatim invariant | drawer content unchanged | Task 6 real-backend test |
| 7 | LongMemEval R@5 | ±0.5pp baseline | Skip if dataset absent |
| 8 | Coverage | ≥ 85% on new modules | Task 10 Step 2 |

---

## Completion Checklist

- [ ] All tasks completed with commits in dependency-group order (A → G)
- [ ] Full test suite passing
- [ ] Coverage ≥ 85% on new modules
- [ ] Ruff clean
- [ ] Smoke test on real palace documented
- [ ] Gates 1–3, 5, 6, 8 all PASS (Gates 4, 7 may be waived)
- [ ] Branch ready to merge into `feat/mempalace-walk-phase-0` (or develop once Phase 0 lands)

**Do NOT open a PR to `MemPalace/mempalace` without first opening a GitHub issue per CONTRIBUTING.md — discussion before code.**
