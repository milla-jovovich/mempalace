---
title: "Phase 0 — Fix the Foundation"
summary: "Fix broken fundamentals before building new features: KG correctness, storage ceilings, embedding constraints, missing resilience features, and Python implementation defects."
read_when:
  - Planning Phase 0 work
  - Deciding what to fix next
  - Understanding current defects and their scope
status: active
last_updated: "2026-04-11"
---

# Phase 0 — Fix the Foundation

> Fix what's broken before building what's new. None of the active KG features are reliable without this.

---

## Goal

Eliminate correctness bugs, silent failure modes, and performance anti-patterns that undermine every higher phase. Phase 0 is not about new features — it is about making the existing system trustworthy.

---

## Knowledge Graph Correctness

| # | Task | File | Effort | Why |
|---|---|---|---|---|
| 0.1 | Persistent connection + `threading.Lock` + `sqlite3.Row` factory | `knowledge_graph.py` | 2h | One connection per call costs ~1-2ms overhead; row index magic numbers break on schema change |
| 0.2 | SHA-256 entity IDs | `knowledge_graph.py:_entity_id` | 1h | `"John O'Brien"` and `"John OBrien"` silently collide to `"johnobrien"` |
| 0.3 | Partial indexes (`WHERE valid_to IS NULL`, `(subject, predicate)` composite) | `knowledge_graph.py` | 1h | Temporal OR-NULL pattern blocks index use on the hot query path |
| 0.4 | Atomic SQL expressions for all weight updates | `knowledge_graph.py` | 1h | Prerequisite for Hebbian decay — no read-modify-write ever |

**Exit criteria**: `query_entity()` uses named columns, no collisions in entity IDs, temporal queries hit the index.

---

## Dependency Hygiene

| # | Task | File | Effort | Why |
|---|---|---|---|---|
| ~~0.0~~ | ~~Upgrade ChromaDB `0.6.3` → `1.x`~~ | `pyproject.toml` | ✅ | Upgraded to `>=1.0,<2` (now 1.5.7). API unchanged — zero code edits needed. 117 tests pass, zero warnings. |

**Exit criteria**: ✅ `chromadb>=1.0` in `pyproject.toml`; ✅ zero ChromaDB warnings; ✅ `filterwarnings` suppressions removed.

---

## Storage Ceilings

| # | Task | File | Effort | Why |
|---|---|---|---|---|
| 0.5 | Multi-collection partitioning for ChromaDB | `searcher.py` | 3h | Single `mempalace_drawers` collection has no sharding; hitting ceiling requires destructive manual fork |
| 0.6 | SQLite compaction — automate `VACUUM` | `knowledge_graph.py` | 1h | Deleted triples leave gaps; DB file never shrinks without explicit `VACUUM`; add a `compact()` maintenance method |

**Exit criteria**: ChromaDB supports at least 2 named partitions; `compact()` reduces DB size after bulk deletes.

---

## Embedding Model Constraints

| # | Task | File | Effort | Why |
|---|---|---|---|---|
| 0.7 | Add GPU path for embedding inference | `searcher.py` / config | 2h | Default `all-MiniLM-L6-v2` is CPU-only; on GPU-capable machines this is the dominant query latency source (~50-100ms per query) |

**Exit criteria**: When CUDA or MPS device is detected, embedding inference uses it; throughput improves measurably on Apple Silicon / NVIDIA hardware.

---

## Missing Resilience Features

| # | Task | File | Effort | Why |
|---|---|---|---|---|
| 0.8 | Backup / recovery | `palace.py` / CLI | 3h | No backup mechanism; disk failure = permanent data loss |
| 0.9 | Corruption detection | `searcher.py`, `knowledge_graph.py` | 2h | Silent bad results after crash; no integrity check on startup |
| 0.10 | Collection compaction | `searcher.py` | 2h | ChromaDB storage grows monotonically; no automated cleanup of tombstoned vectors |
| 0.11 | Index rebuild | `searcher.py` / CLI | 2h | No recovery path when ChromaDB HNSW index is corrupted; requires full re-ingest today |

