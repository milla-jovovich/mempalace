# Checkpoint collection split — implementation plan

Companion to [`docs/superpowers/specs/2026-04-25-checkpoint-collection-split.md`](../specs/2026-04-25-checkpoint-collection-split.md).

12 tasks, TDD-shaped, scoped for ~2-3 days focused work.

## Phase A: Scaffolding (no behavior change)

1. **Add `_SESSION_RECOVERY_COLLECTION` constant + `get_session_recovery_collection()`** in `mempalace/palace.py`. Mirrors `get_collection()` but uses the new collection name. Test: `tests/test_palace.py::test_get_session_recovery_collection_creates_with_correct_metadata` — verifies hnsw_space=cosine, hnsw:num_threads=1, palace_path threaded through.

2. **Verify both collections coexist in one ChromaDB client.** Test: open both, write a drawer to each, verify they don't interfere. ChromaDB supports multi-collection per palace natively; this is a sanity check.

## Phase B: Write routing (write path change, read path unchanged)

3. **Route `tool_diary_write` by topic.** Modify `mempalace/mcp_server.py::tool_diary_write` so that `topic in _CHECKPOINT_TOPICS` writes to the recovery collection; everything else writes to the main collection (current behavior).

   Test: `tests/test_mcp_server.py::test_diary_write_routes_checkpoint_to_recovery` — write with `topic="checkpoint"`, assert main collection drawer count unchanged, recovery collection has the new drawer.

   Test: `tests/test_mcp_server.py::test_diary_write_routes_general_to_main` — write with `topic="musings"`, assert main collection has it, recovery collection unchanged.

4. **Verify `mempalace_search` no longer sees newly-written checkpoints.** This is the inverse of step 3 — a regression test that locks in the read-side benefit. Write a checkpoint via tool_diary_write, then call search_memories — assert it doesn't surface.

## Phase C: New read path (recovery tool)

5. **Add `tool_session_recovery_read` handler** in `mempalace/mcp_server.py`. Signature per spec: filters by session_id, agent, since/until, wing, limit. Reads from recovery collection only.

   Test: `tests/test_mcp_server.py::test_session_recovery_read_filters_by_session_id` — write 3 checkpoints under different session_ids, query for one, assert only that one returns.

   Test: `test_session_recovery_read_returns_empty_when_no_match` — empty recovery collection returns empty.

   Test: `test_session_recovery_read_handles_none_metadata` — defensive, mirrors the #999 / #1094 / #1201 family.

6. **Register the new tool in the TOOLS dict** with input_schema, description. Verify via MCP `tools/list` that `mempalace_session_recovery_read` shows up.

## Phase D: Migration (existing-palace data move)

7. **Add `migrate_checkpoints_to_recovery(palace_path)`** in `mempalace/migrate.py`. Walks main collection paginated (10K-drawer batches per the existing `miner.status` paginated pattern), finds drawers with `topic in _CHECKPOINT_TOPICS`, copies them to recovery, deletes from main. Idempotent — running twice is a no-op on the second run.

   Test: `tests/test_migrate.py::test_migrate_moves_checkpoints` — seed main collection with 3 checkpoints + 2 non-checkpoints. Run migration. Assert main has 2 drawers (the non-checkpoints), recovery has 3.

   Test: `test_migrate_is_idempotent` — run migration twice. Assert state after run 2 is identical to state after run 1.

   Test: `test_migrate_preserves_drawer_ids_and_metadata` — verify the moved drawer keeps its ID, content, and metadata exactly.

   Test: `test_migrate_handles_legacy_auto_save_topic` — also moves topic="auto-save" drawers per the canonical-topic synonyms.

## Phase E: CLI + daemon integration

8. **Wire migration into `mempalace repair --mode reorganize`** in `mempalace/repair.py` and the CLI dispatcher. Test the CLI invocation end-to-end against a real palace fixture.

9. **Wire migration into palace-daemon startup** (palace-daemon repo). In the daemon's `lifespan` async context, after the mempalace client is warmed, fire `migrate_checkpoints_to_recovery()` under the exclusive semaphore once. Gated behind `PALACE_AUTO_MIGRATE_CHECKPOINTS=1` env var (default on).

   Test: integration test on the daemon side — start daemon against a palace with seeded checkpoints, verify they're moved by the time `/health` returns.

## Phase F: Cleanup (one release later, deferred for safety)

These don't ship in the same PR — they ship in the *next* release, after we've verified migration is stable and the recovery-tool consumer pattern is in use.

10. **Mark kind= parameter on search_memories as deprecated** with a `DeprecationWarning`. Document in CHANGELOG.

11. **Cat 9 A/B re-run** after migration lands on the canonical palace. Acceptance criterion: kind=all and kind=content tokens-per-question converge (both ~600). If they don't, something's wrong and we shouldn't promote to step 12.

12. **Delete `_apply_kind_text_filter`, the over-fetch hack, the kind= parameter** from search_memories and the MCP tool. Update all tests that reference kind=. CHANGELOG: "kind= filter deprecated and removed; checkpoints moved to recovery collection in [version]; default search now returns content automatically."

## Test running

```bash
# Phase A-D (mempalace fork)
cd ~/Projects/memorypalace
./scripts/preflight.sh

# Phase E (palace-daemon)
cd ~/Projects/palace-daemon
PALACE_DAEMON_URL=http://disks.jphe.in:8085 \
PALACE_API_KEY=$(jq -r .env.PALACE_API_KEY ~/.claude/settings.local.json) \
    ./scripts/verify-routes.sh

# Phase F (Cat 9 re-run)
cd ~/Projects/multipass-structural-memory-eval
./venv/bin/sme-eval retrieve --adapter mempalace-daemon \
    --questions /tmp/cat9-ab/questions.yaml \
    --kind all --n-results 5 --json /tmp/cat9-postfix-all.json

./venv/bin/sme-eval retrieve --adapter mempalace-daemon \
    --questions /tmp/cat9-ab/questions.yaml \
    --kind content --n-results 5 --json /tmp/cat9-postfix-content.json

# compare token counts — should be roughly equal post-migration
```

## Risks

- **Migration on the canonical 151K palace** — first run will be slow. ~640 checkpoints to move; estimated ~1-3 min under exclusive semaphore. Document the one-time delay in the CHANGELOG.
- **ChromaDB internal IDs** — copying drawers across collections preserves the ID at the application level, but ChromaDB's internal seq_id (the BLOB-vs-INTEGER thing from #664/#1090/#1134) might behave oddly. Test thoroughly. Worst case: regenerate IDs on copy with a `recovery_<original_id>` prefix.
- **Existing tests that expect checkpoints in `mempalace_search` results** — there shouldn't be any (the kind= filter would already exclude them), but a grep for `topic.*checkpoint.*search` in tests/ before starting will confirm.
- **Upstream divergence increases** — this is a meaningful schema change. Coordinate timing with bensig.

## Acceptance criteria

- All 12 phase tasks have green tests.
- `mempalace repair --mode reorganize` runs idempotently against the canonical palace.
- Cat 9 A/B re-run shows tokens-per-question convergence (kind=all ≈ kind=content, both substantive).
- Palace-daemon startup migrates automatically on first boot post-deploy.
- Upstream PR draft ready (single PR covering the whole fork-side change set, with Cat 9 numbers as evidence in the description).
