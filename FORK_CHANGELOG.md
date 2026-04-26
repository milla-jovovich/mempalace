# Fork Changelog (jphein/mempalace)

Fork-ahead changes that aren't yet in upstream `MemPalace/mempalace`.
Upstream's release history lives in [`CHANGELOG.md`](CHANGELOG.md);
this file is the supplement.

Date-based sections, not semver — the fork tracks `upstream/develop` and
doesn't cut its own release tags. When a fork-ahead row lands upstream,
the entry is moved to the **Merged into upstream** section at the
bottom (kept for ~2 weeks, then trimmed).

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [2026-04-26]

### Added

- **`mempalace_session_recovery_read` MCP tool** — reads the dedicated
  `mempalace_session_recovery` collection by optional `session_id`,
  `agent`, `since`, `until`, `wing`, `limit` filters; returns entries
  newest-first. Used for hook auditing and "what was I doing 2 hours
  ago" recovery. Registered in the `TOOLS` dict and documented in
  `website/reference/mcp-tools.md`. ([`e266365`](https://github.com/jphein/mempalace/commit/e266365))
- **`mempalace repair --mode reorganize`** — explicit operator command
  to migrate existing `topic=checkpoint` drawers from the main
  collection to `mempalace_session_recovery`. Idempotent, ID and
  metadata preserving. ([`42817d7`](https://github.com/jphein/mempalace/commit/42817d7))
- **`scripts/deploy.sh`** — one-command push + Syncthing-aware redeploy
  to the canonical disks daemon (`systemctl --user restart palace-daemon`
  + post-restart import check that today\'s fork-ahead surface is
  loaded). ([`8252025`](https://github.com/jphein/mempalace/commit/8252025))
- **`drawer_id` field** on `mempalace_search`, `mempalace_diary_read`,
  and `mempalace_session_recovery_read` payloads — chromadb\'s primary
  key was always returned by `query()` / `get()` but never plumbed into
  the result dicts; consumers (e.g. citation popovers) can now follow
  a hit back to the underlying drawer via `mempalace_get_drawer`.
  ([`9a8bb77`](https://github.com/jphein/mempalace/commit/9a8bb77))

### Changed

- **`tool_diary_write` routes `topic in _CHECKPOINT_TOPICS` to a
  dedicated collection** (`mempalace_session_recovery`). Everything else
  stays in `mempalace_drawers`. The main collection is now the
  *verbatim store* — chats, tool calls, mined files — and is no longer
  polluted by Stop-hook auto-save fragments dominating vector top-N.
  ([`e266365`](https://github.com/jphein/mempalace/commit/e266365))
- **`hook_precompact` writes a session-recovery marker** before mining
  the transcript and allowing compaction. Mirrors `hook_stop`\'s
  `_save_diary_direct` call so a context-compaction event leaves a
  queryable timestamp in the recovery collection rather than nothing.
  ([`42817d7`](https://github.com/jphein/mempalace/commit/42817d7))
- **`tool_diary_write` accepts an optional `session_id`** parameter,
  stored in metadata when a checkpoint is being written so the new
  recovery-read tool can filter by Claude Code session.
  ([`e266365`](https://github.com/jphein/mempalace/commit/e266365))

### Fixed

- **`quarantine_stale_hnsw` no longer destroys healthy indexes on cold
  start.** Two-stage gate: (1) mtime gap > threshold (existing) AND
  (2) `_segment_appears_healthy` integrity sniff-test on
  the chromadb segment metadata file (new — checks for chromadb\'s
  protocol/terminator bytes without deserializing). Production case
  2026-04-26 06:56:45 had three healthy 253MB segments quarantined on
  cold start by mtime alone (chromadb 1.5.x flushes HNSW asynchronously;
  clean shutdown does not force-flush, so the on-disk gap is the steady
  state, not corruption). The integrity gate distinguishes flush-lag
  from corruption. ([`645ba20`](https://github.com/jphein/mempalace/commit/645ba20))
- **`make_client()` only invokes `quarantine_stale_hnsw` once per palace
  per process.** Previously, every reconnect under steady write load
  re-fired the proactive check, racking up `.drift-*` directories every
  10–30 minutes. The cold-start gate (`ChromaBackend._quarantined_paths`)
  caps it to one fire on first open; runtime drift detection still
  works via palace-daemon\'s `_auto_repair`, which calls
  `quarantine_stale_hnsw` directly. ([`70c4bc6`](https://github.com/jphein/mempalace/commit/70c4bc6))

### Performance

- **Cherry-picked upstream PR [#1085](https://github.com/MemPalace/mempalace/pull/1085)**
  (@midweste, OPEN as of 2026-04-26) — batch ChromaDB inserts in
  `miner.process_file()`. New `_build_drawer()` helper + `add_drawers()`
  batch-insert path; one `collection.upsert` + one ONNX embedding pass
  per sub-batch instead of per-chunk. Hoists `datetime.now()` and
  `os.path.getmtime()` to file-level (2 syscalls per file instead of
  2N). Reported 10–30× mining speedup upstream. Fork-side resolution
  preserved fork\'s existing `DRAWER_UPSERT_BATCH_SIZE=1000`; aliased
  upstream\'s `CHROMA_BATCH_LIMIT` to it. ([`6be6fff`](https://github.com/jphein/mempalace/commit/6be6fff))
  *Becomes a no-op when #1085 merges to develop and we next sync.*

---

## [2026-04-25]

### Added

- **Phases A–C of the checkpoint collection split** — new
  `mempalace_session_recovery` collection adapter
  (`_SESSION_RECOVERY_COLLECTION` + `get_session_recovery_collection`
  in `palace.py`); `tool_diary_write` routes `topic in _CHECKPOINT_TOPICS`
  to it. Promoted from "future work" to "necessary" by the same-day
  Cat 9 A/B (`kind=all` 632 tokens/Q vs `kind=content` 3 tokens/Q on
  the canonical 151K-drawer palace). 12 new tests across
  `tests/test_session_recovery.py` + `TestCheckpointRouting` +
  `TestSessionRecoveryRead`. Design doc:
  `docs/superpowers/specs/2026-04-25-checkpoint-collection-split.md`;
  TDD plan:
  `docs/superpowers/plans/2026-04-25-checkpoint-collection-split-impl.md`.
  ([`e266365`](https://github.com/jphein/mempalace/commit/e266365))

### Fixed

- **`palace_graph.build_graph` skips `None` metadata.**
  `palace_graph.py:95` was calling `meta.get("room", "")`
  unconditionally; ChromaDB returns `None` for legacy/partial-write
  drawers, taking out every consumer of `build_graph` (graph_stats,
  find_tunnels, traverse, the daemon\'s `/stats`). Caught by
  palace-daemon\'s `verify-routes.sh` smoke test. Filed as upstream
  [#1201](https://github.com/MemPalace/mempalace/pull/1201).
  ([`5fd15db`](https://github.com/jphein/mempalace/commit/5fd15db))
- **`kind=` filter on `search_memories` excludes Stop-hook
  checkpoints by default** — surgical fix while the structural split
  was being designed. Three values: `"content"` (default, excludes),
  `"checkpoint"` (recovery/audit only), `"all"` (no filter). Two
  same-day architecture corrections: (a) the where-clause filter
  (`topic $nin [...]`) tripped a chromadb 1.5.x filter-planner bug
  that returned `Internal error: Error finding id` on every
  `kind=content` vector query, so the exclusion moved to post-filter
  only ([`398f42f`](https://github.com/jphein/mempalace/commit/398f42f));
  (b) vector top-N is dominated by checkpoints on this palace, so
  post-filter alone empties the result set without aggressive
  over-fetch — pull size raised to `max(n*20, 100)` for `kind != "all"`
  ([`f9f5cc4`](https://github.com/jphein/mempalace/commit/f9f5cc4)).
  9 tests in `TestCheckpointFilter`. *This is the safety net during
  the transition; once Phase D ships and existing checkpoints
  migrate, the post-filter and over-fetch hack become deletable.*

---

## Merged into upstream (recent)

Trimmed monthly. See [`CHANGELOG.md`](CHANGELOG.md) for the full
released history.

- **PR #659** — diary `wing` parameter (merged 2026-04-23)
- **PR #661** — graph cache with write-invalidation (merged 2026-04-22)
- **PR #673** — deterministic hook saves (merged 2026-04-22)
- **PR #1021** — Claude Code 2.1.114 stdout/silent_save fixes (merged 2026-04-22)
- **PR #999** — `None`-metadata guards across read paths (merged 2026-04-18)
- **PR #1000** — `quarantine_stale_hnsw` (shipped in v3.3.2)
- **PR #1023** — PID file guard (shipped in v3.3.2)
- **PR #681** — Unicode checkmark → ASCII (shipped in v3.3.2)