**Exit criteria**:
- `mempalace backup` creates a portable snapshot of both ChromaDB and SQLite stores
- Startup integrity check detects and reports corruption rather than serving garbage
- `mempalace compact` reclaims storage from deleted drawers
- `mempalace rebuild-index` reconstructs the vector index from raw embeddings without re-ingesting source files

---

## Python Implementation Defects

| # | Task | File | Effort | Why |
|---|---|---|---|---|
| 0.12 | Thread Safety — enable WAL mode + `threading.Lock` | `knowledge_graph.py` | 1h | Multiple writers (background mining + active query) risk corruption; 10-second timeout is the only guard |
| 0.13 | Fix N+1 pattern in `file_already_mined` | `miner.py:file_already_mined` | 2h | 1000-file mine = 1000 individual ChromaDB queries; replace with single batch lookup |
| 0.14 | Log caught exceptions in broad `except Exception` blocks | `searcher.py`, `miner.py`, `knowledge_graph.py` | 1h | Silent failures are undebuggable; every `except Exception` must log `logger.exception(...)` |
| 0.15 | Replace string-munging entity IDs with SHA-256 / hash64 | `knowledge_graph.py:_entity_id` | 1h | Current implementation causes silent merge collisions (see 0.2 — this is the general fix across all callers) |
| 0.16 | Expose hardcoded limits in config | `miner.py`, `entity_detector.py`, `layers.py` | 2h | `CHUNK_SIZE=800`, `CHUNK_OVERLAP=100`, `MAX_BYTES_PER_FILE=5000`, `n_results=5` are all buried in source; none are in `pyproject.toml` or config schema |

**Exit criteria**:
- `PRAGMA journal_mode=WAL` set on connection open; write methods acquire `threading.Lock`
- `file_already_mined` issues one ChromaDB batch query regardless of file count
- Zero `except Exception` blocks without a `logger.exception` or `logger.error` call
- All limits configurable via `pyproject.toml` `[tool.mempalace]` section

---

## Implementation Order

```
PRIORITY    TASK    REASON
──────────  ──────  ──────────────────────────────────────────
NOW         0.2     SHA-256 IDs — prevents silent data corruption
NOW         0.14    Log exceptions — required to debug anything else
NOW         0.12    WAL mode — prevents corruption under concurrent access
NEXT        0.1     Persistent conn + Row factory — correctness + perf
NEXT        0.3     Partial indexes — hot query path correctness
NEXT        0.4     Atomic weight updates — prerequisite for Phase 1
NEXT        0.13    N+1 batch fix — easy win, measurable speedup
NEXT        0.15    Entity ID (generalise 0.2 fix to all callers)
NEXT        0.16    Expose config — low risk, unblocks tuning
LATER       0.5     ChromaDB partitioning — needed at scale, not urgent
LATER       0.6     SQLite VACUUM — housekeeping, low urgency
LATER       0.7     GPU embeddings — performance improvement
LATER       0.8     Backup/recovery — important but not blocking
LATER       0.9     Corruption detection — depends on 0.8 design
LATER       0.10    Collection compaction — housekeeping
LATER       0.11    Index rebuild — recovery tooling
```

---

## Exit Criteria

- [ ] `query_entity()` uses `sqlite3.Row` named columns throughout
- [ ] No entity ID collisions: SHA-256 keys in use, old string IDs migrated
- [ ] Temporal queries hit partial index (confirm via `EXPLAIN QUERY PLAN`)
- [ ] All weight updates are single atomic SQL expressions
- [ ] WAL mode enabled; all write paths hold `threading.Lock`
- [ ] `file_already_mined` uses batch lookup (single query for any N files)
- [ ] Zero silent `except Exception` swallows — all log the caught error
- [ ] `CHUNK_SIZE`, `CHUNK_OVERLAP`, `MAX_BYTES_PER_FILE`, `n_results` in config
- [ ] `mempalace backup` and `mempalace compact` commands functional
- [ ] Startup integrity check reports ChromaDB / SQLite corruption

