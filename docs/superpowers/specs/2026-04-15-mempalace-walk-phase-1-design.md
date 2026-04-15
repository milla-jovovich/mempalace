# MemPalace Walk — Phase 1: Extractor v1 + Dream Job A

**Date:** 2026-04-15
**Status:** Approved
**Depends on:** Phase 0 (`feat/mempalace-walk-phase-0`) — KG schema, CircuitBreaker, GPU detection

---

## Executive Summary

Phase 1 builds the extraction pipeline that populates the knowledge graph from palace drawers. After Phase 1, running `mempalace walker extract` over an existing palace will produce a dense entity-relationship graph (target: median ≥ 2 triples/drawer, up from ~0.3). No query-time behavior changes — the KG gets richer, retrieval improvements land in Phase 2.

Two-model pipeline:
- **GLiNER** (in-process, `urchade/gliner_multi-v2.1`) — entity + type detection, batched at 33k texts/s
- **Qwen3.5 35B** (HTTP → `localhost:43100`, OpenAI-compatible) — relationship extraction given entities + text, 4 concurrent requests

`mempalace mine` is untouched. Extraction is a separate pass (`walker extract`) so mining stays fast.

---

## 1. Principles (inherited, non-negotiable)

- **Verbatim always** — extraction reads drawer text, never writes to it. Drawers are immutable.
- **Local-first** — Qwen runs on `localhost:43100`, no cloud calls.
- **Incremental only** — extraction state tracked per drawer; re-running is safe and idempotent.
- **Background everything** — `walker extract` and `dream-cycle` are explicit user commands, not inline with mine.

---

## 2. Package Layout

```
mempalace/walker/
└── extractor/
    ├── __init__.py
    ├── gliner_ner.py       # GLiNER wrapper — entity + type detection
    ├── qwen_rel.py         # Qwen HTTP client — relationship extraction
    ├── pipeline.py         # Orchestrates GLiNER → Qwen → upsert_triple
    └── state.py            # Tracks extracted drawers in SQLite

mempalace/dream/
├── __init__.py
└── reextract.py            # Dream Job A — re-extracts stale drawers

mempalace/cli.py            # adds walker extract + dream-cycle --jobs A
```

All new code lives under `mempalace/walker/extractor/` and `mempalace/dream/`. No existing files modified except `cli.py` (additive).

---

## 3. Data Flow

```
mempalace mine (unchanged)
      ↓ files drawers into ChromaDB palace

mempalace walker extract
      ↓ reads unextracted drawers from ChromaDB
GLiNER batch (in-process, batch_size=32)
      ↓ entities + types per drawer
Qwen3.5 35B HTTP (localhost:43100, concurrency=4)
      ↓ JSON triples [{subject, predicate, object}]
upsert_triple() → knowledge_graph.db
      ↓
extraction_state table — marks drawer extracted
```

---

## 4. Component Design

### 4.1 `gliner_ner.py`

Loaded once per `walker extract` run, reused across all drawers.

```python
ENTITY_TYPES = [
    "person", "organization", "location",
    "date", "project", "technology", "event",
]

@dataclass
class Entity:
    text: str
    type: str
    score: float

class GlinerNER:
    def __init__(self, model: str = "urchade/gliner_multi-v2.1", device: str | None = None):
        # device=None → calls _select_device() → "cuda" if GPU available, else "cpu"
        _device = device or GlinerNER._select_device()
        # load GLiNER model on _device
        ...

    def extract_batch(self, texts: list[str], threshold: float = 0.4) -> list[list[Entity]]:
        """Returns one Entity list per input text. batch_size=32."""

    @staticmethod
    def _select_device() -> str:
        """Calls detect_hardware() from walker.gpu_detect; returns 'cuda' if tier != CPU_ONLY, else 'cpu'."""
```

Threshold 0.4 balances recall vs noise — tunable via CLI flag `--gliner-threshold`.

### 4.2 `qwen_rel.py`

Thin async HTTP client. No model loading — calls the already-running Qwen3.5 35B endpoint.

`CircuitBreaker` is imported from `mempalace.infra.circuit_breaker` (Phase 0 — `mempalace/infra/circuit_breaker.py`). Interface: `CircuitBreaker(name: str, failure_threshold: int, recovery_timeout_secs: float)` with a `.call(fn)` method. No third-party dependency needed.

```python
SYSTEM_PROMPT = """Extract relationships as JSON triples from the text.
Return ONLY a JSON array: [{"subject": "...", "predicate": "...", "object": "..."}]
Use only entities from the provided list. Predicates must be snake_case verbs.
Return [] if no clear relationships exist. No explanation, no markdown."""

@dataclass
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
    ):
        # Verify endpoint reachable at construction time (GET /v1/models).
        # Raise RuntimeError with clear message if unreachable — fail fast before any extraction.
        self._cb = CircuitBreaker("qwen_rel", failure_threshold=3, recovery_timeout_secs=30.0)
        ...

    async def extract(self, text: str, entities: list[Entity]) -> list[Triple]:
        """POST /v1/chat/completions. Retry once on JSON parse failure.
        Returns [] immediately if entities is empty (no point calling Qwen).
        Returns [] if circuit open or Qwen returns no valid triples."""
```

