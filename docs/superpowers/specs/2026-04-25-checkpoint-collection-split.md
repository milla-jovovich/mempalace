# Checkpoint collection split — design

- **Project:** `mempalace` (jphein fork)
- **Date:** 2026-04-25
- **Status:** Draft — spec for implementation, no code yet
- **Promoted by:** [Cat 9 A/B report](file:///tmp/cat9-ab/REPORT.md), 2026-04-25 — kind=content delivers ~3 tokens vs 632 for kind=all on the canonical 151K palace. Over-fetch + post-filter is structurally inadequate; checkpoints must be removed from the searchable corpus, not filtered out of it.

## One-line summary

Move Stop-hook auto-save checkpoint diary entries to a separate ChromaDB collection (`mempalace_session_recovery`); `mempalace_search` queries `mempalace_drawers` only and never sees them.

## Goals

1. **Default search returns substantive content.** kind= filter and over-fetch hack become deletable. The main collection has only writes that callers chose to make searchable.
2. **Session recovery / hook audit still works** via a new MCP tool (`mempalace_session_recovery_read` or similar) that reads from the dedicated collection.
3. **Migration is non-lossy** for existing palaces with topic=checkpoint drawers already in the main collection. ~640 checkpoints out of 151K on JP's canonical palace.
4. **Forward-compatible with upstream.** Upstream MemPalace doesn't have the kind= filter and writes Stop-hook diary entries directly into the main collection. Migration story should be safe to apply against upstream-shaped palaces too (they just won't have many checkpoints to move).

## Non-goals