---

## Testing

**Approach**: write a failing test first, then make the change, then confirm it passes.

### Test file map

| Task | Test file | What to assert |
|---|---|---|
| 0.1 — `sqlite3.Row` factory | `test_knowledge_graph.py` | `result[0]["name"]` works without `IndexError` |
| 0.2 — SHA-256 entity IDs | `test_knowledge_graph.py` | Add `"John O'Brien"` and `"John OBrien"` → `stats["entity_count"] == 2` |
| 0.3 — Partial indexes | `test_knowledge_graph.py` | `EXPLAIN QUERY PLAN` on temporal query contains `"INDEX"` |
| 0.4 — Atomic weight updates | `test_knowledge_graph.py` (`TestWALMode`) | Two threads update same triple weight concurrently → final value equals expected sum |
| 0.5 — ChromaDB partitioning | `test_searcher.py` | Mine into partition `"work"`, search from `"personal"` → zero cross-contamination |
| 0.6 — SQLite `compact()` | `test_knowledge_graph.py` | File size after bulk delete + `compact()` ≤ file size before inserts |
| 0.7 — GPU path | `test_searcher.py` | Monkeypatch `torch.cuda.is_available → True` → `build_embedding_function().device == "cuda"` |
| 0.8 — Backup/recovery | `tests/test_resilience.py` (new) | `backup(dest)` → delete palace → `restore(dest)` → data intact |
| 0.9 — Corruption detection | `tests/test_resilience.py` (new) | Truncate `knowledge_graph.db` → `check_integrity()` raises or logs error |
| 0.10 — Collection compaction | `tests/test_resilience.py` (new) | Add 100 drawers, delete 50, `compact()` → ChromaDB metadata count < 100 |
| 0.11 — Index rebuild | `tests/test_resilience.py` (new) | Delete HNSW index file → `rebuild_index()` → search returns same results |
| 0.12 — WAL mode | `test_knowledge_graph.py` (`TestWALMode`) | `PRAGMA journal_mode` returns `"wal"` on fresh connection |
| 0.13 — N+1 batch fix | `test_miner.py` | Monkeypatch `collection.get`, call `file_already_mined(["a","b","c"])` → `call_count == 1` |
| 0.14 — Log exceptions | `test_searcher.py`, `test_miner.py` | Pass broken path, use `caplog` → `"ERROR"` appears in log output |
| 0.15 — SHA-256 all callers | `test_knowledge_graph.py` | Same as 0.2 but verify via `_entity_id()` directly for all call sites |
| 0.16 — Config limits | `test_config.py` | `load_config({"chunk_size": 400})` → `cfg.chunk_size == 400` |

### Running tests

```bash
# default run (benchmarks excluded)
pytest tests/

# with coverage report
pytest --cov=mempalace --cov-report=term-missing tests/

# single task in isolation
pytest tests/test_knowledge_graph.py -k "test_entity_id_no_collision" -v
```

### Coverage progression

| After | Target threshold |
|---|---|
| Tasks 0.1–0.4, 0.12–0.16 land | raise `fail_under` from 30 → 50 |
| `test_resilience.py` complete (0.8–0.11) | raise to 65 |
| `entity_detector.py` tests added | raise to 75 |

---

## References

- [python-implementation-review.md](python-implementation-review.md) — Source of defects 0.12–0.16
- [local-deployment-limitations.md](local-deployment-limitations.md) — Source of storage ceiling and embedding tasks 0.5–0.11
- [knowledge-graph-performance.md](knowledge-graph-performance.md) — Source of KG correctness tasks 0.1–0.4
- [ROADMAP.md](ROADMAP.md) — Consolidated phase roadmap