**Failure modes:**
- Parse failure → retry once with a stricter prompt ("return ONLY valid JSON, no other text")
- Second failure → log warning, return `[]` for that drawer
- 3 consecutive failures → CircuitBreaker opens → remaining batch skips Qwen, GLiNER entities still written as entity-only nodes

### 4.3 `state.py`

SQLite table in `knowledge_graph.db` (same file, separate table — no new file).

**Lock coordination:** `ExtractionState` is initialized with the same `KnowledgeGraph` instance and calls `kg._conn()` to reuse the same SQLite connection. Since `knowledge_graph.db` uses WAL mode (set in `_init_db`), concurrent reads and writes are safe at the SQLite level. `mark_extracted()` does NOT acquire `_write_lock` — it is a lightweight INSERT/REPLACE on a separate table and does not need to serialize with triple writes. If this assumption causes `OperationalError: database is locked` in practice, the fix is to give `ExtractionState` its own `threading.Lock`.

```sql
CREATE TABLE IF NOT EXISTS extraction_state (
    drawer_id        TEXT PRIMARY KEY,
    extractor_version TEXT NOT NULL,
    extracted_at     TEXT DEFAULT CURRENT_TIMESTAMP,
    triple_count     INTEGER DEFAULT 0,
    entity_count     INTEGER DEFAULT 0
);
```

```python
class ExtractionState:
    def is_extracted(self, drawer_id: str, version: str) -> bool: ...
    def mark_extracted(self, drawer_id: str, version: str,
                       triple_count: int, entity_count: int) -> None: ...
    def unextracted_ids(self, all_ids: list[str], version: str) -> list[str]: ...
```

### 4.4 `pipeline.py`

Async orchestrator. GLiNER is synchronous (runs in thread pool), Qwen calls use `asyncio.gather` with a semaphore.

```python
@dataclass
class ExtractionStats:
    drawers_processed: int
    drawers_skipped: int
    entities_found: int
    triples_inserted: int
    triples_updated: int
    qwen_failures: int
    circuit_open_events: int
    elapsed_secs: float

async def extract_drawers(
    drawers: list[dict],
    kg: KnowledgeGraph,
    state: ExtractionState,
    gliner: GlinerNER,
    qwen: QwenRelExtractor,
    extractor_version: str = "v1.0",
    dry_run: bool = False,
) -> ExtractionStats:
    # dry_run=True: run GLiNER + Qwen, print triples, skip upsert_triple and mark_extracted
    # 1. Filter already-extracted drawers
    # 2. GLiNER over full unextracted batch (sync, in thread pool)
    # 3. For each drawer (asyncio.gather with semaphore(concurrency)):
    #      a. If 0 entities from GLiNER → skip Qwen, call mark_extracted(triple_count=0)
    #      b. Else call Qwen, collect triples
    #      c. upsert_triple() for each valid triple (source_drawer_ids=[drawer_id])
    #      d. If ALL upserts succeed → mark_extracted() for this drawer
    #         If any upsert fails → log error, do NOT mark_extracted (drawer retried next run)
    # Note: mark_extracted() is per-drawer, called inside the per-drawer loop,
    # not once at the end of the batch. This ensures partial batch failures
    # leave unprocessed drawers eligible for retry.
```

`source_drawer_ids` is populated on every `upsert_triple` call, so each triple is traceable back to its source drawers.

### 4.5 `dream/reextract.py` — Dream Job A

Same pipeline as `extract_drawers` but targets drawers where `extractor_version != current_version`. Processes in batches of 500 (memory-safe on large palaces). Appends a structured JSON summary to `~/.mempalace/dream_log.jsonl`:

```json
{"job": "A", "version": "v1.0", "started_at": "...", "elapsed_secs": 142.3,
 "drawers_processed": 5000, "drawers_skipped": 1200, "triples_inserted": 9841,
 "triples_updated": 2103, "qwen_failures": 4, "circuit_open_events": 0}
```

```python
async def run_job_a(palace_path: str, version: str = "v1.0", batch_size: int = 500) -> JobAResult:
    """Re-extract all drawers not yet at `version`. Idempotent.
    Async — the dream-cycle CLI entry point calls asyncio.run(run_job_a(...)).
    Safe to interrupt: drawers are marked extracted per-drawer inside extract_drawers().
    An interrupted run leaves already-extracted drawers marked; re-run skips them."""
```

---

## 5. CLI

### `mempalace walker extract`