- Solving retrieval-quality issues unrelated to checkpoint dominance (chunk size #1024, embedding model, knowledge-graph integration). Those stay on the roadmap independently.
- Eliminating checkpoint storage entirely. They're useful for session recovery; just shouldn't be in the searchable corpus.
- Bidirectional cross-collection search. The recovery collection is for the recovery use case; if a caller wants both, they call both tools.

## Context — what exists, what changes

| Thing | State today | Changes |
|---|---|---|
| Stop-hook silent-save → palace-daemon `/silent-save` → `tool_diary_write` → `_get_collection(create=True)` (the main `mempalace_drawers`) | Writes checkpoints into the searchable corpus | Writes to `mempalace_session_recovery` instead |
| `tool_diary_write` (MCP tool) | Single collection write, no kind awareness | Routes by `topic ∈ _CHECKPOINT_TOPICS` → recovery collection; everything else → main collection |
| `mempalace_search` (MCP tool) → `search_memories` → `_get_collection(create=False)` | Queries main collection; kind= filter excludes checkpoints client-side | Queries main collection; kind= filter is deletable (no checkpoints to filter) |
| `mempalace_diary_read` (MCP tool) | Reads diary entries from main collection scoped to wing | Reads from main collection (still works for non-checkpoint diary entries — agent journals, etc.) |
| New: `mempalace_session_recovery_read` | doesn't exist | Reads from recovery collection by session_id, agent, date range |
| Existing palace data | Has ~640 topic=checkpoint drawers in main collection (varies per install) | Migrated to recovery collection on first daemon startup or via `mempalace repair --mode reorganize` |
| `kind=` parameter on search_memories / `_apply_kind_text_filter` post-filter / over-fetch hack | Active workaround | Becomes a no-op (kept for one release as safety net, then removed) |

## Architecture

### Collection layout

```
~/.mempalace/palace/  (or wherever palace_path points)
├── chroma.sqlite3
├── <main-uuid>/                # mempalace_drawers (existing)
│   ├── data_level0.bin
│   └── ...
└── <recovery-uuid>/             # mempalace_session_recovery (new)
    ├── data_level0.bin
    └── ...
```

Both collections live in the same ChromaDB persistent client, share the same HNSW config (`hnsw:space=cosine`, `hnsw:num_threads=1`, the works). Same backend, same flock, same daemon coordination — just two collections instead of one.

### Write path — `tool_diary_write`

```python
def tool_diary_write(agent_name, entry, topic="general", wing=""):
    if topic in _CHECKPOINT_TOPICS:                    # checkpoint / auto-save
        col = _get_session_recovery_collection()
    else:                                                # general agent diary
        col = _get_collection()
    col.add(ids=..., documents=[entry], metadatas=[...])
```

The routing decision is at write time, by topic. Existing call sites that don't pass `topic="checkpoint"` are unaffected — their diary entries continue to land in the main collection as before. Stop-hook writes (`hooks_cli.py`, `palace-daemon /silent-save`) all pass `topic="checkpoint"` (canonicalized at the daemon boundary as of `dd8894c`), so they route to recovery.

### Read paths

- **`mempalace_search`** — unchanged signature. Queries main collection only. The kind= parameter becomes vestigial: `kind="content"` is now equivalent to "default behavior"; `kind="checkpoint"` still works but returns 0 results from the main collection (since checkpoints aren't there) — callers should use the new recovery tool. `kind="all"` returns main collection contents (no filter).

  Migration plan: keep kind= for one release with a deprecation warning when `kind="checkpoint"` is used (suggest the new tool). Remove the kind= parameter and the `_apply_kind_text_filter` / over-fetch hacks in the release after that.

- **`mempalace_session_recovery_read`** (new MCP tool):

  ```
  mempalace_session_recovery_read(
      session_id: str | None = None,    # filter by session
      agent: str | None = None,          # filter by agent
      since: str | None = None,          # ISO date — entries newer than this
      until: str | None = None,          # ISO date — entries older than this
      wing: str | None = None,           # restrict to a project's checkpoints
      limit: int = 50,
  ) -> dict
  ```

  Returns checkpoint diary entries from the recovery collection. Used for hook debugging, session continuity audits, and "what were we doing 2 hours ago" recovery.

- **`mempalace_diary_read`** — unchanged. Still reads from main collection. Still useful for agent diaries that aren't auto-save checkpoints.

### Migration

The migration is necessary for existing palaces (the canonical 151K palace + every fork user's palace). Three options:

**Option A: auto-migrate on daemon startup.** `palace-daemon` lifespan checks for topic=checkpoint drawers in the main collection on startup; if present, moves them to the recovery collection in batches. Idempotent — once moved, the main collection has zero topic=checkpoint drawers and the migration is a no-op.

- **Pro:** zero user action. Just deploy the new daemon and the palace migrates itself.
- **Pro:** the palace-daemon already has the right concurrency control (semaphores) to do this safely.
- **Con:** delays daemon startup proportional to the migration size. On the canonical palace ~640 checkpoints; should take seconds, not minutes.

**Option B: explicit `mempalace repair --mode reorganize`.** Daemon doesn't auto-migrate; users opt in via a new repair mode.

- **Pro:** doesn't surprise anyone with a long startup.
- **Con:** users have to know to run it; until they do, they get the old broken behavior.

**Option C: lazy / on-write migration.** When the next checkpoint write fires, before writing to the recovery collection, the write path also moves any existing topic=checkpoint drawers from main → recovery. Amortized over time.

- **Pro:** zero-impact deploy; spread over actual usage.
- **Con:** complex code path. Edge cases around concurrent reads-during-migration. Hard to test.

**Recommendation: Option A**, with Option B as a manual escape hatch. The auto-migration is bounded (palace size has a finite number of historical checkpoints) and the daemon already coordinates write-side concurrency; running the migration once at startup under the rebuild-style exclusive semaphore is the cleanest shape.

### What gets deleted (one release after migration)

After this lands and one full release cycle:

- `_CHECKPOINT_TOPICS` constant
- `_apply_kind_text_filter` post-filter
- The over-fetch hack (`max(n*20, 100)`) on kind != "all" — back to standard `n_results * 3`
- The `kind=` parameter on `search_memories`, `mempalace_search` MCP tool, palace-daemon `/search` and `/context` HTTP routes

## Components

### Build: `mempalace/palace.py` — collection adapter

Add `_SESSION_RECOVERY_COLLECTION = "mempalace_session_recovery"` constant. Add `get_session_recovery_collection(palace_path, create=False)` mirroring `get_collection()`'s shape — same backend, same hnsw config, same flock semantics.

### Build: `mempalace/mcp_server.py` — write routing + new tool

Modify `tool_diary_write` to route by topic. Add `tool_session_recovery_read` handler with the signature above. Register in the `TOOLS` dict with input_schema and description.

Update upstream-PR-relevance: this is a *new MCP tool* and a *behavior change to existing one*. Probably wants to be a single PR upstream once stable in the fork.

### Build: `mempalace/migrate.py` — reorganize migration

Add `migrate_checkpoints_to_recovery(palace_path)` that walks the main collection looking for topic in `("checkpoint", "auto-save")`, copies them to the recovery collection, deletes from the main collection. Idempotent.

Wire into `mempalace repair --mode reorganize` (new mode). And into palace-daemon's lifespan startup as auto-migrate (gated on a config flag for those who want manual control).

### Modify: `mempalace/hooks_cli.py`

`_save_diary_direct` already calls `tool_diary_write(topic="checkpoint", ...)` — no change needed. The routing change is in `tool_diary_write` itself.

### Modify: palace-daemon (separate repo)

`palace-daemon/main.py`'s `/silent-save` already calls `tool_diary_write` via `_do_silent_save_write` which uses the canonicalized `topic="checkpoint"`. No daemon-side code change needed for the write path.

Add migration-on-startup gated behind `PALACE_AUTO_MIGRATE_CHECKPOINTS=1` env var (default on). Inside `lifespan`, after the daemon comes up, fire `migrate_checkpoints_to_recovery()` under the exclusive semaphore once.

### Modify: tests

- `tests/test_palace.py` — `get_session_recovery_collection` smoke
- `tests/test_mcp_server.py` — `tool_diary_write` routing by topic; `tool_session_recovery_read` happy-path + filters
- `tests/test_migrate.py` — `migrate_checkpoints_to_recovery` is idempotent, lossless, doesn't touch non-checkpoint drawers
- Existing `TestCheckpointFilter` tests — should still pass for kind="all" / "content" / "checkpoint" but the underlying mechanism is now "the collection has no checkpoints" instead of "the post-filter dropped them." Update test assertions accordingly.

### Cat 9 re-run after migration (acceptance criterion)

The same A/B from `/tmp/cat9-ab/REPORT.md` should re-run after the migration. **Predicted outcome:** kind=all and kind=content tokens-per-question converge — both around 600 — because the main collection has no checkpoints to filter. If the prediction holds, that's the empirical proof the structural fix worked.

## Honest capability envelope

This is a **2-3 day implementation** at a focused pace, including tests and migration verification. Not a single-session ship.

After it lands, retrieval quality on the canonical palace should jump materially (token count, answer quality on RLM smoke test, future LongMemEval-S E2E numbers) because the main collection's vector ranking is no longer dominated by checkpoint shape.

## Why this isn't an upstream-first PR

Upstream MemPalace doesn't have the kind= filter, doesn't have the daemon, doesn't have the canonicalized topic. The fork is in a position to ship this end-to-end first, validate against the canonical palace, and *then* propose the structural change upstream as a single coherent PR (probably accompanied by the Cat 9 numbers as evidence).

Filing upstream first would require @bensig to coordinate multiple changes simultaneously across mempalace + palace-daemon + Stop-hook clients. Better to land it in the fork, prove it works, propose it cleanly.

## Open questions

1. **Does the recovery collection need its own embedding model?** Currently using the same ChromaDB default (MiniLM). Probably fine — recovery is a per-session lookup, semantic search there is rare. Could skip embedding entirely and use SQLite-only storage. Decide during implementation.
2. **What does `mempalace_diary_read` do for the recovery use case?** Right now it reads main collection. After this change, it returns nothing for hook-saved sessions because those moved. Either: (a) leave it main-only (callers asking for checkpoint sessions should use the new tool), or (b) accept a `recovery: bool = False` param. Probably (a) — explicit is clearer.
3. **What about `mempalace mine` outputs that look checkpoint-shaped?** None do — the convo_miner writes structured drawers with topic="conversation" or similar, not topic="checkpoint." So no conflict.

## Implementation plan

See companion plan doc: `docs/superpowers/plans/2026-04-25-checkpoint-collection-split-impl.md` *(to be written)*.
