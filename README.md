# MemPalace (jphein fork)

**JP's production fork of [milla-jovovich/mempalace](https://github.com/milla-jovovich/mempalace)**

[![version-shield](https://img.shields.io/badge/version-3.3.4-4dc9f6?style=flat-square&labelColor=0a0e14)](https://github.com/jphein/mempalace/releases) [![upstream-shield](https://img.shields.io/badge/upstream-3.3.3-7dd8f8?style=flat-square&labelColor=0a0e14)](https://github.com/MemPalace/mempalace/releases)
[![python-shield](https://img.shields.io/badge/python-3.9+-7dd8f8?style=flat-square&labelColor=0a0e14&logo=python&logoColor=7dd8f8)](https://www.python.org/)
[![license-shield](https://img.shields.io/badge/license-MIT-b0e8ff?style=flat-square&labelColor=0a0e14)](LICENSE)

---

Fork of [MemPalace](https://github.com/milla-jovovich/mempalace), tracking `upstream/develop` through the 2026-04-25 sync (absorbs upstream's unreleased v3.3.4 line — Felipe Truman's [#976](https://github.com/MemPalace/mempalace/pull/976) HNSW + mine_global_lock + PreCompact-attempt-cap, Igor's [#1179](https://github.com/MemPalace/mempalace/pull/1179) BM25 hybrid CLI search, [#1180](https://github.com/MemPalace/mempalace/pull/1180) cross-wing topic tunnels, [#1182](https://github.com/MemPalace/mempalace/pull/1182) graceful Ctrl-C, [#1183](https://github.com/MemPalace/mempalace/pull/1183) init-mine UX, [#1185](https://github.com/MemPalace/mempalace/pull/1185) batched-upsert-gpu). Upstream shipped [v3.3.3](https://github.com/MemPalace/mempalace/releases/tag/v3.3.3) on 2026-04-24. Running in production since 2026-04-09 — currently **151,420 drawers** behind [palace-daemon](https://github.com/jphein/palace-daemon) on a separate host (migrated 2026-04-24, see "Multi-client coordination" below). See upstream README for full feature docs.

What this fork adds that you won't get from upstream yet: a **deterministic silent-save hook architecture** (zero data loss, `systemMessage` notification, daemon-strict mode that skips local writes when `PALACE_DAEMON_URL` is set), **ChromaDB 1.5.x hardening** (`quarantine_stale_hnsw` drift recovery, segfault-trigger guards, 8-site `None`-metadata safety), **search that never silently misses** (`search_memories` returns warnings + sqlite BM25 top-up + `available_in_scope` so callers can see what they aren't getting), and **`kind=`-filtered search** that excludes Stop-hook auto-save checkpoints by default — discovered via the 2026-04-25 RLM smoke test, which surfaced that checkpoint diary entries (high word-density session summaries) were dominating retrieval and producing confident-but-misleading answers. Full list below.

1383 tests pass on `main` · [Discussion #1017](https://github.com/MemPalace/mempalace/discussions/1017) introduces the fork upstream · [Issues on this repo](https://github.com/jphein/mempalace/issues) for fork-specific feedback.

## Fork change queue

Everything the fork has ahead of upstream, ranked from easiest PR to hardest. Contributors: pick a row near the top of the table and you'll land a first-time PR with low rework risk. Merged-upstream history is in the [Fork Changes](#fork-changes) section further down.

Status legend: a PR number means there's an open upstream PR for the change; **PR pending** means the fork has the change but no PR has been filed yet; **PR candidate** means the fork has the change, no PR yet, and it's scheduled to be proposed upstream (most need an issue-first discussion to align on approach). As of 2026-04-25, there is no `fork-only` status — every fork-ahead item is a PR candidate. If a proposal is rejected upstream, we document the reason in an issue and move on.

Size (lines of diff) and Risk (maintainer-appetite + chance of a rework request) are there so a contributor scanning the table can pick a good first PR without guessing.

| Area | Change | Status | Size | Risk | Files |
|---|---|---|---|---|---|
| **CLI** | `cmd_export` CLI wrapper — wires upstream's existing `export_palace()` from `exporter.py` to a CLI entry point; upstream has the module but no CLI. | [#1086](https://github.com/MemPalace/mempalace/pull/1086) | tiny | none | `cli.py` |
| **Hooks** | `mempal_save_hook.sh` auto-detects Python — checks `MEMPAL_PYTHON` env var, then repo venv at `../../venv/bin/python3`, then system `python3`; no hardcoded path required. Same pattern applied to `.claude-plugin/` stop and precompact hooks. | [Replied on #1049 on 2026-04-21](https://github.com/MemPalace/mempalace/issues/1049#issuecomment-4292554161) offering our autodetect; attempted the `.claude-plugin/` side via [#1115](https://github.com/milla-jovovich/mempalace/pull/1115) on 2026-04-22, withdrawn 2026-04-23 as premature pending [#1069](https://github.com/MemPalace/mempalace/issues/1069) arbitration (CI correctly caught the #942 PATH-only contract violation). Re-submit after bensig's direction on #1069. | small | low | `hooks/mempal_save_hook.sh`, `.claude-plugin/hooks/mempal-stop-hook.sh`, `.claude-plugin/hooks/mempal-precompact-hook.sh` |
| **Reliability** | `quarantine_stale_hnsw()` should also validate the HNSW `index_metadata` file integrity — a process killed mid-write leaves a corrupt file with zero mtime drift, so the 1h threshold doesn't fire and the next palace open segfaults. Fix: attempt to deserialize the file in the quarantine check and quarantine on failure regardless of mtime. | Blocked on [#1062](https://github.com/MemPalace/mempalace/pull/1062) — @Samaara-Das's PR wires the quarantine caller that v3.3.2 shipped without (fixes [#1061](https://github.com/MemPalace/mempalace/issues/1061)). File our integrity-check extension as a follow-up after #1062 merges. | small | low | `backends/chroma.py` |
| **CLI** | `cmd_purge` CLI — delete drawers by wing/room, nuke-and-reinsert retained drawers to avoid HNSW ghost entries left by `collection.delete()`. Substantive new command. | [#1087](https://github.com/MemPalace/mempalace/pull/1087) · closes [#848](https://github.com/MemPalace/mempalace/issues/848) (@robottwo's wing/room drawer removal feature request); references [#521](https://github.com/MemPalace/mempalace/issues/521) for hnswlib motivation | medium | medium | `cli.py` |
| **Hooks** | Transcript auto-mining in `hook_precompact()` with correct defaults — `--mode convos` + `wing_<project>` derived from transcript path, plus a `hook_auto_mine` config flag (default `true`) for explicit opt-out | [Commented on #1083 on 2026-04-21](https://github.com/MemPalace/mempalace/issues/1083#issuecomment-4292630330) with the two-part design (opt-out + correct defaults), asked @raphaelsamy whether `hook_auto_mine: false` boolean is sufficient or they want finer-grained control, asked @bensig for direction. PR to follow once direction is confirmed. | medium | low-medium | `hooks_cli.py`, `config.py`, `tests/test_hooks_cli.py` |
| **Performance** | `bulk_check_mined()` paginated pre-fetch + `--workers` ThreadPoolExecutor concurrent mining | [Issue #1088](https://github.com/MemPalace/mempalace/issues/1088) filed 2026-04-21; [cross-ref comment](https://github.com/MemPalace/mempalace/issues/1088#issuecomment-4292570126) ties it to [#357](https://github.com/MemPalace/mempalace/issues/357) (parallel-mining corruption we could fix) and gates the PR on [#1071](https://github.com/MemPalace/mempalace/pull/1071) landing first (ORT thread cap, for bounded parallelism). | medium | medium | `palace.py`, `miner.py` |
| **Reliability** | `_get_client()` tries `get_collection` before `create_collection` — `get_or_create_collection` segfaults ChromaDB 1.5.x when the existing collection's metadata differs from the call-site metadata | [Issue #1089](https://github.com/MemPalace/mempalace/issues/1089) filed 2026-04-21 — documented the crash + fork workaround, cross-referenced [#974](https://github.com/MemPalace/mempalace/issues/974) / [#1071](https://github.com/MemPalace/mempalace/pull/1071) interaction (metadata drift risk post-merge), offered three paths: interim guard PR, chroma-core bug report, or close as covered. | small | medium | `backends/chroma.py` |
| **Reliability** | Skip `_fix_blob_seq_ids` sqlite open after first successful migration via `.blob_seq_ids_migrated` marker — opening sqlite3 against a live ChromaDB 1.5.x file corrupts the next PersistentClient | [#1177](https://github.com/milla-jovovich/mempalace/pull/1177) filed 2026-04-24, closes [#1090](https://github.com/MemPalace/mempalace/issues/1090) — marker guard in `_fix_blob_seq_ids()`, CI green after ruff cleanup | small | medium | `backends/chroma.py` |
| **Search** | `_tokenize` None-document guard — `searcher._tokenize` short-circuits to `[]` when ChromaDB returns a drawer with `documents=None`, preventing `AttributeError` during `_hybrid_rank → _bm25_scores → _tokenize`. Closes the gap left by upstream's [#999](https://github.com/milla-jovovich/mempalace/pull/999) None-metadata audit, which covered metadata read loops but not BM25 helpers. Observed in production daemon log on 2026-04-24. | [#1198](https://github.com/milla-jovovich/mempalace/pull/1198) filed 2026-04-24, three regression tests in `TestBM25NoneSafety` | tiny | low | `searcher.py`, `tests/test_searcher.py` |
| **Search** | `kind=` filter on `search_memories` and `mempalace_search` MCP tool excludes Stop-hook auto-save checkpoints by default. CHECKPOINT-shaped diary entries (`topic=checkpoint`, text starting `"CHECKPOINT:"`) are short, word-dense session summaries that consistently outrank substantive content under cosine similarity — the actual conversations they summarize get buried. Three values: `"content"` (default, excludes), `"checkpoint"` (recovery/audit only), `"all"` (no filter). The exclusion is post-filter only (commits [`398f42f`](https://github.com/jphein/mempalace/commit/398f42f), [`f9f5cc4`](https://github.com/jphein/mempalace/commit/f9f5cc4)) — combining `$nin`/`$in` metadata operators with vector queries trips a ChromaDB 1.5.x filter-planner bug that returns `Internal error: Error finding id` on every query. Post-filter checks both `topic` metadata AND text-prefix shape; coverage equivalent to where-clause + post-filter belt-and-suspenders, no chromadb bug. With kind != "all", over-fetch pulls `max(n*20, 100)` candidates so substantive content survives the filter on a checkpoint-dominant corpus. Companion fix in [`jphein/palace-daemon` `b4b39fc`](https://github.com/jphein/palace-daemon/commit/b4b39fc) plumbs `kind=` through `/search` + `/context` HTTP routes (and fixes a coexisting bug where `limit=` had been silently ignored). | PR pending — fork commits [`8d02835`](https://github.com/jphein/mempalace/commit/8d02835) → [`3d85739`](https://github.com/jphein/mempalace/commit/3d85739) → [`398f42f`](https://github.com/jphein/mempalace/commit/398f42f) → [`f9f5cc4`](https://github.com/jphein/mempalace/commit/f9f5cc4), 9 regression tests in `TestCheckpointFilter`, end-to-end validated against the 151K-drawer canonical palace on 2026-04-25 | small | low | `searcher.py`, `mcp_server.py`, `tests/test_searcher.py` |
| **Reliability** | Call `quarantine_stale_hnsw()` in `make_client()` itself + lower threshold 3600→300s — upstream's #1062 wires it at server startup but misses short-lived callers (hooks, CLI). Production 0.96h-drift segfault confirmed 1h threshold was too loose. | [#1173](https://github.com/milla-jovovich/mempalace/pull/1173) filed 2026-04-24, complementary to [#1062](https://github.com/MemPalace/mempalace/pull/1062) | small | low | `backends/chroma.py` |
| **Reliability** | Gate `quarantine_stale_hnsw` in `make_client()` to once-per-palace-per-process. Symptom on canonical disks daemon (no Syncthing replication of palace data — confirmed `.stignore` excludes `mempalace-data`): `.drift-*` directories accumulating every 10–30 min throughout the day. Root cause: `chroma.sqlite3` mtime bumps per write but HNSW segments flush on chromadb's internal cadence; under steady write load the mtime gap exceeds the 300s threshold from #1173 even though nothing is corrupt. The proactive check renames a valid HNSW segment, chromadb rebuilds, drift recurs as soon as the next batch lands. **Real cold-start drift still caught** (fresh process opening replicated/restored palace); **real runtime errors still caught** via palace-daemon `_auto_repair` calling `quarantine_stale_hnsw` directly. | PR pending — fork commit [`70c4bc6`](https://github.com/jphein/mempalace/commit/70c4bc6), 2 new tests in `test_backends.py` (single-fire-per-palace, per-palace independence) | tiny | low | `backends/chroma.py`, `tests/test_backends.py` |
| **Reliability** | `hook_precompact` now writes a session-recovery checkpoint marker before mining the transcript and allowing compaction. Mirrors `hook_stop`'s `_save_diary_direct` call; same routing path A–C established (write lands in `mempalace_session_recovery`, queryable via `mempalace_session_recovery_read` by session_id). The motivation is JP's framing — *the palace is just a verbatim store of chats and tool calls* — so a context-compaction event is a derivative write that belongs in the recovery collection, not the searchable corpus. Failures are non-fatal (logged; mining + compaction still proceed). Bundled with phase D in commit [`42817d7`](https://github.com/jphein/mempalace/commit/42817d7). | PR pending — see checkpoint-split row above | tiny | none | `mempalace/hooks_cli.py` |
| **Reliability** | Make `quarantine_stale_hnsw` non-destructive — add an integrity sniff-test that distinguishes corruption from chromadb's normal async flush lag. **Production root-cause** confirmed in disks daemon journal 2026-04-26 06:56:45: every cold-start renamed all three HNSW segment dirs (538-557s `chroma.sqlite3` mtime gap), chromadb created empty replacements, vector recall went to 0/N until a 15-min `mempalace repair --mode rebuild` repopulated. The mtime threshold alone can't tell flush-lag from corruption: chromadb 1.5.x flushes HNSW asynchronously and a clean shutdown does NOT force-flush, so on-disk HNSW is *always* somewhat older than `chroma.sqlite3`. Fix: stage 2 integrity gate sniffs `index_metadata.pickle` for its protocol/terminator bytes (no deserialization — security-hook compliant) before renaming. Healthy segment with mtime drift → keep in place; truncated/zero-filled metadata → quarantine. Production case from 06:24 had `data_level0.bin=253MB` + 18MB metadata file — clearly healthy, but renamed under old logic. | PR pending — 4 new tests in `test_backends.py` (renames-corrupt, leaves-healthy-with-drift, leaves-no-metadata, renames-truncated) | small | low | `backends/chroma.py`, `tests/test_backends.py` |
| **Search** | Surface `drawer_id` in `mempalace_search` results, `mempalace_diary_read` entries, and the new `mempalace_session_recovery_read` payload. ChromaDB's primary key was always returned by `query()` / `get()` but never plumbed into the result-building loop, so callers couldn't link a hit back to a drawer (citation popovers, `mempalace_get_drawer` follow-ups, link-out with real target). Defensive zip-with-id-pad keeps existing test mocks working without touching N fixtures. | PR pending — fork commit [`9a8bb77`](https://github.com/jphein/mempalace/commit/9a8bb77), 1 new integration test + 1 inline assertion | tiny | none | `searcher.py`, `mcp_server.py`, `tests/test_searcher.py`, `tests/test_mcp_server.py`, `website/reference/mcp-tools.md` |
| **Search** | Move Stop-hook auto-save checkpoints to a dedicated `mempalace_session_recovery` ChromaDB collection so they're physically absent from `mempalace_search` rather than post-filtered. Promoted from "future work" to "necessary" by 2026-04-25 Cat 9 A/B (`kind=all` 632 tokens/Q vs `kind=content` 3 tokens/Q on 151K palace — over-fetch=100 still wasn't enough on a checkpoint-dominant corpus, the structural change is non-optional). New MCP tool `mempalace_session_recovery_read` reads the recovery collection by session_id, agent, since/until, wing, limit. **Phases A–D shipped** (collection adapter, write routing, new read tool, and the migration that moves existing topic=checkpoint drawers from main → recovery; idempotent, ID/metadata-preserving). Wired into `mempalace repair --mode reorganize` for explicit operator runs. PreCompact incorporated — `hook_precompact` now writes a session-recovery marker mirroring Stop, so context-compaction events leave a queryable timestamp in the recovery collection rather than nothing. **Phase E** (palace-daemon `lifespan` auto-migrate on startup) still deferred — cross-repo, separate go-ahead. Once the canonical 151K palace runs `--mode reorganize` and the Cat 9 A/B re-runs to show kind=all ≈ kind=content convergence, the kind= post-filter and over-fetch hack become deletable. | PR pending — fork commits [`e266365`](https://github.com/jphein/mempalace/commit/e266365) (A–C) → [`42817d7`](https://github.com/jphein/mempalace/commit/42817d7) (D + PreCompact + `mempalace repair --mode reorganize`), 18 new tests across `test_session_recovery.py` + `TestCheckpointRouting` + `TestSessionRecoveryRead` + `TestMigrateCheckpointsToRecovery`, design doc at [`docs/superpowers/specs/2026-04-25-checkpoint-collection-split.md`](docs/superpowers/specs/2026-04-25-checkpoint-collection-split.md), 12-task TDD plan at [`docs/superpowers/plans/2026-04-25-checkpoint-collection-split-impl.md`](docs/superpowers/plans/2026-04-25-checkpoint-collection-split-impl.md) | medium | medium | `palace.py`, `mcp_server.py`, `tests/test_session_recovery.py`, `tests/test_mcp_server.py`, `website/reference/mcp-tools.md` |
| **Performance** | Cherry-picked upstream [#1085](https://github.com/MemPalace/mempalace/pull/1085) (@midweste) — batch ChromaDB inserts in `miner.process_file()`. New `_build_drawer()` helper + `add_drawers()` batch-insert path; `process_file` now hands the full chunk list to `add_drawers` instead of looping per-chunk. Hoists `datetime.now()` and `os.path.getmtime()` so 1 syscall pair per file instead of 2N. ONNX embedding passes drop from N (one per chunk) to ⌈N/DRAWER_UPSERT_BATCH_SIZE⌉. Reported 10–30× mining speedup on a 70K-drawer / 499-file project upstream. Fork-side resolution: kept fork's existing `DRAWER_UPSERT_BATCH_SIZE=1000` value (more conservative than upstream's 5000 for embedding-pass memory headroom); aliased upstream's `CHROMA_BATCH_LIMIT` to it. | Cherry-picked from open upstream PR [#1085](https://github.com/MemPalace/mempalace/pull/1085) (@midweste, OPEN as of 2026-04-26, base=develop). Fork commit [`6be6fff`](https://github.com/jphein/mempalace/commit/6be6fff). Tracking upstream — becomes a no-op when #1085 merges and we next sync develop→main. We don't file a fork-side PR because the work is already proposed; we just credit @midweste and wait. | small | none | `mempalace/miner.py` |
| **Performance** | L1 importance pre-filter — `importance >= 3` first, full scan fallback | [#660](https://github.com/milla-jovovich/mempalace/pull/660) | small | low | `layers.py` |
| **Performance** | `miner.status()` paginates `col.get()` in 10 K-drawer batches — upstream's single `col.get(limit=total)` hits SQLite's max-variable limit on palaces with many thousands of drawers | tracked upstream in [#851](https://github.com/milla-jovovich/mempalace/pull/851) (merged 2026-04-22, also fixes #850 and #1015); fork's paginated version has been running since 2026-04-10 | small | low | `miner.py` |
| **Config** | Configurable chunking parameters — `chunk_size` (default 800 chars), `chunk_overlap` (100), `min_chunk_size` (50) written to `config.json` and exposed via `MempalaceConfig` properties | [#1024](https://github.com/milla-jovovich/mempalace/pull/1024) · addresses [#390](https://github.com/MemPalace/mempalace/issues/390) (default 800 exceeds MiniLM's 256-token cap; this lets users override) | small | low | `config.py`, `miner.py`, `convo_miner.py` |
| **Search** | Warnings + sqlite BM25 top-up when vector underdelivers — `search_memories` returns `warnings: [...]` and `available_in_scope: N` so callers see why recall was partial; fallback hits tagged `matched_via: "sqlite_bm25_fallback"`. The palace never silently returns fewer results than the scope contains (sibling of #951, addresses read-side of #823) | [#1005](https://github.com/milla-jovovich/mempalace/pull/1005) | medium | low | `searcher.py` |

## What this looks like in practice

A stop hook fires every 15 messages in Claude Code, writes directly to the palace via the Python API, and renders a terminal line so the user sees the save land:

```json
{
  "systemMessage": "✦ 13 memories woven into the palace — investigate, description, symlihjnk"
}
```

`search_memories` (via `mempalace_search` MCP tool) returns results with scope-authoritative context so callers can tell when the vector layer underdelivered:

```json
{
  "query": "kiyo xhci usb crash fix razer",
  "total_before_filter": 15,
  "available_in_scope": 137949,
  "warnings": [],
  "results": [
    {"wing": "projects", "room": "technical", "similarity": 0.859, "matched_via": "drawer", ...},
    {"wing": "kiyo-xhci-fix", "room": "technical", "similarity": 0.852, "matched_via": "drawer", ...}
  ]
}
```

On a palace where the HNSW index has drifted and vector can't rank everything, the same call would return `warnings: ["vector search returned 0 of 5 requested; filled 5 from sqlite+BM25 keyword match"]` and hits tagged `"matched_via": "sqlite_bm25_fallback"` — the data is never silently hidden.

The `kind=` parameter (default `"content"`) keeps Stop-hook auto-save checkpoints out of the result set — those are session-summary drawers that drown out substantive content under cosine similarity. Same query against the 151K-drawer canonical palace on 2026-04-25, side by side:

```
kind="all" (legacy):
  topic='checkpoint' room=diary sim=0.546 | CHECKPOINT:2026-04-25|session:11bb99a2-...
  topic='checkpoint' room=diary sim=0.357 | CHECKPOINT:2026-04-25|session:11bb99a2-...
  ... (5 of 5 results are checkpoints; available_in_scope=151,443)

kind="content" (default):
  topic=None room=configuration sim=0.61 | "...replaces stock firmware without..."
  topic=None room=realm_sigil   sim=0.58 | "# realm-sigil Rollout Implementation Plan..."
  ... (substantive content; available_in_scope=150,811)
```

The 632-drawer delta between `available_in_scope` values is the count of checkpoints the filter excludes — ~0.4% of corpus by count, but ~80%+ of search results before the filter. That's the impact ratio that matters for retrieval-then-grounding consumers (RLM, the familiar.realm.watch pipeline, ad-hoc queries).

## Why this fork exists

We surveyed the memory-system landscape in April 2026 and found no verbatim-first local system with MCP. Every alternative transforms content on write — extracted facts, knowledge graphs, tiered summaries — losing the original text.

Dates below are the earliest public marker we could find — either the first GitHub release tag or, where no release had been cut, the repository creation date. Treat as "roughly this month" rather than exact launch dates; pre-public development likely predates them.

| System | Verbatim? | Local? | MCP? | First public | Notes |
|---|---|---|---|---|---|
| **MemPalace** | Yes | Yes | Yes | 2026-04-06 (v3.0.0) | What we have. 165,632 drawers as of 2026-04-21. Verbatim drawers + wings/rooms scope + SQLite KG + BM25/vector hybrid search. |
| [Longhand](https://glama.ai/mcp/servers/Wynelson94/longhand) | Yes | Yes | Yes, 16-tool MCP | 2026-04-14 (v0.5.2; repo 2026-04-09) | Closest cousin. Claude Code-specific — reads `~/.claude/projects/*.jsonl` sessions directly. SQLite (raw JSON per event) + ChromaDB (embeddings of pre-computed "episodes"). Also does deterministic file-state replay via stored diffs. ~1.3MB/session; 170 tests; v0.5.13 as of 2026-04-21. ([Author writeup](https://dev.to/wynelson94/why-i-built-a-lossless-alternative-to-ai-memory-summarization-40cl).) |
| [Celiums](https://celiums.ai/) | Yes | Yes (SQLite, Docker, or DO) | Yes, 6-tool MCP | 2026-04-08 (repo; [MCP server](https://glama.ai/mcp/servers/terrizoaguimor/celiums-memory)) | Fellow verbatim-first. Stores full module text (2–20K words each) with PAD emotional vectors, importance scores, and circadian metadata. Bundles a 500K+ expert-module knowledge base alongside personal memory — a different product shape. |
| [mcp-memory-service](https://github.com/doobidoo/mcp-memory-service) (doobidoo) | Yes by default (opt-in consolidation) | Yes (SQLite) or cloud (Cloudflare Workers) | Yes | 2024-12-26 (repo; v10.28.2 current) | The long-standing verbatim option. "Turn-level storage (one entry per message)" preserves original text; MiniLM embeddings computed locally. Autonomous consolidation is opt-in, not default. Targets LangGraph / CrewAI / AutoGen plus Claude. |
| [Hindsight](https://github.com/vectorize-io/hindsight) | No — LLM extracts facts | Yes (Docker) | Yes | 2026-01-05 (v0.2.0; repo 2025-10-30) | Three ops: retain / recall / reflect. Original text is lost. |
| [Mem0](https://github.com/mem0ai/mem0) / [OpenMemory](https://github.com/mem0ai/mem0/tree/main/openmemory) | No — extracts "memories" | Partial | Yes | 2023-06 (repo) | Cloud-first; OpenMemory is the local-mode sibling. |
| [Cognee](https://github.com/topoteretes/cognee) | No — knowledge graph | Yes | Yes (added since we wrote this row) | 2023-08 (repo) | "Knowledge Engine" via ECL pipeline. |
| [Letta](https://github.com/letta-ai/letta) | No — tiered summarization | Yes | No | 2023-10 (as MemGPT) | Formerly MemGPT. Rebrand kept the repo. |
| [engram](https://github.com/NickCirv/engram) | Structured fields, not raw | Yes | Yes | 2026-04-11 (v0.3.0; repo 2026-04-09) | Go + SQLite FTS5. |
| [CaviraOSS OpenMemory](https://github.com/CaviraOSS/OpenMemory) | No — temporal graph | Yes | Yes | 2025-10-26 (v1.0.0) | SQL-native. |

The April-2026 verbatim cluster (MemPalace, Celiums, Longhand, engram all within ~8 days) is striking — it suggests the "store it raw and retrieve well" pattern reached independent critical mass right around the same time. mcp-memory-service has been doing verbatim-by-default since late 2024; it just wasn't the loudest of the memory projects. Sweeps for `thedotmack/claude-mem`, `ukkit/memcord`, `itsjwill/claude-memory`, `DeusData/codebase-memory-mcp`, and `mkreyman/mcp-memory-keeper` turned up systems that *compress with AI*, explicitly summarize, or build knowledge graphs — not verbatim peers.

**Verbatim storage is the differentiator.** For recovering exact commands, error messages, code snippets, and what someone actually said, you need the original text. Everything else — hierarchy, tags, knowledge graphs, decay — is enrichment *layered on top of* a faithful archive. If any of those layers fails or needs rebuilding, the underlying truth is still there.

A small cohort of systems has independently arrived at the same call — verbatim retention as the foundation, enrichment layered on top — which is encouraging corroboration of the architectural principles below. Where they diverge is the second product axis: **scope** and **source**.

- **MemPalace** (this fork) — personal, mines anything the user points it at (project files, JSONL transcripts, export bundles) into wings/rooms/drawers. Hybrid BM25 + vector search; AAAK optional enrichment layer.
- **[Longhand](https://glama.ai/mcp/servers/Wynelson94/longhand)** — personal, Claude Code sessions only. Stores raw event JSON per tool call, precomputes "episodes" for semantic retrieval, offers deterministic file-state replay via stored diffs. Narrower input, deeper per-session structure.
- **[Celiums](https://celiums.ai/)** — personal *plus* a bundled 500K-module expert knowledge base. Adds PAD emotional vectors and circadian metadata to each memory. Two corpora, shared search interface.
- **[mcp-memory-service](https://github.com/doobidoo/mcp-memory-service)** — agent-pipeline-oriented (LangGraph, CrewAI, AutoGen). Turn-level storage by default, opt-in autonomous consolidation for older memories.

These are reasonable, non-overlapping answers to "what is memory *for*." Worth being explicit about our scope so users pick the right tool: MemPalace is **personal verbatim archive, any source the user mines, MCP-accessible**, full stop.

(A note on positioning: Longhand's public page happens to group MemPalace with "summary-based tools." That's inaccurate — we've been verbatim-first from the beginning, it's architectural principle 1. The mischaracterization is worth flagging because it suggests "verbatim memory" isn't yet a legible category in the broader discourse. The more of us that make the shared call explicit, the less confusion downstream.)

## Architectural principles

Three principles that emerged from 152K drawers of production use. They explain most of this fork's decisions and should guide future ones. Contributors: use these to evaluate PRs.

### 1. Forced transforms on write are the enemy

Every operation that *requires* interpreting content at write time is a failure surface. Entity detection misfires. Classifiers force wrong rooms. LLM-extracted "facts" lose nuance and can't be un-extracted. Many of this fork's visible bugs (`room=None` crashes, a stopword list that's grown to [285 English entries and counting](mempalace/i18n/en.json) to paper over false positives, wing misassignment) trace to a single mistake: making classification a *gate* instead of a best-effort enrichment.

Write the raw text. Derive everything else lazily, from unambiguous signals, with a graceful fallback when derivation fails. The verbatim archive is the one thing that must always succeed. Optional enrichment modes (LLM topic extraction, AAAK encoding, concept chunking) are welcome as long as they are exactly that — opt-in, additive, and never a prerequisite for the write to complete.

### 2. Hierarchy as optional scope, not required metadata

Hierarchy isn't wrong — *mandatory synchronous classification* is wrong. Those are different claims, and conflating them was our earlier mistake.

**Good uses of hierarchy, which we keep:**
- **Browseable scope** for serendipitous recall across 152K drawers. Search answers "when did I hit this error"; browse answers "what was I working on last November."
- **Deletion and retention as a unit.** Purging drawers from an abandoned experiment is one operation, not a risky query-then-delete with collateral damage.
- **Disambiguation without query gymnastics.** The same keyword appears in unrelated contexts across years of work. Scope separates them by default.
- **Auto-surfacing priors.** A wing derived from the current working directory is a cheap, unambiguous signal for what to search first. This matters for the open problem below.

**Bad uses of hierarchy, which we're unwinding:**
- Required at write time (what caused all the crashes).
- Derived from content-inspection heuristics — NER, keyword matching, stopword filtering — rather than unambiguous signals.
- Single-label, as if every drawer had one true parent. Cross-cutting concerns belong in tags (P0).
- Deep nesting when shallow would do.

Filesystems, Gmail, and Notion all pair hierarchy with tags and derive hierarchy from unambiguous signals (drop location, sender rules, database parent). We're converging on the same pattern.

### 3. Retrieval is the investment, not classification

Search quality compounds. Classification quality has a hard ceiling set by the accuracy of the classifier, and ours isn't good enough to justify the complexity it imposes. Vector + BM25 + optional scope filter already beats anything the hierarchy provides on its own. Tags (P0) extend this without requiring write-time commitment. Feedback loops (P3) and decay (P2) extend it further.

Effort spent tuning the entity detector is effort not spent on the thing that actually pays compounding returns.

## Two-layer memory model

Claude Code has two complementary memory layers, used in tandem:

| Layer | Storage | Size | Consolidation | Purpose |
|---|---|---|---|---|
| **Auto-memory** | `~/.claude/projects/*/memory/*.md` | 17 files (this project) | None (manual writes) | Preferences, feedback, context |
| **MemPalace** | palace-daemon at `http://disks.jphe.in:8085` (ChromaDB on the daemon host) | 151K+ drawers | None (write-only archive) | Verbatim conversations, tool output, code |

Neither has automatic consolidation. Claude Code has unreleased "Auto Dream" consolidation code behind a disabled feature flag ([anthropics/claude-code#38461](https://github.com/anthropics/claude-code/issues/38461)) — if it ships, it covers only the lightweight layer. MemPalace decay (P2) and feedback (P3) remain the right priorities for the verbatim archive.

## Ecosystem — third-party projects, forks, and evaluation frameworks

From a 2026-04-21 sweep of upstream MemPalace issue + comment + discussion history. State moves; check the repos directly for current status. Projects here are grouped by how they relate to MemPalace, not by quality.

### Companion tools (compose with MemPalace, don't replace it)

- **[palace-daemon](https://github.com/rboarescu/palace-daemon)** (@rboarescu) — FastAPI gateway + MCP-over-HTTP proxy. Three asyncio semaphores (read / write / mine) with a dedicated mine lane so bulk imports can't starve interactive queries. Explicitly pins correctness floor at MemPalace ≥3.3.2. **This fork migrated to palace-daemon on 2026-04-24** (commits [`c09582c`](https://github.com/jphein/mempalace/commit/c09582c) wired MCP + hooks; [`0e97b19`](https://github.com/jphein/mempalace/commit/0e97b19) added daemon-strict mode that skips local writes when `PALACE_DAEMON_URL` is set). All reads and writes from the plugin now flow through the daemon; see the "Multi-client coordination" section below for the architecture and what's deferred. JP's deployment runs at [`jphein/palace-daemon`](https://github.com/jphein/palace-daemon).
- **[engram](https://github.com/NickCirv/engram)** (@NickCirv) — File-read interception for AI coding assistants. Uses MemPalace as one of six context providers at session start via `mcp-mempalace mempalace-search`; caches with 1h TTL. Referenced in upstream [discussion #798](https://github.com/MemPalace/mempalace/discussions/798).
- **[engram](https://github.com/harreh3iesh/engram)** (@harreh3iesh — different project, same name) — Hooks + tools for AI memory, first-class MemPalace backend. Notable pattern: a **stuck detector** (`PreToolUse` hook that counts Grep/Glob calls and nudges the AI when it's spinning). Upstream [discussion #748](https://github.com/MemPalace/mempalace/discussions/748).
- **[cdd-mempalace](https://github.com/fuzzymoomoo/cdd-mempalace)** (@fuzzymoomoo) — Bridge library mapping Context-Driven Development methodology onto MemPalace's wings/halls/rooms structure. Ships `MAPPING.md` + engineering-memory examples. Multiple active upstream PRs (test coverage, Windows fixes, docs). fuzzymoomoo is probably the most-invested production user after us — see upstream discussions [#765](https://github.com/MemPalace/mempalace/discussions/765), [#891](https://github.com/MemPalace/mempalace/discussions/891), [#910](https://github.com/MemPalace/mempalace/discussions/910).

### Evaluation frameworks

- **[multipass-structural-memory-eval](https://github.com/M0nkeyFl0wer/multipass-structural-memory-eval)** (@M0nkeyFl0wer) — Nine-category diagnostic framework for memory systems. Most-referenced external project across upstream comments (27 mentions). **"Category 9: The Handshake"** explicitly tests *integration under production model usage*, not just offline retrieval — which is a gap our LongMemEval numbers don't close. Delta-focused methodology (measures improvement between versions rather than absolute scores). Forked at [jphein/multipass-structural-memory-eval](https://github.com/jphein/multipass-structural-memory-eval). **Roadmap entry: build a `mempalace-daemon` adapter** that talks HTTP/MCP only instead of opening ChromaDB directly — the shipped `sme/adapters/mempalace.py` opens a parallel `PersistentClient` against the same palace path the daemon serves, which violates the daemon-strict single-writer invariant from commit `0e97b19`. Once the daemon-aware adapter exists, run Cat 9 A/B with `kind="all"` (legacy default) vs `kind="content"` (new default) — that lets SME's framework verdict, rather than our own A/B harness, deliver the engram-2-critique-response number. Multi-hour build, not yet started; tracked at [jphein/multipass-structural-memory-eval `7df3572`](https://github.com/jphein/multipass-structural-memory-eval/commit/7df3572).

### Adjacent / competing memory systems with concrete technical differences

- **[agentmemory](https://github.com/rohitg00/agentmemory)** (@rohitg00) — Persistent memory for AI coding agents, BM25 + vector hybrid. Reports **95.2% R@5** on LongMemEval-S with the same `all-MiniLM-L6-v2` embedding model. Filed a benchmark methodology review in upstream [discussion #747](https://github.com/MemPalace/mempalace/discussions/747) that's worth reading before publishing any head-to-head numbers.
- **[engram-2](https://github.com/199-biotechnologies/engram-2)** (@199-biotechnologies — a third, unrelated engram) — Rust CLI memory system, deterministic, SQLite + FTS5 only (no vector DB). Hybrid retrieval via Gemini embeddings + FTS5 through reciprocal rank fusion. Claims **0.990 R@5** on LongMemEval (vs MemPalace's 0.984) with no reranking, and reports **MemPalace's end-to-end QA accuracy as 17%** — a concrete critique flagged for investigation below. "Memory layer budgeting" (identity / critical / topic / deep tiers with token accounting) is a pattern worth studying.
- **[Tiro (project-tiro)](https://github.com/esagduyu/project-tiro)** (@esagduyu) — Local-first reading OS for the AI age. Same data-spine architecture as MemPalace (FastAPI + ChromaDB + SQLite + sentence-transformers + Anthropic API + MCP server) but with a *curated* input domain: web pages and email newsletters saved as clean markdown, instead of mined from chat transcripts. Opus 4.6 generates ranked daily digests across topics/entities, finds contradictions between sources, learns reading preferences (must-read / summary-enough / discard tiers); Haiku 4.5 does lightweight enrichment (tags, entities, summaries) on every save. Ships a d3.js force-directed knowledge graph, OpenAI TTS streaming, and a 7-tool MCP server for Claude Desktop / Code integration. Built solo for the Cerebral Valley × Anthropic *Built with Opus 4.6* hackathon (Feb 10–16 2026). Forked at [jphein/project-tiro](https://github.com/jphein/project-tiro) 2026-04-10. **Architectural twin to MemPalace's auto-mine-everything approach** — same stack, different input shape: curated saves vs auto-archived transcripts. Worth comparing E2E QA on each: does a smaller curated domain beat a large verbatim everything-archive for question-answering? An interesting eval that would inform our P1 (derive-hierarchy-from-unambiguous-signals) prioritization.
- For the broader verbatim-first cohort (Longhand, Celiums, mcp-memory-service), see the "Why this fork exists" table above.

### Adjacent inference paradigms (different layer than memory storage)

- **[RLM (Recursive Language Models)](https://github.com/alexzhang13/rlm)** (@alexzhang13, MIT OASYS) — Task-agnostic inference paradigm where the LM offloads its context as a variable in a REPL environment and recursively decomposes / examines / sub-calls itself over the input. Replaces the canonical `llm.completion(prompt, model)` with `rlm.completion(prompt, model)`. Targets near-infinite context length without hitting the model's window; the LM programmatically examines its own input rather than receiving it inline. Backed by the [Dec 2025 arXiv preprint](https://arxiv.org/abs/2512.24601) (Zhang/Kraska/Khattab) and an [Oct 2025 blogpost](https://alexzhang13.github.io/blog/2025/rlm/). Forked at [jphein/rlm](https://github.com/jphein/rlm) 2026-04-25; integration example shipped at [`examples/mempalace_demo.py`](https://github.com/jphein/rlm/blob/main/examples/mempalace_demo.py). **Smoke-tested 2026-04-25 against the canonical 151K-drawer palace** via Foundry gpt-5.3-chat: RLM autonomously chose to call `mempalace_search` from the docstring alone, returned cited answers in 4 iterations / ~23s. *That same test is what surfaced the checkpoint-noise problem* the fork's `kind=` filter now solves. Composition pattern (per familiar.realm.watch's v0.3 spec): RLM as outer orchestrator, MemPalace's `mempalace_search` and familiar's `/v1/chat/completions` as its tools — not a replacement for either, but a way to compose decomposition with deterministic grounding.
- **[ASI-Evolve](https://github.com/GAIR-NLP/ASI-Evolve)** (@GAIR-NLP) — Closed-loop autonomous research agent: knowledge → hypothesis → experiment → analysis, repeated until convergence. Three-agent architecture (Researcher proposes, Engineer executes, Analyzer distills lessons) plus **two parallel memory systems**: a **Cognition Store** (upfront domain knowledge — papers, heuristics, prior approaches) and an **Experiment Database** (every trial stored with motivation/code/result/analysis, parent selection via UCB1 / greedy / random / MAP-Elites island sampling). Validated on neural architecture design (+0.97 over DeltaNet — ~3× recent human gains), pretraining-data curation (+18 pts MMLU), RL algorithm design (+12.5 pts AMC32 vs GRPO), and biomedical drug-target interaction (+6.94 AUROC). [arXiv 2603.29640](https://arxiv.org/abs/2603.29640). Forked at [jphein/ASI-Evolve](https://github.com/jphein/ASI-Evolve) 2026-04-25. **Architectural pair with MemPalace:** the Cognition Store is exactly the role MemPalace would play in such a loop — verbatim local archive of prior knowledge that the Researcher agent reads before proposing the next candidate. The Experiment Database is structurally identical to MemPalace's wings/rooms/drawers (a verbatim archive of trial artifacts) just with a tighter retrieval policy (UCB1 over score signal vs cosine over embedding). Worth investigating: can MemPalace's `mempalace_search` serve as the Cognition Store interface, and can our drawer-id citations replace ASI-Evolve's separate trial-record store? More directly than RLM's "outer orchestrator" framing, ASI-Evolve provides a *named consumer pattern* for memory — the Researcher agent — instead of asking the model to discover when to retrieve.

### MemPalace-orbit projects (peer builds, not competitors)

These are projects built *on top of* or *alongside* MemPalace, by community contributors who use the palace as a substrate for something else. Distinct from companion tools (which compose) and from competitors (which replace) — these are *peer products*.

- **[GraphPalace](https://github.com/web3guru888/GraphPalace)** (@web3guru888) — graph-layer build on the MemPalace data spine. Forked at [jphein/GraphPalace](https://github.com/jphein/GraphPalace) 2026-04-22.
- **[mempalace-viz](https://github.com/JoeDoesJits/mempalace-viz)** (@JoeDoesJits) — visualization layer for palace state — wings, rooms, tunnels, drawer counts. HTML/JS frontend. Forked at [jphein/mempalace-viz](https://github.com/jphein/mempalace-viz) 2026-04-20.
- **[AutomataArena](https://github.com/astrutt/AutomataArena)** (@astrutt) — orchestration substrate that uses MemPalace as a memory layer for multi-agent environments. Forked at [jphein/AutomataArena](https://github.com/jphein/AutomataArena) 2026-04-22.

These are early-stage and worth following for cross-pollination ideas. They share the underlying ChromaDB + SQLite data shape, so any retrieval-quality fix we ship (the `kind=` filter, future P0 tags, etc.) automatically benefits them when they re-pull the fork.

### Active forks beyond ours

As of 2026-04-21, the upstream MemPalace repo has **6,386 forks**. The ones below appear in upstream PR / issue comments with meaningful divergence or contribution activity:

| Fork | Contributor work |
|---|---|
| [jphein/mempalace](https://github.com/jphein/mempalace) | this fork |
| [fuzzymoomoo/cdd-mempalace](https://github.com/fuzzymoomoo/cdd-mempalace) | 10 comment refs; CDD integration layer, multiple upstream PRs |
| [potterdigital/mempalace](https://github.com/potterdigital/mempalace) | author of upstream's [#1081](https://github.com/MemPalace/mempalace/pull/1081) (HNSW repair hint for filtered queries) |
| [vnguyen-lexipol/mempalace](https://github.com/vnguyen-lexipol/mempalace) | author of upstream's [#851](https://github.com/MemPalace/mempalace/pull/851) (miner.status pagination) |
| [messelink/mempalace](https://github.com/messelink/mempalace), [FabioLissi/mempalace](https://github.com/FabioLissi/mempalace) | multiple comment refs each; relationship unclear, listed for completeness |
| [Kushmaro/memcitadel](https://github.com/Kushmaro/memcitadel) | renamed fork; positioning unclear |

## Fork Changes

Merged history below. For what's in flight or pending, see the top-of-README "Fork change queue."

### Merged upstream (post-v3.3.1)

**Merged 2026-04-22 (Ben's batched queue-clear pass at 00:38 UTC):**

- Graph cache with write-invalidation — `build_graph()` module-level cache with 60s TTL, `threading.Lock`, `invalidate_graph_cache()` on writes ([#661](https://github.com/milla-jovovich/mempalace/pull/661))
- Deterministic hook saves — silent mode via direct Python API call to `tool_diary_write()`, plain-text save, marker advances only after confirmed write, `systemMessage` terminal notification; config-flag-gated, strictly safer save semantics than the legacy block-mode "ask AI to save" pattern ([#673](https://github.com/milla-jovovich/mempalace/pull/673), closes #854)
- Hook `silent_save` guard + `_output()` stdout routing — silent-mode skips `stop_hook_active` guard so Claude Code 2.1.114 plugin dispatch keeps firing; `_output()` reuses already-loaded `mcp_server`'s `_REAL_STDOUT_FD` or writes directly to fd 1 to avoid cold-import side effects ([#1021](https://github.com/milla-jovovich/mempalace/pull/1021))
- `miner.status()` pagination — upstream's own fix for the `SQLITE_MAX_VARIABLE_NUMBER` crash on large palaces; triage sweep surfaced three-user confirmation data (#1015, #1016, sha2fiddy thread) that prioritized the merge over the superseded #1016 ([#851](https://github.com/milla-jovovich/mempalace/pull/851), closes #802/#850/#1015)

**Merged earlier:**

- `None`-metadata guards across 8 read-path loops — `searcher.py` (CLI + API + closet-boost), `miner.status()`, and 4 MCP handlers ([#999](https://github.com/milla-jovovich/mempalace/pull/999), merged 2026-04-18)

**Released in [v3.3.2](https://github.com/MemPalace/mempalace/releases/tag/v3.3.2) on 2026-04-21:**

- `quarantine_stale_hnsw()` helper — renames HNSW segments whose `data_level0.bin` is 1h+ older than `chroma.sqlite3`, sidesteps read-path SIGSEGV ([#1000](https://github.com/milla-jovovich/mempalace/pull/1000), closes #823)
- PID file guard prevents stacking `mempalace mine` processes on every hook fire ([#1023](https://github.com/milla-jovovich/mempalace/pull/1023)), with a cross-platform PID-check fix (`os.kill(pid, 0)` on Windows *terminates* the target — replaced with `ctypes` `OpenProcess`/`GetExitCodeProcess`). Broader complementary work in [#976](https://github.com/milla-jovovich/mempalace/pull/976) covers direct-CLI fan-out + an HNSW `num_threads` pin.
- Unicode checkmark replaced with ASCII `+` for Windows encoding ([#681](https://github.com/milla-jovovich/mempalace/pull/681), closes #535)

### Merged upstream (in v3.3.0)

- BLOB seq_id migration repair (#664)
- `--yes` flag for init (#682)
- Unicode `sanitize_name` (#683)
- VAR_KEYWORD kwargs check (#684)
- New MCP tools + export (via #667)

### Pulled in from upstream v3.3.1

Six changes landed on fork via the upstream merge: multi-language entity detection, BCP-47 locales, script-aware word boundaries, UTF-8 read encoding, non-blocking precompact hook (#863), and basic `silent_save` honoring (#966 — narrower than our fork's deterministic-save architecture, so we keep the fork version). See [upstream v3.3.1 release notes](https://github.com/MemPalace/mempalace/releases/tag/v3.3.1) for details.

### Superseded by upstream

- Hybrid keyword fallback (`$contains`) — upstream shipped Okapi-BM25 (60/40 blend) via [#789](https://github.com/milla-jovovich/mempalace/pull/789)
- Batch ChromaDB writes — upstream has file-level locking for concurrent agents via [#784](https://github.com/milla-jovovich/mempalace/pull/784)
- Inline transcript mining in hooks — upstream uses `mempalace mine` in background
- Stale HNSW mtime detection — upstream took a different approach in [#757](https://github.com/milla-jovovich/mempalace/pull/757); fork's broader inode+mtime detection and `mempalace_reconnect` MCP tool stay as fork-local convenience

## Planned work

Ordered by impact. Informed by competitive research ([Karta](https://github.com/rohithzr/karta), Hindsight, [engram](https://github.com/NickCirv/engram), [context-engine](https://github.com/Emmimal/context-engine), CaviraOSS) and our own usage patterns — see [Sources](#sources) at the bottom for the full reference list. Each item is evaluated against the three principles above.

### P0 — Multi-label tags *(1-2 days, additive, upstream candidate)*

Tags are the cross-cutting-concerns layer that hierarchy can't provide. A conversation about ChromaDB HNSW debugging gets `chromadb, hnsw, sqlite, python, testing` tags *and* lives in its project wing — the two aren't mutually exclusive. Modern memory systems (Hindsight, Mem0, CaviraOSS) converged on multi-label tagging because content is inherently multi-faceted while hierarchy is inherently single-parent.

Add `tags` metadata (3-8 per drawer, extracted during mining via TF-IDF or longest-non-stopword heuristic — we already have `_extract_keyword` in `searcher.py`). ChromaDB `where_document` and metadata `$contains` handle the query. This is additive: drawers still get a wing when derivation is unambiguous, and now they also get content tags for cross-wing retrieval.

**Optional LLM enrichment layer (opt-in, additive):** Milla Jovovich's production setup adds a parallel Haiku pass at index time — Haiku reads each session and writes a short synthetic document ("Session topics: yoga, Tuesday routine. Summary: …") stored alongside the verbatim drawer. The verbatim is untouched; the topic doc improves semantic routing without replacing it. This maps directly onto the tag approach: the Haiku-extracted topics become the tag values. Benchmark: heuristic-tagged baseline scores 96.6% R@5 on LongMemEval; Haiku-enriched scoring is competitive before rerank. Implement as an opt-in `--enrich` flag on `mempalace mine` that calls Haiku per session and appends topic metadata. No API key required for the default path.

**Upstream signal:** [#1033](https://github.com/milla-jovovich/mempalace/pull/1033) (`<private>` tag filter + progressive disclosure, @zackchiutw, MERGEABLE) is adjacent — it adds a single-purpose privacy tag, not the full multi-label scheme. P0 would still be additive on top of it.

### P1 — Derive hierarchy from unambiguous signals *(half day)*

Reframe from "best-effort classification" to "derive from what we actually know." The cwd at write time, the transcript file path, the project directory — these are unambiguous. Entity detection on drawer content is not.

Changes:
- Default wing to source directory name — already mostly works; make it the primary path.
- Room assignment becomes optional metadata; never crash on `room=None`.
- Demote the entity detector to a last-resort hint, not a gate. Classification failure never blocks a write.
- Document the derivation order explicitly: cwd → transcript path → project hint → (optional) entity hint → unfiled.

This preserves hierarchy's benefits (scope, browse, delete-as-unit) while eliminating the failure surface that caused most of this fork's bugs. It's principle 1 and principle 2 made concrete.

### P2 — Decay / recency weighting *(tracked upstream — do not duplicate)*

**Status 2026-04-19: handled by [#1032](https://github.com/milla-jovovich/mempalace/pull/1032)** (@zackchiutw, MERGEABLE, filed 2026-04-19). Ships a config-driven 4-stage rerank pipeline with **Weibull time-decay** as one stage — exactly this item's intent. All stages off by default; opt-in via `~/.mempalace/config.json`. Watch that PR; no fork work needed unless it stalls.

Older implementation of the same idea: [#337](https://github.com/milla-jovovich/mempalace/pull/337) (@matrix9neonebuchadnezzar2199-sketch, simpler half-life decay, stale since 2026-04-14).

Independent `mempalace prune --stale-days 180 --dry-run` CLI is still a fork opportunity (#1032 doesn't touch pruning).

### P3 — Feedback loops *(rerank tracked upstream; rating/reflection still open)*

**Tier 0 (LLM rerank) status: also covered by [#1032](https://github.com/milla-jovovich/mempalace/pull/1032)** — the pipeline's final stage is an optional Anthropic-API rerank pass. Milla's production `longmemeval_bench.py` already validates the approach: 96.6% R@5 baseline → **99.4% with Haiku rerank**, ~$0.001 per question.

Tier 1+ still open upstream: `mempalace_rate_memory(drawer_id, useful: bool)` MCP tool, implicit echo/fizzle signals, Hindsight-style "reflect" synthesis. These remain viable fork or upstream contributions independent of #1032.

**Alternative importance-scoring reference — [Celiums](https://celiums.ai/):** combines novelty (habituation dampens repeats), emotional intensity (PAD vectors), and circadian context (peak-cognitive-hour weighting) into a per-memory 0.0–1.0 score. More axes than pure recency decay, and the score is stored alongside the verbatim drawer rather than being a query-time rerank. Worth reading before designing our rating-signal schema — we don't need the full brain-inspired module stack, but the separation between *stored* importance (novelty at write time) and *queried* ranking (relevance + recency + feedback) is a useful distinction we haven't made explicit yet.

### P4 — KG auto-population + entity resolution *(1.5 days)*

The knowledge graph has 5 MCP tools and a SQLite backend but ~zero data. Hooks should extract `subject/predicate/object` triples on every save using heuristics (no LLM — `project → has_file → path`, `session → discussed → room` patterns). Normalize entity IDs (lowercase, strip punctuation, collapse whitespace). Alias table + Levenshtein < 2 for fuzzy matches. Prerequisite for contradiction detection.

Triples are **derived** from the verbatim archive, not parallel to it. If extraction improves later, re-mine — the source of truth is untouched. Same principle that makes P0 and P1 safe: stable underlying drawers, rebuildable enrichment.

### P5 — Temporal fact validity *(1 day, depends on P4)*

KG triples get a context slot (SPOC: subject-predicate-object-context) rather than only `valid_from` / `valid_to` columns. Context acts as a namespace — `(LeBron, played_for, Beavers, "2023_season")` vs `(LeBron, played_for, Lakers, "2022_season")` — making contradiction detection "same S+P, different O, overlapping contexts" rather than timestamp-range logic. On write, close any existing triple with the same subject+predicate+context before opening a new one. Reference: Zep's [Graphiti](https://github.com/getzep/graphiti) temporal graph model.

### P6 — Input sanitization on writes *(half day)*

Strip known injection patterns (role-play instructions, "ignore previous instructions"). Flag with `sanitized: true` metadata rather than blocking. Length cap at 10K chars. Low priority while we're local-only; matters if the MCP server is ever exposed more broadly.

### P7 — Alternative storage modes *(tracked upstream — do not duplicate)*

**Status 2026-04-19: dropped as fork work.** Upstream has a formal design artifact and four in-flight backend implementations. Fork tracks this, does not rebuild it:

- [#743 — RFC 001: storage backend plugin specification](https://github.com/milla-jovovich/mempalace/pull/743) (@igorls, filed 2026-04-12, 587-line spec, single file). Defines entry-point group `mempalace.backends`, typed `QueryResult` / `GetResult` dataclasses, `PalaceRef(id, local_path?, namespace?)` for daemon-first multi-palace model, `where_document` contract. Designed to unblock all downstream backend PRs.
- [#700 — Qdrant backend](https://github.com/milla-jovovich/mempalace/pull/700) (@RobertoGEMartin)
- [#381 — Qdrant vector search](https://github.com/milla-jovovich/mempalace/pull/381) (@Anush008, earlier competing implementation)
- [#574 — LanceDB abstraction + migration path](https://github.com/milla-jovovich/mempalace/pull/574) (@dekoza)
- [#575 — LanceDB multi-device sync](https://github.com/milla-jovovich/mempalace/pull/575) (@dekoza, builds on #574)

### Deprioritized

- **Expanding hierarchy types** (tunnels, closets, new room categories). Adding more categories doesn't address the write-time classification problem. Tags (P0) and derived scope (P1) do.
- **Benchmark work** — our value is "152K drawers of verbatim local history with fast search," not upstream's LongMemEval score.
- **Full architecture rewrite** — not worth the migration cost.
- **Dual-granularity ANN, dream engine, foresight signals** — [Karta](https://github.com/rohithzr/karta)-inspired features that require LLM calls on every write. Our zero-LLM philosophy makes these opt-in at best.
- **FTS5 parallel index** — right idea (engram proves it), but significant infrastructure alongside ChromaDB. Revisit after tags and decay are proven.

## Active investigations

### Verifying engram-2's "17% end-to-end QA" critique of MemPalace

[engram-2](https://github.com/199-biotechnologies/engram-2) published a benchmark note stating MemPalace achieves 0.984 R@5 on LongMemEval but **only 17% end-to-end question-answering accuracy**. If true, it's the sharpest competitive critique in the space: retrieval recall doesn't translate to answer quality. Possible explanations range from "their downstream prompting is unusually strict" to "MemPalace's result formatting genuinely degrades LLM interpretation." Either way, publishing R@5 without an E2E number leaves the fork exposed to this framing. Running LongMemEval-S end-to-end through our fork against a modern reader model and reporting the delta is cheap (a few hours) and would either close the gap (methodology) or surface a real consumption problem we haven't measured.

**2026-04-25 update — partial root-cause identified.** Smoke-testing [RLM](https://github.com/jphein/rlm) (Recursive Language Models, Zhang/Kraska/Khattab arXiv 2512.24601) as a MemPalace consumer surfaced that **80%+ of `mempalace_search` results were Stop-hook auto-save checkpoints** — short word-dense session summaries that consistently outranked substantive content under cosine similarity. RLM autonomously called the search tool, parsed the JSON, and produced a confident-but-misleading answer because every result it had was a CHECKPOINT diary entry rather than the actual conversation those entries summarized. This is *one specific shape* of the engram-2 critique: high R@5 (the relevant docs are findable) but low E2E (the LLM grounds on the wrong drawer-shape and answers from summaries instead of content). The fork's `kind="content"` filter (commit `8d02835`, the table row above) addresses this slice. Whether it materially closes the 17% gap is now testable — re-running the same RLM smoke test with `kind="content"` returned substantive content drawers and answer quality jumped accordingly. The remaining gap (if any) likely traces to the chunk-size/embedding-model truncation pair (#390, #1024) and/or the absence of a knowledge-graph-anchored answer layer (P4). LongMemEval-S E2E still pending; the kind= fix lowers the floor.

### Multi-palace separation — curated "authority" vs auto-mined "chat memory"

@kostadis raised this in upstream [discussion #1018](https://github.com/MemPalace/mempalace/discussions/1018): they want a **manually curated palace** (canonical docs, no auto-hooks) alongside the existing chat-memory palace (auto-mined from transcripts). Our fork's hooks dump everything into a single palace, which pollutes curated content. This intersects with Row 5 (hook opt-out) but is a structural request, not a settings one — the right fix is multi-palace support with a per-hook target flag. Not filing a PR-candidate row yet because the feature needs design review (does it fit mempalace's single-`palace_path` model? does it want a `palace_name` / alias layer? who owns the routing decision at query time?). Candidate for a P-level roadmap item once we've thought it through.

### Auto-surfacing context Claude doesn't know to ask for

Claude frequently makes wrong assumptions when the correct info exists in MemPalace, because it doesn't know to search. This is a **consumption problem, not a storage problem** — the write path (hooks, mining) is solid; the read path works when triggered. The gap is automatic surfacing at the moment of need.

What didn't work: SessionStart pre-loading, auto-memory bridges, PreCompact re-reads, CLAUDE.md instructions to "always query mempalace." What might work: [engram](https://github.com/NickCirv/engram)-style file-read interception that injects MemPalace context alongside code structure ([discussion #798](https://github.com/MemPalace/mempalace/discussions/798)). Only covers code-level assumptions, not workflow/config.

P1's cwd-derived wings are relevant here: once wings are derived from unambiguous signals, they become a cheap scoping prior for any automatic surfacing mechanism. "Claude is in `/Projects/mempalace`; query that wing first" is a lot cheaper than training a router. No memory system has solved this well — it's the unsolved problem of the [OSS Insight Agent Memory Race](https://ossinsight.io/blog/agent-memory-race-2026).

**2026-04-25 — RLM as a candidate solution.** [Recursive Language Models](https://github.com/jphein/rlm) (Zhang/Kraska/Khattab) flip the framing: instead of "make Claude remember to search," give the LM a REPL with `mempalace_search` exposed as a Python callable and let it **decide when to recurse + retrieve**. Smoke-tested 2026-04-25 on Foundry gpt-5.3-chat against the canonical 151K-drawer palace via [palace-daemon](https://github.com/jphein/palace-daemon)'s HTTP search route. Result: RLM autonomously chose to call `mempalace_search`, picked sensible queries from a docstring alone (no prompt engineering), parsed JSON, produced cited answers in 4 iterations / ~23s. Caveat: RLM is sensitive to model selection in unobvious ways — gpt-5.5 (newer) refused to use the tool and hallucinated "I don't have access to that," while gpt-5.3-chat (older, simpler) doggedly recursed. Useful but not a silver bullet for local 3B/7B models. Reference example: [`jphein/rlm:examples/mempalace_demo.py`](https://github.com/jphein/rlm/blob/main/examples/mempalace_demo.py). Long-form architectural take in [`jphein/familiar.realm.watch`](https://github.com/jphein/familiar.realm.watch) v0.3 spec — composition pattern is *RLM as outer orchestrator, familiar's deterministic pipeline as one of its tools*, not a replacement for either.

### Multi-client coordination — palace-daemon now primary, fork-ahead lock retired

Several users have hit the "multiple clients hammering one palace" pattern — @worktarget's #904 report, the ChromaDB concurrency family in #357 / #521 / #832, and the multi-machine case (laptop → home server palace). The core problem: Claude Code spawns one `mcp_server.py` per open terminal; stop hooks spawn additional short-lived writers (diary writes, `mempalace mine` subprocesses). All open independent `PersistentClient` instances against the same palace directory. ChromaDB has no inter-process write locking; concurrent `col.add/upsert/update/delete` from N processes corrupts the HNSW segment, causing the next read to SIGSEGV in `chromadb_rust_bindings`.

The actual root cause was traced upstream in [#974](https://github.com/MemPalace/mempalace/issues/974) / [#965](https://github.com/MemPalace/mempalace/issues/965): ChromaDB's multi-threaded `ParallelFor` HNSW insert path races in `repairConnectionsForUpdate` / `addPoint`, corrupting the graph even within a single process. Without `hnsw:num_threads: 1` pinned at collection creation, the race produces runaway writes to `link_lists.bin` — observed at 437 GB on this fork's 135K-drawer palace, 1.5 TB on a Nobara install in [#976](https://github.com/MemPalace/mempalace/pull/976).

**palace-daemon migration — landed 2026-04-24, single-writer architecture is now the fork's primary answer.** The daemon at [`~/Projects/palace-daemon`](https://github.com/jphein/palace-daemon) is a FastAPI gateway with three asyncio semaphores (read N concurrent / write N/2 concurrent / mine 1 at a time) where the daemon is the *only* process that opens the palace; clients connect over HTTP via `mempalace-mcp.py` (a stdlib-only MCP proxy) and the hooks_cli `/silent-save` endpoint. A per-port file lock at `/tmp/palace-daemon-8085.lock` enforces one daemon per host+port; the proxy client fails fast if the daemon is unreachable, deliberately eliminating split-brain.

Two fork commits made the migration concrete:

1. **[`c09582c`](https://github.com/jphein/mempalace/commit/c09582c) (2026-04-24)** — plugin `.mcp.json` and Stop/PreCompact hooks routed through `http://disks.jphe.in:8085`. MCP is now a stdio-to-HTTP proxy; the in-process `mempalace.mcp_server` path is no longer the canonical entrypoint for this fork's installation.
2. **[`0e97b19`](https://github.com/jphein/mempalace/commit/0e97b19) (2026-04-24, "daemon-strict mode")** — when `PALACE_DAEMON_URL` is set, hooks skip *all* local palace writes (`_maybe_auto_ingest`, `_mine_sync`, silent-save fallback). The daemon is the single source of truth; concurrent local writes that would race the daemon's writes (and feed Syncthing-mediated drift on backed-up palaces) are now structurally impossible. Opt out with `PALACE_DAEMON_STRICT=0`.

**Why this matters for upstream contributors:** the in-tree fix this fork previously published as [#1171](https://github.com/MemPalace/mempalace/pull/1171) (cross-process flock at the `ChromaCollection` adapter) is **closed** as of 2026-04-25. Felipe Truman's [#976](https://github.com/MemPalace/mempalace/pull/976) (mine_global_lock at the miner level) covers the dominant write-conflict source for installs *without* a daemon, and that's the right layer — narrower scope, no Windows no-op, no extra constructor args. Combined with the daemon for multi-process MCP + hooks, #1171's adapter-level flock became defense-in-depth that didn't pay for its complexity.

**Other fork-ahead reliability fixes that remain valuable independent of the daemon:**

- **Quarantine on open ([#1173](https://github.com/MemPalace/mempalace/pull/1173)):** `quarantine_stale_hnsw()` now runs inside `ChromaBackend.make_client()` itself (complementary to #1062 which covers server startup). Threshold lowered 3600→300s after a 0.96h-drift segfault.
- **Marker guard ([#1177](https://github.com/MemPalace/mempalace/pull/1177)):** `.blob_seq_ids_migrated` sentinel file skips `sqlite3.connect()` on already-migrated palaces — opening sqlite against a live ChromaDB 1.5.x WAL database corrupts the next `PersistentClient`. Closes #1090.
- **Search BM25 None guard ([#1198](https://github.com/MemPalace/mempalace/pull/1198), filed 2026-04-24):** `_tokenize` short-circuits to `[]` for `None` documents — closes the gap upstream's #999 None-metadata audit left in BM25 helpers.

Felipe's `hnsw:num_threads: 1` pin from #976 (cherry-picked into the fork as commit `552a0d7` and now natively merged via the 2026-04-25 develop sync) is the actual root-cause fix for the parallel-HNSW race — applied at collection-creation metadata + via `_pin_hnsw_threads()` on every `get_collection` (ChromaDB 1.5.x doesn't persist the modified config across reopens). The daemon serializes around that fix at a higher layer; the two compose cleanly.

**Postgres + pgvector — long-term option, no immediate move.** RFC 001's backend seam is merged (#413, #995) and the registry already advertises `mempalace_postgres` as the canonical entry-point example. @skuznetsov's [#665](https://github.com/MemPalace/mempalace/pull/665) ships the actual PostgreSQL backend implementation (`pg_sorted_heap` preferred path, `pgvector` fallback); @malakhov-dmitrii's [#1072](https://github.com/MemPalace/mempalace/pull/1072) wires `palace._DEFAULT_BACKEND` through the registry so `MEMPALACE_BACKEND=postgres` actually takes effect. When both land, switching is `pip install mempalace-postgres && export MEMPALACE_BACKEND=postgres`. Postgres would eliminate the entire ChromaDB 1.5.x failure class natively (MVCC, no HNSW drift, no Rust-binding segfaults), but with the daemon now serializing access cleanly, the migration cost (151K+ drawers off ChromaDB via `export_palace()` + a Postgres importer) isn't justified by current pain. Re-evaluate if the daemon proves unstable, or once bensig's TypeScript rewrite picks its own storage layer.

**Postgres + pgvector — long-term option, no immediate move.** RFC 001's backend seam is merged (#413, #995) and the registry already advertises `mempalace_postgres` as the canonical entry-point example. @skuznetsov's [#665](https://github.com/milla-jovovich/mempalace/pull/665) ships the actual PostgreSQL backend implementation (`pg_sorted_heap` preferred path, `pgvector` fallback); @malakhov-dmitrii's [#1072](https://github.com/milla-jovovich/mempalace/pull/1072) wires `palace._DEFAULT_BACKEND` through the registry so `MEMPALACE_BACKEND=postgres` actually takes effect. When both land, switching is `pip install mempalace-postgres && export MEMPALACE_BACKEND=postgres`. Postgres would eliminate the entire ChromaDB 1.5.x failure class natively (MVCC, no HNSW drift, no Rust-binding segfaults), but with the v3.3.4 stack now mitigating that class for direct-access palaces, the migration cost (135K+ drawers off ChromaDB via `export_palace()` + a Postgres importer) isn't justified by current pain. Re-evaluate if the v3.3.4 stack proves unstable, or once bensig's TypeScript rewrite picks its own storage layer.

### Stale auto-loaded docs

Knowledge lives across 7+ layers: global CLAUDE.md, project CLAUDE.md, auto-memory (14 files), docs/, superpowers specs, code comments, MemPalace. The auto-loaded layers go stale and actively mislead Claude. Ironically, MemPalace is the only layer that *can't* go stale (verbatim + timestamped) but it's the only one that's never auto-loaded.

**Fix before any fork feature work:** audit every auto-loaded layer, date-stamp facts that can change, reduce duplication (one home per fact). Planned `/verify-docs` slash command pattern-matches version strings, file paths, PR numbers, URLs, and verifies against current state — then integrates into `/housekeep`. Cleaning stale docs prevents more wrong assumptions than any amount of auto-querying.

### Looking for solutions — context feeding + docs updating

Tools and patterns we're evaluating for the two open problems above. Not competitors to MemPalace (it's the verbatim archive, they're the delivery and freshness layers) — more like cooperating pieces.

- [**Mintlify**](https://www.mintlify.com/) — docs platform pitched as "self-updating knowledge management," with MCP and `llms.txt` support for AI-consumable docs. Useful reference for the stale-docs problem: their agent-driven update model is one approach to keeping auto-loaded context fresh. Cloud-hosted, so not a drop-in for local palaces, but the surface area (what they expose to AI, how they structure agent-readable docs) is worth studying.
- [**Context engineering (Emmimal P Alexander)**](https://towardsdatascience.com/rag-isnt-enough-i-built-the-missing-context-layer-that-makes-llm-systems-work/) — argues the bottleneck isn't retrieval but *what actually enters the context window*. Five components: hybrid retrieval, re-ranking with domain weighting, memory with exponential decay, intelligent compression, token-budget enforcement. The reference implementation is [context-engine](https://github.com/Emmimal/context-engine), already cited for P2 decay. The article frames the auto-surfacing problem as an engineering discipline rather than a product feature — useful scaffolding for the open problem above.

## Open upstream PRs

All 10 rebased onto current `upstream/develop` and `MERGEABLE` as of 2026-04-25.

| PR | Status | Description |
|---|---|---|
| [#660](https://github.com/MemPalace/mempalace/pull/660) | CI green, awaiting review | L1 importance pre-filter |
| [#1005](https://github.com/MemPalace/mempalace/pull/1005) | CI green, Copilot + Dialectician acks, awaiting maintainer | Warnings + sqlite BM25 top-up — never silently return fewer results than scope contains |
| [#1024](https://github.com/MemPalace/mempalace/pull/1024) | CI green, qodo review addressed | Configurable `chunk_size` / `chunk_overlap` / `min_chunk_size` |
| [#1086](https://github.com/MemPalace/mempalace/pull/1086) | CI green, awaiting review | `mempalace export` CLI wrapper for `export_palace()` |
| [#1087](https://github.com/MemPalace/mempalace/pull/1087) | CI green, awaiting review | `mempalace purge --wing/--room` — destructive drawer removal with HNSW ghost handling |
| [#1094](https://github.com/MemPalace/mempalace/pull/1094) | CI green, awaiting review | Coerce `None` metadatas to `{}` at `ChromaCollection` boundary (closes [#1020](https://github.com/MemPalace/mempalace/issues/1020)) |
| [#1142](https://github.com/MemPalace/mempalace/pull/1142) | CI green, @bensig accepted 2026-04-23 | `docs/RELEASING.md` with `mempalace-mcp` pre-release grep (fulfills [#1093](https://github.com/MemPalace/mempalace/issues/1093)'s release-checklist proposal) |
| [#1173](https://github.com/MemPalace/mempalace/pull/1173) | CI green, awaiting review | Call `quarantine_stale_hnsw()` in `make_client()`; lower threshold 3600→300s (complementary to [#1062](https://github.com/MemPalace/mempalace/pull/1062)) |
| [#1177](https://github.com/MemPalace/mempalace/pull/1177) | CI green, awaiting review | `.blob_seq_ids_migrated` marker guard — skip `sqlite3.connect()` on already-migrated palaces (closes [#1090](https://github.com/MemPalace/mempalace/issues/1090)) |
| [#1198](https://github.com/MemPalace/mempalace/pull/1198) | CI pending, filed 2026-04-24 | `searcher._tokenize` None-document guard — closes the gap [#999](https://github.com/MemPalace/mempalace/pull/999)'s None-metadata audit left in BM25 helpers |

Merged since v3.3.1:
- [v3.3.2](https://github.com/MemPalace/mempalace/releases/tag/v3.3.2) (2026-04-21): [#681](https://github.com/MemPalace/mempalace/pull/681), [#1000](https://github.com/MemPalace/mempalace/pull/1000), [#1023](https://github.com/MemPalace/mempalace/pull/1023)
- 2026-04-22: [#661](https://github.com/MemPalace/mempalace/pull/661), [#673](https://github.com/MemPalace/mempalace/pull/673), [#1021](https://github.com/MemPalace/mempalace/pull/1021), [#851](https://github.com/MemPalace/mempalace/pull/851) (upstream; also fixes #850, #1015)
- 2026-04-23: [#659](https://github.com/MemPalace/mempalace/pull/659)
- [v3.3.3](https://github.com/MemPalace/mempalace/releases/tag/v3.3.3) (2026-04-24): [#942](https://github.com/MemPalace/mempalace/pull/942), [#833](https://github.com/MemPalace/mempalace/pull/833), [#1097](https://github.com/MemPalace/mempalace/pull/1097), [#1145](https://github.com/MemPalace/mempalace/pull/1145), [#1147](https://github.com/MemPalace/mempalace/pull/1147) (follow-ups to #659), [#1148](https://github.com/MemPalace/mempalace/pull/1148) / [#1150](https://github.com/MemPalace/mempalace/pull/1150) / [#1157](https://github.com/MemPalace/mempalace/pull/1157) (entity-detection overhaul via @igorls's [#1175](https://github.com/MemPalace/mempalace/pull/1175) stacked-PR rescue), [#1166](https://github.com/MemPalace/mempalace/pull/1166) (palace-path env var security), [#340](https://github.com/MemPalace/mempalace/pull/340) / [#1093](https://github.com/MemPalace/mempalace/pull/1093) (mempalace-mcp install regression)
- 2026-04-25 develop sync (unreleased v3.3.4 line): [#976](https://github.com/MemPalace/mempalace/pull/976) (HNSW race + mine_global_lock — closes #974/#965; the PR's original PreCompact attempt-cap was dropped during rebase, so #955/#1172 are covered by [#863](https://github.com/MemPalace/mempalace/pull/863)), [#1168](https://github.com/MemPalace/mempalace/pull/1168) (tunnel security), [#1179](https://github.com/MemPalace/mempalace/pull/1179) (CLI BM25 hybrid + legacy-metric warning), [#1180](https://github.com/MemPalace/mempalace/pull/1180) (cross-wing topic tunnels), [#1182](https://github.com/MemPalace/mempalace/pull/1182) (mine Ctrl-C handling), [#1183](https://github.com/MemPalace/mempalace/pull/1183) (init mine UX), [#1185](https://github.com/MemPalace/mempalace/pull/1185) (batched-upsert-gpu)
- Earlier: [#999](https://github.com/MemPalace/mempalace/pull/999) (2026-04-18)

Closed: [#626](https://github.com/MemPalace/mempalace/pull/626), [#633](https://github.com/MemPalace/mempalace/pull/633), [#662](https://github.com/MemPalace/mempalace/pull/662) (superseded by BM25), [#663](https://github.com/MemPalace/mempalace/pull/663) (upstream wrote [#757](https://github.com/MemPalace/mempalace/pull/757)), [#738](https://github.com/MemPalace/mempalace/pull/738) (docs stale), [#629](https://github.com/MemPalace/mempalace/pull/629) (superseded — upstream shipped batching + file locking), [#632](https://github.com/MemPalace/mempalace/pull/632) (superseded — `--version`, `purge`, `repair` all shipped in v3.3.0), [#1036](https://github.com/MemPalace/mempalace/pull/1036) (superseded by #851 which merged 2026-04-22, also fixes #850), [#1115](https://github.com/MemPalace/mempalace/pull/1115) (premature, withdrew 2026-04-23 pending [#1069](https://github.com/MemPalace/mempalace/issues/1069) arbitration), [#1146](https://github.com/MemPalace/mempalace/pull/1146) (duplicate of @igorls's #1147), [#1171](https://github.com/MemPalace/mempalace/pull/1171) (closed 2026-04-25 — superseded by [#976](https://github.com/MemPalace/mempalace/pull/976)'s `mine_global_lock` at the right layer + this fork's daemon-strict architecture).

## Setup

```
git clone https://github.com/jphein/mempalace.git
cd mempalace
python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"

mempalace init ~/Projects --yes
mempalace mine ~/Projects/myproject
mempalace status
```

## Development

```
source venv/bin/activate
python -m pytest tests/ -q              # ~1096 tests (benchmarks deselected)
mempalace status                         # palace health
ruff check . && ruff format --check .    # lint + format
```

## Sources

Articles and surveys that shaped the fork's direction, competitive framing, and roadmap. Referenced throughout this README.

### Primary research

- [**lhl/agentic-memory**](https://github.com/lhl/agentic-memory) — multi-system analysis of agentic memory architectures. [`ANALYSIS-mempalace.md`](https://github.com/lhl/agentic-memory/blob/main/ANALYSIS-mempalace.md) is the specific MemPalace review that seeded our 7-item roadmap on 2026-04-11; [`ANALYSIS-karta.md`](https://github.com/lhl/agentic-memory/blob/main/ANALYSIS-karta.md) anchors the "deprioritized Karta-inspired features" list.
- [**codingwithcody.com — "MemPalace: digital castles on sand"**](https://codingwithcody.com/2026/04/13/mempalace-digital-castles-on-sand/) — 2026-04-13 critique (a TagMem promotion piece) whose hierarchy-causes-bugs argument directly produced architectural principles 1 and 2.
- [**OSS Insight — Agent Memory Race 2026**](https://ossinsight.io/blog/agent-memory-race-2026) — competitive landscape survey we cross-referenced against `lhl/agentic-memory` before writing the comparison table.

### Systems inspiring roadmap items

- [**Karta**](https://github.com/rohithzr/karta) — contradiction detection, dream-engine feedback loop, foresight signals, dual-granularity search, 14-step read pipeline with abstention. Inspires parts of P3/P4/P5; the heavier LLM-per-write features are deprioritized.
- [**Gigabrain**](https://github.com/legendaryvibecoder/gigabrain) — 30+ junk-filter patterns on write, event-sourced audit trail, nightly 8-stage maintenance. Pattern to steal for the stale-docs problem.
- [**Codex memory**](https://github.com/openai/codex) — citation-driven retention (usage count feeds selection and pruning), two-phase extraction → consolidation. Influences P3 feedback loops.
- [**ByteRover CLI**](https://github.com/campfirein/byterover-cli) — 5-tier progressive retrieval (exact cache → fuzzy cache → index → LLM → agentic). Pattern to consider for the context-feeding open problem.
- [**engram**](https://github.com/NickCirv/engram) — Go + SQLite FTS5 parallel index; file-read interception prototype referenced in [discussion #798](https://github.com/MemPalace/mempalace/discussions/798). Cited in deprioritized FTS5 item and the auto-surfacing open problem.
- [**context-engine**](https://github.com/Emmimal/context-engine) — ~200-line exponential decay implementation that ports directly into P2. Author Emmimal P Alexander's [context-engineering writeup](https://towardsdatascience.com/rag-isnt-enough-i-built-the-missing-context-layer-that-makes-llm-systems-work/) (*Towards Data Science*) frames the five components of the "missing context layer" — hybrid retrieval, re-ranking, memory decay, compression, token-budget enforcement — and informs our framing of the auto-surfacing open problem.
- **Verbatim-first cohort** — a handful of local-first memory systems independently landing on the same architectural call:
  - [**Longhand**](https://glama.ai/mcp/servers/Wynelson94/longhand) ([author writeup](https://dev.to/wynelson94/why-i-built-a-lossless-alternative-to-ai-memory-summarization-40cl)) — Claude Code-specific. Raw event JSON per tool call in SQLite, ChromaDB embeds pre-computed "episodes," plus deterministic file-state replay from stored diffs. Fork takeaway: typed-row event storage (every tool call as its own row with `session_id` + `timestamp`) enables structural queries we currently can't do — "show me every `Bash` event that touched file X in this session" is a primitive in Longhand, a keyword search in us. Worth considering for a future MemPalace pipeline mode that's Claude Code JSONL-aware by default.
  - [**Celiums**](https://celiums.ai/) ([MCP server](https://glama.ai/mcp/servers/terrizoaguimor/celiums-memory)) — triple-store (PostgreSQL + Qdrant + Valkey) or single-file SQLite. Layers PAD emotional vectors, importance scores, and circadian metadata onto verbatim text. Informs P3's importance-scoring design: novelty (habituation) + emotional intensity + circadian context as stored weights alongside the drawer, rather than only query-time rerank.
  - [**mcp-memory-service**](https://github.com/doobidoo/mcp-memory-service) (doobidoo) — verbatim-by-default with opt-in "autonomous consolidation" of older memories. Targets agent pipelines (LangGraph, CrewAI, AutoGen) rather than Claude Code specifically. The opt-in consolidation split (default preserves all, user enables aging) is a cleaner escape hatch than a decay flag — closer to what we want than a binary "turn on decay."

  Fork takeaway across the cohort: keep the drawer verbatim, layer richer metadata on top. We store wing/room/importance today; there's room along novelty, emotional, typed-event, and feedback axes without ever touching the archive.

### Verification note

Columns in the comparison table were filled in on 2026-04-14–18 by reading each project's README and, where unclear, a recent issue or PR on the same repo. Feature status on any of these projects will drift — cite them upstream before treating rows here as current. [TagMem](https://codingwithcody.com/2026/04/13/mempalace-digital-castles-on-sand/) is deliberately omitted; we could not find a public repo for it at the time of writing.

## License

MIT — see [LICENSE](LICENSE).