```
mempalace walker extract [--palace PATH] [--wing WING] [--concurrency N]
                         [--version V] [--gliner-threshold F] [--dry-run]

  --wing              Limit to one wing (default: all); error if wing not found
  --concurrency       Qwen parallel requests (default: 4)
  --version           extractor_version tag (default: "v1.0")
  --gliner-threshold  Entity detection threshold (default: 0.4)
  --dry-run           Run pipeline, print triples, write nothing
```

`--dry-run` threads as `dry_run=True` into `extract_drawers()`: GLiNER and Qwen run normally, triples printed to stdout, no writes to KG or state table.

Example output:
```
Extracting 542 drawers (wing: all, version: v1.0)
  GLiNER:  542 drawers → 3,241 entities  [2.1s]
  Qwen:    542 drawers → 1,847 triples   [4m 12s, 4 concurrent]
  KG:      1,847 upserted (1,203 new, 644 updated)
  Skipped: 0 already extracted
Done. Run `mempalace status --walker` to see KG stats.
```

### `mempalace dream-cycle --jobs A`

```
mempalace dream-cycle --jobs A [--palace PATH] [--batch-size N] [--version V]
```

### `mempalace status --walker` additions

```
KG triples:     1,847 (1,203 entities)
Extracted:      542/542 drawers (v1.0) — last run 2026-04-15 03:00
Qwen endpoint:  http://localhost:43100 — reachable
```

"Last run" timestamp = `MAX(extracted_at)` across all rows in `extraction_state` for the current version.

---

## 6. Error Handling

| Failure | Behavior |
|---------|----------|
| GLiNER OOM | Reduce batch size by half, retry; log warning |
| Qwen JSON parse error | Retry once with stricter prompt |
| Qwen timeout (>30s) | Count as failure toward CircuitBreaker |
| CircuitBreaker OPEN | Skip Qwen for remaining batch; GLiNER entities still written |
| Qwen endpoint unreachable at start | Abort with clear error message before any extraction |
| Drawer text empty | Skip silently |
| `upsert_triple` failure | Log + continue; don't mark drawer as extracted |

---

## 7. Testing Strategy

### Unit tests (`tests/walker/test_extractor_*.py`)

**`test_gliner_ner.py`**
- Entity extraction on 10 fixture texts; assert known entities detected
- Batch returns same count as inputs (no dropped texts)
- Threshold filtering works

**`test_qwen_rel.py`**
- Mock HTTP server: valid JSON → parsed correctly
- Mock HTTP server: invalid JSON → retry fires → returns `[]` on second failure
- CircuitBreaker trips after 3 consecutive failures
- Empty entity list → Qwen not called (no point sending empty context)
- Endpoint unreachable at construction → RuntimeError raised before extraction begins

**`test_pipeline.py`**
- End-to-end with mocked GLiNER + mocked Qwen
- `extraction_state` written per-drawer (not per-batch)
- Drawer NOT marked extracted when any `upsert_triple` fails
- `upsert_triple` called correct number of times
- Idempotent: run twice → same KG state, no duplicate triples
- `source_drawer_ids` populated on triples
- Zero-entity drawer: Qwen not called, drawer still marked extracted

**`test_reextract.py`**
- Dream Job A only processes drawers at stale version
- Verbatim invariant: drawer text content unchanged after extraction
- Batch boundary: 501 drawers processes in 2 batches

### Coverage gate: ≥ 85%

---

## 8. Phase 1 Go/No-Go Gates

| # | Gate | Target |
|---|------|--------|
| 1 | Median triples/drawer | ≥ 2 (baseline ~0.3) |
| 2 | Avg triples/drawer | ≥ 3 |
| 3 | Extractor throughput (total_drawers / elapsed_secs) | > 3 drawers/sec on A5000 (≈ 300ms/drawer avg) |
| 4 | Dream Job A on 5k drawers | < 30 min on A5000 |
| 5 | Dream Job A idempotent | run twice → same KG state |
| 6 | Verbatim invariant | dream cycle never mutates drawer content |
| 7 | Existing LongMemEval R@5 | unchanged ±0.5pp |
| 8 | Extractor test coverage | ≥ 85% |

---

## 9. Explicit Non-Goals (Phase 1)

- No changes to `mempalace mine` pipeline
- No query-time retrieval changes (Phase 2)
- No `lm-format-enforcer` constrained decoding
- No nightly scheduler / cron (Phase 4)
- No MuSiQue benchmark (Phase 2)
- No LLM walker (Phase 3)

---

## 10. Dependencies

No new runtime dependencies beyond what Phase 0 added in `[walker]`:

```toml
[walker]
gliner>=0.2.0
vllm>=0.6.0       # not used in Phase 1 — Qwen runs externally
scipy>=1.11.0
networkx>=3.0
httpx>=0.27.0     # async HTTP client for Qwen calls (explicit, not relying on ChromaDB transitive)
```

`httpx` is currently a transitive dep of ChromaDB but is added explicitly here since it is a first-class dependency of this feature and must not break if ChromaDB drops it in a future release.
