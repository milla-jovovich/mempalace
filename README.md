# MemPalace (jphein fork)

**JP's production fork of [milla-jovovich/mempalace](https://github.com/milla-jovovich/mempalace)**

[![version-shield](https://img.shields.io/badge/version-3.3.1-4dc9f6?style=flat-square&labelColor=0a0e14)](https://github.com/MemPalace/mempalace/releases)
[![python-shield](https://img.shields.io/badge/python-3.9+-7dd8f8?style=flat-square&labelColor=0a0e14&logo=python&logoColor=7dd8f8)](https://www.python.org/)
[![license-shield](https://img.shields.io/badge/license-MIT-b0e8ff?style=flat-square&labelColor=0a0e14)](LICENSE)

---

Fork of [MemPalace](https://github.com/milla-jovovich/mempalace), tracking `upstream/develop` through the 2026-04-21 sync. Upstream shipped [v3.3.2](https://github.com/MemPalace/mempalace/releases/tag/v3.3.2) on 2026-04-21 — contains our #681, #1000, #1023. Running in production since 2026-04-09 — currently 165,632 drawers across 68 rooms in 28 wings, 7 open PRs upstream (#999 merged 2026-04-18; #681/#1000/#1023 released in v3.3.2; #1036 closed as duplicate of approved #851). See upstream README for full feature docs.

What this fork adds that you won't get from upstream yet: a **deterministic silent-save hook architecture** (zero data loss, `systemMessage` notification), **ChromaDB 1.5.x hardening** (`quarantine_stale_hnsw` drift recovery, segfault-trigger guards, 8-site `None`-metadata safety), and **search that never silently misses** (`search_memories` returns warnings + sqlite BM25 top-up + `available_in_scope` so callers can see what they aren't getting). Full list below.

1096 tests pass on `main` · [Discussion #1017](https://github.com/MemPalace/mempalace/discussions/1017) introduces the fork upstream · [Issues on this repo](https://github.com/jphein/mempalace/issues) for fork-specific feedback.

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

## Why this fork exists

We surveyed the memory-system landscape in April 2026 and found no verbatim-first local system with MCP. Every alternative transforms content on write — extracted facts, knowledge graphs, tiered summaries — losing the original text.

| System | Verbatim? | Local? | MCP? | Notes |
|---|---|---|---|---|
| **MemPalace** | Yes | Yes | Yes | What we have. 165,632 drawers as of 2026-04-21. |
| [Hindsight](https://github.com/vectorize-io/hindsight) | No — LLM extracts facts | Yes (Docker) | Yes | Three ops: retain / recall / reflect. Original text is lost. |
| [Mem0](https://github.com/mem0ai/mem0) / [OpenMemory](https://github.com/mem0ai/mem0/tree/main/openmemory) | No — extracts "memories" | Partial | Yes | Cloud-first; OpenMemory is the local-mode sibling. |
| [Cognee](https://github.com/topoteretes/cognee) | No — knowledge graph | Yes | Yes (added since we wrote this row) | "Knowledge Engine" via ECL pipeline. |
| [Letta](https://github.com/letta-ai/letta) | No — tiered summarization | Yes | No | Formerly MemGPT. |
| [engram](https://github.com/NickCirv/engram) | Structured fields, not raw | Yes | Yes | Go + SQLite FTS5. |
| [CaviraOSS OpenMemory](https://github.com/CaviraOSS/OpenMemory) | No — temporal graph | Yes | Yes | SQL-native. |

**Verbatim storage is the differentiator.** For recovering exact commands, error messages, code snippets, and what someone actually said, you need the original text. Everything else — hierarchy, tags, knowledge graphs, decay — is enrichment *layered on top of* a faithful archive. If any of those layers fails or needs rebuilding, the underlying truth is still there.

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
| **MemPalace** | `~/.mempalace/palace/` (ChromaDB) | 152K+ drawers | None (write-only archive) | Verbatim conversations, tool output, code |

Neither has automatic consolidation. Claude Code has unreleased "Auto Dream" consolidation code behind a disabled feature flag ([anthropics/claude-code#38461](https://github.com/anthropics/claude-code/issues/38461)) — if it ships, it covers only the lightweight layer. MemPalace decay (P2) and feedback (P3) remain the right priorities for the verbatim archive.

## Fork Changes

What this fork adds beyond upstream v3.3.2. Full list in the table; see the lead paragraph for the three differentiators worth reading first.

### Still ahead of upstream

Status legend: a PR number means there's an open upstream PR for the change; **PR pending** means the fork has the change but no PR has been filed yet; **fork-only** means the fork keeps it intentionally but isn't pitching it upstream.

| Area | Change | Status | Files |
|---|---|---|---|
| **Reliability** | Skip `_fix_blob_seq_ids` sqlite open after first successful migration via `.blob_seq_ids_migrated` marker — opening sqlite3 against a live ChromaDB 1.5.x file corrupts the next PersistentClient | fork-only (narrow chromadb 1.5.x debugging path) | `backends/chroma.py` |
| **Reliability** | `_get_client()` tries `get_collection` before `create_collection` — `get_or_create_collection` segfaults ChromaDB 1.5.x when the existing collection's metadata differs from the call-site metadata | fork-only | `backends/chroma.py` |
| **Reliability** | `quarantine_stale_hnsw()` should also validate `index_metadata.pickle` integrity — a process killed mid-write leaves a corrupt file with zero mtime drift, so the 1h threshold doesn't fire and the next palace open segfaults. Fix: attempt to deserialize the file in the quarantine check and quarantine on failure regardless of mtime. | PR pending | `backends/chroma.py` |
| **Performance** | `bulk_check_mined()` — paginated pre-fetch for concurrent mining | fork-only (complementary to upstream's file-locking in [#784](https://github.com/milla-jovovich/mempalace/pull/784)) | `palace.py`, `miner.py` |
| **Performance** | Graph cache — 60s TTL, invalidated on writes | [#661](https://github.com/milla-jovovich/mempalace/pull/661) | `palace_graph.py` |
| **Performance** | L1 importance pre-filter — `importance >= 3` first, full scan fallback | [#660](https://github.com/milla-jovovich/mempalace/pull/660) | `layers.py` |
| **Performance** | `miner.status()` paginates `col.get()` in 10 K-drawer batches — upstream's single `col.get(limit=total)` hits SQLite's max-variable limit on palaces with many thousands of drawers | tracked upstream in [#851](https://github.com/milla-jovovich/mempalace/pull/851) (approved, MERGEABLE, also fixes #850); fork's paginated version has been running since 2026-04-10 | `miner.py` |
| **Config** | Configurable chunking parameters — `chunk_size` (default 800 chars), `chunk_overlap` (100), `min_chunk_size` (50) written to `config.json` and exposed via `MempalaceConfig` properties | [#1024](https://github.com/milla-jovovich/mempalace/pull/1024) | `config.py`, `miner.py` |
| **Search** | Warnings + sqlite BM25 top-up when vector underdelivers — `search_memories` returns `warnings: [...]` and `available_in_scope: N` so callers see why recall was partial; fallback hits tagged `matched_via: "sqlite_bm25_fallback"`. The palace never silently returns fewer results than the scope contains (sibling of #951, addresses read-side of #823) | [#1005](https://github.com/milla-jovovich/mempalace/pull/1005) | `searcher.py` |
| **Hooks** | Silent save mode — direct Python API, deterministic, zero data loss; extracts 2–3 topic words from recent messages for the diary title; optional desktop toast via `notify-send` | [#673](https://github.com/milla-jovovich/mempalace/pull/673) · APPROVED externally 2026-04-12, rebased + squashed 2026-04-21, `MERGEABLE` | `hooks_cli.py` |
| **Hooks** | `mempal_save_hook.sh` auto-detects Python — checks `MEMPAL_PYTHON` env var, then repo venv at `../../venv/bin/python3`, then system `python3`; no hardcoded path required. Same pattern applied to `.claude-plugin/` stop and precompact hooks. | fork-only | `hooks/mempal_save_hook.sh`, `.claude-plugin/hooks/mempal-stop-hook.sh`, `.claude-plugin/hooks/mempal-precompact-hook.sh` |
| **Hooks** | Honor silent_save when `stop_hook_active:true` — Claude Code 2.1.114 sets the flag on every plugin-dispatched Stop fire after the first, and the legacy block-mode loop guard was suppressing every subsequent auto-save (silent, no log entry, marker stuck). Fixed to only skip on the flag in block mode | [#1021](https://github.com/milla-jovovich/mempalace/pull/1021) | `hooks_cli.py` |
| **Hooks** | Write hook JSON to real stdout via `sys.modules` lookup — `mempalace.mcp_server` redirects stdout→stderr at import to protect MCP stdio from ChromaDB C-level noise; `_output()` checks `sys.modules` for an already-loaded `mcp_server` and reuses its `_REAL_STDOUT_FD`, otherwise writes directly to fd 1. Avoids triggering the redirect as a side effect. | [#1021](https://github.com/milla-jovovich/mempalace/pull/1021) | `hooks_cli.py` |
| **Features** | Diary wing routing — derive project wing from transcript path; `tool_diary_write` and `tool_diary_read` accept an optional `wing` parameter | [#659](https://github.com/milla-jovovich/mempalace/pull/659) | `hooks_cli.py`, `mcp_server.py` |
| **Hooks** | `hooks/mempal_precompact_hook.sh` transcript auto-mining — session ID parsed from JSON input, transcript resolved by direct path or `find`-by-session-id fallback, then mined inline (chunk_exchanges → upsert) before compaction fires; includes Python auto-detection | PR pending | `hooks/mempal_precompact_hook.sh` |
| **CLI** | `cmd_export` and `cmd_purge` CLI commands — `export` calls `export_palace()` from the exporter module; `purge` deletes drawers by wing/room, nukes the palace dir and re-inserts retained drawers (avoids HNSW ghost entries left by `delete_collection`) | PR pending | `cli.py` |

### Merged upstream (post-v3.3.1)

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

### Auto-surfacing context Claude doesn't know to ask for

Claude frequently makes wrong assumptions when the correct info exists in MemPalace, because it doesn't know to search. This is a **consumption problem, not a storage problem** — the write path (hooks, mining) is solid; the read path works when triggered. The gap is automatic surfacing at the moment of need.

What didn't work: SessionStart pre-loading, auto-memory bridges, PreCompact re-reads, CLAUDE.md instructions to "always query mempalace." What might work: [engram](https://github.com/NickCirv/engram)-style file-read interception that injects MemPalace context alongside code structure ([discussion #798](https://github.com/MemPalace/mempalace/discussions/798)). Only covers code-level assumptions, not workflow/config.

P1's cwd-derived wings are relevant here: once wings are derived from unambiguous signals, they become a cheap scoping prior for any automatic surfacing mechanism. "Claude is in `/Projects/mempalace`; query that wing first" is a lot cheaper than training a router. No memory system has solved this well — it's the unsolved problem of the [OSS Insight Agent Memory Race](https://ossinsight.io/blog/agent-memory-race-2026).

### Stale auto-loaded docs

Knowledge lives across 7+ layers: global CLAUDE.md, project CLAUDE.md, auto-memory (14 files), docs/, superpowers specs, code comments, MemPalace. The auto-loaded layers go stale and actively mislead Claude. Ironically, MemPalace is the only layer that *can't* go stale (verbatim + timestamped) but it's the only one that's never auto-loaded.

**Fix before any fork feature work:** audit every auto-loaded layer, date-stamp facts that can change, reduce duplication (one home per fact). Planned `/verify-docs` slash command pattern-matches version strings, file paths, PR numbers, URLs, and verifies against current state — then integrates into `/housekeep`. Cleaning stale docs prevents more wrong assumptions than any amount of auto-querying.

### Looking for solutions — context feeding + docs updating

Tools and patterns we're evaluating for the two open problems above. Not competitors to MemPalace (it's the verbatim archive, they're the delivery and freshness layers) — more like cooperating pieces.

- [**Mintlify**](https://www.mintlify.com/) — docs platform pitched as "self-updating knowledge management," with MCP and `llms.txt` support for AI-consumable docs. Useful reference for the stale-docs problem: their agent-driven update model is one approach to keeping auto-loaded context fresh. Cloud-hosted, so not a drop-in for local palaces, but the surface area (what they expose to AI, how they structure agent-readable docs) is worth studying.
- [**Context engineering (Emmimal P Alexander)**](https://towardsdatascience.com/rag-isnt-enough-i-built-the-missing-context-layer-that-makes-llm-systems-work/) — argues the bottleneck isn't retrieval but *what actually enters the context window*. Five components: hybrid retrieval, re-ranking with domain weighting, memory with exponential decay, intelligent compression, token-budget enforcement. The reference implementation is [context-engine](https://github.com/Emmimal/context-engine), already cited for P2 decay. The article frames the auto-surfacing problem as an engineering discipline rather than a product feature — useful scaffolding for the open problem above.

## Open upstream PRs

| PR | Status | Description |
|---|---|---|
| [#659](https://github.com/milla-jovovich/mempalace/pull/659) | `MERGEABLE`, bensig review addressed 2026-04-19 (wing_ prefix + agent filter) | Diary wing parameter |
| [#660](https://github.com/milla-jovovich/mempalace/pull/660) | `MERGEABLE`, waiting review | L1 importance pre-filter |
| [#661](https://github.com/milla-jovovich/mempalace/pull/661) | feedback addressed (threading.Lock in 8adf35a), pinged 2026-04-18, waiting `@bensig` re-review. GitHub holds the `CHANGES_REQUESTED` state until the reviewer dismisses it — this does not mean the PR owes a response. | Graph cache with write-invalidation |
| [#673](https://github.com/milla-jovovich/mempalace/pull/673) | APPROVED externally 2026-04-12, rebased fresh on `upstream/develop` + squashed to 1 commit 2026-04-21, `MERGEABLE` | Deterministic hook saves (broader than upstream's narrower #966) |
| [#1005](https://github.com/milla-jovovich/mempalace/pull/1005) | CI green (all platforms), Copilot + Dialectician review addressed, waiting maintainer review | Warnings + sqlite BM25 top-up — never silently return fewer results than scope contains |
| [#1021](https://github.com/milla-jovovich/mempalace/pull/1021) | bensig review addressed 2026-04-19 (`silent_guard` default), CI green | Hook stdout routing + silent_save guard fixes for Claude Code 2.1.114 |
| [#1024](https://github.com/milla-jovovich/mempalace/pull/1024) | CI green, filed 2026-04-18 | Configurable `chunk_size` / `chunk_overlap` / `min_chunk_size` |

Merged since v3.3.1: [#999](https://github.com/milla-jovovich/mempalace/pull/999) (2026-04-18), plus [#681](https://github.com/milla-jovovich/mempalace/pull/681), [#1000](https://github.com/milla-jovovich/mempalace/pull/1000), [#1023](https://github.com/milla-jovovich/mempalace/pull/1023) all shipped in [v3.3.2](https://github.com/MemPalace/mempalace/releases/tag/v3.3.2) (2026-04-21).

Closed: [#626](https://github.com/milla-jovovich/mempalace/pull/626), [#633](https://github.com/milla-jovovich/mempalace/pull/633), [#662](https://github.com/milla-jovovich/mempalace/pull/662) (superseded by BM25), [#663](https://github.com/milla-jovovich/mempalace/pull/663) (upstream wrote [#757](https://github.com/milla-jovovich/mempalace/pull/757)), [#738](https://github.com/milla-jovovich/mempalace/pull/738) (docs stale), [#629](https://github.com/milla-jovovich/mempalace/pull/629) (superseded — upstream shipped batching + file locking), [#632](https://github.com/milla-jovovich/mempalace/pull/632) (superseded — `--version`, `purge`, `repair` all shipped in v3.3.0), [#1036](https://github.com/milla-jovovich/mempalace/pull/1036) (superseded by #851 which was already approved, also fixes #850).

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

### Verification note

Columns in the comparison table were filled in on 2026-04-14–18 by reading each project's README and, where unclear, a recent issue or PR on the same repo. Feature status on any of these projects will drift — cite them upstream before treating rows here as current. [TagMem](https://codingwithcody.com/2026/04/13/mempalace-digital-castles-on-sand/) is deliberately omitted; we could not find a public repo for it at the time of writing.

## License

MIT — see [LICENSE](LICENSE).
