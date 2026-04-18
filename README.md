# MemPalace (jphein fork)

**JP's production fork of [milla-jovovich/mempalace](https://github.com/milla-jovovich/mempalace)**

[![version-shield](https://img.shields.io/badge/version-3.3.1-4dc9f6?style=flat-square&labelColor=0a0e14)](https://github.com/MemPalace/mempalace/releases)
[![python-shield](https://img.shields.io/badge/python-3.9+-7dd8f8?style=flat-square&labelColor=0a0e14&logo=python&logoColor=7dd8f8)](https://www.python.org/)
[![license-shield](https://img.shields.io/badge/license-MIT-b0e8ff?style=flat-square&labelColor=0a0e14)](LICENSE)

---

Fork of [MemPalace v3.3.1](https://github.com/milla-jovovich/mempalace/releases/tag/v3.3.1). Running in production since 2026-04-09 — currently 137,949 drawers across 68 rooms in 22 wings, 7 open PRs upstream (#999 merged 2026-04-18). See upstream README for full feature docs.

What this fork adds that you won't get from upstream yet: a **deterministic silent-save hook architecture** (zero data loss, `systemMessage` notification), **ChromaDB 1.5.x hardening** (`quarantine_stale_hnsw` drift recovery, segfault-trigger guards, 8-site `None`-metadata safety), and **search that never silently misses** (`search_memories` returns warnings + sqlite BM25 top-up + `available_in_scope` so callers can see what they aren't getting). Full list below.

**Status at a glance:** active as of 2026-04-18 · [Discussion #1017](https://github.com/MemPalace/mempalace/discussions/1017) introduces the fork upstream · 998 tests pass on `main` · [Open upstream PRs](#open-upstream-prs) (8) are the contribution pipeline · [Issues on this repo](https://github.com/jphein/mempalace/issues) for fork-specific feedback.

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
| **MemPalace** | Yes | Yes | Yes | What we have. 137,949 drawers as of 2026-04-18. |
| [Hindsight](https://github.com/vectorize-io/hindsight) | No — LLM extracts facts | Yes (Docker) | Yes | Three ops: retain / recall / reflect. Original text is lost. |
| [Mem0](https://github.com/mem0ai/mem0) / [OpenMemory](https://github.com/mem0ai/mem0/tree/main/openmemory) | No — extracts "memories" | Partial | Yes | Cloud-first; OpenMemory is the local-mode sibling. |
| [Cognee](https://github.com/topoteretes/cognee) | No — knowledge graph | Yes | Yes (added since we wrote this row) | "Knowledge Engine" via ECL pipeline. |
| [Letta](https://github.com/letta-ai/letta) | No — tiered summarization | Yes | No | Formerly MemGPT. |
| [engram](https://github.com/NickCirv/engram) | Structured fields, not raw | Yes | Yes | Go + SQLite FTS5. |
| [CaviraOSS OpenMemory](https://github.com/CaviraOSS/OpenMemory) | No — temporal graph | Yes | Yes | SQL-native. |

**Verbatim storage is the differentiator.** For recovering exact commands, error messages, code snippets, and what someone actually said, you need the original text. Everything else — hierarchy, tags, knowledge graphs, decay — is enrichment *layered on top of* a faithful archive. If any of those layers fails or needs rebuilding, the underlying truth is still there.

## Architectural principles

Three principles that emerged from 137K drawers of production use. They explain most of this fork's decisions and should guide future ones. Contributors: use these to evaluate PRs.

### 1. Transforms on write are the enemy

Every operation that interprets content at write time is a failure surface. Entity detection misfires. Classifiers force wrong rooms. LLM-extracted "facts" lose nuance and can't be un-extracted. Many of this fork's visible bugs (`room=None` crashes, a stopword list that's grown to [285 English entries and counting](mempalace/i18n/en.json) to paper over false positives, wing misassignment) trace to a single mistake: making classification a *gate* instead of a best-effort enrichment.

Write the raw text. Derive everything else lazily, from unambiguous signals, with a graceful fallback when derivation fails. The verbatim archive is the one thing that must always succeed.

### 2. Hierarchy as optional scope, not required metadata

Hierarchy isn't wrong — *mandatory synchronous classification* is wrong. Those are different claims, and conflating them was our earlier mistake.

**Good uses of hierarchy, which we keep:**
- **Browseable scope** for serendipitous recall across 137K drawers. Search answers "when did I hit this error"; browse answers "what was I working on last November."
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
| **MemPalace** | `~/.mempalace/palace/` (ChromaDB) | 137K+ drawers | None (write-only archive) | Verbatim conversations, tool output, code |

Neither has automatic consolidation. Claude Code has unreleased "Auto Dream" consolidation code behind a disabled feature flag ([anthropics/claude-code#38461](https://github.com/anthropics/claude-code/issues/38461)) — if it ships, it covers only the lightweight layer. MemPalace decay (P2) and feedback (P3) remain the right priorities for the verbatim archive.

## Fork Changes

What this fork adds beyond upstream v3.3.1.

### Headlines

The three that matter most if you only read one section:

- **Silent-save hook architecture** — the stop hook writes to the palace directly via the Python API, advances the save marker only after a confirmed write, and surfaces a `systemMessage` line in the terminal. Deterministic, zero data loss, no dependency on the AI acting on a `block` prompt. ([#673](https://github.com/milla-jovovich/mempalace/pull/673), APPROVED externally.) Claude Code 2.1.114 tightened the Stop-hook output contract: the terminal `<Line>` renders reliably only when the hook emits the full schema (`continue:true`, `suppressOutput:false`, `systemMessage:…`) rather than bare `systemMessage`. Plus a related fd-level stdout-routing fix for when `mcp_server` transitively redirects `sys.stdout` to stderr. Producer-side fixes in [#1021](https://github.com/milla-jovovich/mempalace/pull/1021); observation flagged upstream at [anthropics/claude-code#50542](https://github.com/anthropics/claude-code/issues/50542).
- **ChromaDB 1.5.x hardening** — `quarantine_stale_hnsw()` recovers a palace whose HNSW has drifted from sqlite before it segfaults the Rust graph-walk ([#1000](https://github.com/milla-jovovich/mempalace/pull/1000), closes #823). `None`-metadata guards across 8 read-path loops landed upstream in [#999](https://github.com/milla-jovovich/mempalace/pull/999) (merged 2026-04-18).
- **Search that never silently misses** — `search_memories` returns `warnings: [...]`, `available_in_scope: N`, and a sqlite+BM25 fallback when vector underdelivers. The palace will tell you *why* it returned fewer results than the scope holds, instead of just returning them ([#1005](https://github.com/milla-jovovich/mempalace/pull/1005)).

### Still ahead of upstream

Status legend: a PR number means there's an open upstream PR for the change; **PR pending** means the fork has the change but no PR has been filed yet; **fork-only** means the fork keeps it intentionally but isn't pitching it upstream.

| Area | Change | Status | Files |
|---|---|---|---|
| **Reliability** | Epsilon mtime comparison (`abs() < 0.01` vs `==`) prevents re-mining | PR pending (verify vs current `develop` first) | `palace.py`, `miner.py` |
| **Reliability** | Skip `_fix_blob_seq_ids` sqlite open after first successful migration via `.blob_seq_ids_migrated` marker — opening sqlite3 against a live ChromaDB 1.5.x file corrupts the next PersistentClient | fork-only (narrow chromadb 1.5.x debugging path) | `backends/chroma.py` |
| **Reliability** | `quarantine_stale_hnsw()` helper — renames HNSW segments whose `data_level0.bin` is 1h+ older than `chroma.sqlite3`, sidesteps read-path SIGSEGV from dangling neighbor pointers (same failure mode as neo-cortex-mcp#2) | [#1000](https://github.com/milla-jovovich/mempalace/pull/1000) · closes #823 | `backends/chroma.py` |
| **Performance** | `bulk_check_mined()` — paginated pre-fetch for concurrent mining | fork-only (complementary to upstream's file-locking in [#784](https://github.com/milla-jovovich/mempalace/pull/784)) | `palace.py`, `miner.py` |
| **Performance** | Graph cache — 60s TTL, invalidated on writes | [#661](https://github.com/milla-jovovich/mempalace/pull/661) | `palace_graph.py` |
| **Performance** | L1 importance pre-filter — `importance >= 3` first, full scan fallback | [#660](https://github.com/milla-jovovich/mempalace/pull/660) | `layers.py` |
| **Search** | `max_distance` parameter (cosine distance threshold, default 1.5) | PR pending | `mcp_server.py`, `searcher.py` |
| **Search** | Warnings + sqlite BM25 top-up when vector underdelivers — `search_memories` returns `warnings: [...]` and `available_in_scope: N` so callers see why recall was partial; fallback hits tagged `matched_via: "sqlite_bm25_fallback"`. The palace never silently returns fewer results than the scope contains (sibling of #951, addresses read-side of #823) | [#1005](https://github.com/milla-jovovich/mempalace/pull/1005) | `searcher.py` |
| **Hooks** | Silent save mode — direct Python API, deterministic, zero data loss | [#673](https://github.com/milla-jovovich/mempalace/pull/673) · APPROVED externally 2026-04-12 | `hooks_cli.py` |
| **Hooks** | Honor silent_save when `stop_hook_active:true` — Claude Code 2.1.114 sets the flag on every plugin-dispatched Stop fire after the first, and the legacy block-mode loop guard was suppressing every subsequent auto-save (silent, no log entry, marker stuck). Fixed to only skip on the flag in block mode | PR pending | `hooks_cli.py` |
| **Hooks** | Write hook JSON to real stdout — `mempalace.mcp_server` redirects stdout→stderr at import to protect MCP stdio from ChromaDB C-level noise; silent-save imports it transitively, so `{"systemMessage": "✦ …"}` landed on stderr and Claude Code never rendered the checkpoint notification. `_output()` now writes to `_REAL_STDOUT_FD` via `os.write()`, falling back to `sys.stdout` only when unavailable | PR pending | `hooks_cli.py` |
| **Hooks** | Tool output mining — per-tool formatting strategies in `normalize.py` | PR pending | `normalize.py` |
| **Features** | Diary wing routing — derive project wing from transcript path | [#659](https://github.com/milla-jovovich/mempalace/pull/659) | `hooks_cli.py`, `mcp_server.py` |

### Merged upstream (post-v3.3.1)

- `None`-metadata guards across 8 read-path loops — `searcher.py` (CLI + API + closet-boost), `miner.status()`, and 4 MCP handlers ([#999](https://github.com/milla-jovovich/mempalace/pull/999), merged 2026-04-18)

### Merged upstream (in v3.3.0)

- BLOB seq_id migration repair (#664)
- `--yes` flag for init (#682)
- Unicode `sanitize_name` (#683)
- VAR_KEYWORD kwargs check (#684)
- New MCP tools + export (via #667)

### Pulled in from upstream v3.3.1

- Multi-language entity detection: Portuguese, Russian, Italian, Hindi, Indonesian, Chinese (#907, #911, #928, #931, #932, #945, #760, #156, #773, #778)
- BCP-47 case-insensitive locale resolution (#928)
- Script-aware word boundaries for Devanagari/Arabic/Hebrew/Thai (#932)
- UTF-8 encoding on `Path.read_text()` — fixes GBK/non-UTF-8 locale corruption (#946)
- Non-blocking precompact hook (#863) — replaces our fork's blocking precompact
- Basic `silent_save` honoring in stop hook (#966) — narrower than our fork's deterministic-save architecture (below), so we keep the fork version

### Superseded by upstream

- Hybrid keyword fallback (`$contains`) — upstream shipped Okapi-BM25 (60/40 blend) via [#789](https://github.com/milla-jovovich/mempalace/pull/789)
- Batch ChromaDB writes — upstream has file-level locking for concurrent agents via [#784](https://github.com/milla-jovovich/mempalace/pull/784)
- Inline transcript mining in hooks — upstream uses `mempalace mine` in background
- Stale HNSW mtime detection — upstream took a different approach in [#757](https://github.com/milla-jovovich/mempalace/pull/757); fork's broader inode+mtime detection and `mempalace_reconnect` MCP tool stay as fork-local convenience

## Planned work

Ordered by impact. Informed by competitive research ([Karta](https://github.com/rohithzr/karta), Hindsight, [engram](https://github.com/NickCirv/engram), [context-engine](https://github.com/Emmimal/context-engine), CaviraOSS) and our own usage patterns — see [Sources](#sources) at the bottom for the full reference list. Each item is evaluated against the three principles above.

### Done
- Hybrid search fallback (superseded by upstream BM25)
- Graph cache with write-invalidation (shipped in this fork; #661 rebased, threading.Lock added, awaiting re-review)
- L1 importance pre-filter (#660 rebased, clean)
- Convo miner wing assignment (#659 rebased, clean)
- Silent hook saves (shipped in this fork; #673 still ahead of upstream's #966 — ours has marker-after-confirmed-save, themes extraction, systemMessage notification)

### P0 — Multi-label tags *(1-2 days, additive, upstream candidate)*

Tags are the cross-cutting-concerns layer that hierarchy can't provide. A conversation about ChromaDB HNSW debugging gets `chromadb, hnsw, sqlite, python, testing` tags *and* lives in its project wing — the two aren't mutually exclusive. Modern memory systems (Hindsight, Mem0, CaviraOSS) converged on multi-label tagging because content is inherently multi-faceted while hierarchy is inherently single-parent.

Add `tags` metadata (3-8 per drawer, extracted during mining via TF-IDF or longest-non-stopword heuristic — we already have `_extract_keyword` in `searcher.py`). ChromaDB `where_document` and metadata `$contains` handle the query. This is additive: drawers still get a wing when derivation is unambiguous, and now they also get content tags for cross-wing retrieval.

### P1 — Derive hierarchy from unambiguous signals *(half day)*

Reframe from "best-effort classification" to "derive from what we actually know." The cwd at write time, the transcript file path, the project directory — these are unambiguous. Entity detection on drawer content is not.

Changes:
- Default wing to source directory name — already mostly works; make it the primary path.
- Room assignment becomes optional metadata; never crash on `room=None`.
- Demote the entity detector to a last-resort hint, not a gate. Classification failure never blocks a write.
- Document the derivation order explicitly: cwd → transcript path → project hint → (optional) entity hint → unfiled.

This preserves hierarchy's benefits (scope, browse, delete-as-unit) while eliminating the failure surface that caused most of this fork's bugs. It's principle 1 and principle 2 made concrete.

### P2 — Decay / recency weighting *(1 day, opt-in)*

Search should favor recent and frequently-accessed memories. Add `last_accessed` and `access_count` to drawer metadata; post-process results with a decay curve. Reference: [context-engine](https://github.com/Emmimal/context-engine) has a ~200-line exponential decay implementation that ports directly. Ship as opt-in with conservative defaults — too aggressive loses valuable old memories. Also add `mempalace prune --stale-days 180 --dry-run` CLI.

### P3 — Feedback loops *(1-2 days)*

Tier 1 (ship first): `mempalace_rate_memory(drawer_id, useful: bool)` MCP tool. Useful memories rank higher; flagged-not-useful get demoted. Tier 2 (later): query history table + implicit echo/fizzle signals once there's enough data. Hindsight calls this "reflect" — synthesizing across memories to identify what's useful.

### P4 — KG auto-population + entity resolution *(1.5 days)*

The knowledge graph has 5 MCP tools and a SQLite backend but ~zero data. Hooks should extract `subject/predicate/object` triples on every save using heuristics (no LLM — `project → has_file → path`, `session → discussed → room` patterns). Normalize entity IDs (lowercase, strip punctuation, collapse whitespace). Alias table + Levenshtein < 2 for fuzzy matches. Prerequisite for contradiction detection.

Triples are **derived** from the verbatim archive, not parallel to it. If extraction improves later, re-mine — the source of truth is untouched. Same principle that makes P0 and P1 safe: stable underlying drawers, rebuildable enrichment.

### P5 — Temporal fact validity *(1 day, depends on P4)*

KG triples get a context slot (SPOC: subject-predicate-object-context) rather than only `valid_from` / `valid_to` columns. Context acts as a namespace — `(LeBron, played_for, Beavers, "2023_season")` vs `(LeBron, played_for, Lakers, "2022_season")` — making contradiction detection "same S+P, different O, overlapping contexts" rather than timestamp-range logic. On write, close any existing triple with the same subject+predicate+context before opening a new one. Reference: Zep's [Graphiti](https://github.com/getzep/graphiti) temporal graph model.

### P6 — Input sanitization on writes *(half day)*

Strip known injection patterns (role-play instructions, "ignore previous instructions"). Flag with `sanitized: true` metadata rather than blocking. Length cap at 10K chars. Low priority while we're local-only; matters if the MCP server is ever exposed more broadly.

### Deprioritized

- **AAAK work** — upstream's problem; we store verbatim.
- **Expanding hierarchy types** (tunnels, closets, new room categories). Adding more categories doesn't address the write-time classification problem. Tags (P0) and derived scope (P1) do.
- **Benchmark work** — our value is "137K drawers of verbatim local history with fast search," not upstream's LongMemEval score.
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
| [#659](https://github.com/milla-jovovich/mempalace/pull/659) | clean, waiting review | Diary wing parameter |
| [#660](https://github.com/milla-jovovich/mempalace/pull/660) | `MERGEABLE`, waiting review | L1 importance pre-filter |
| [#661](https://github.com/milla-jovovich/mempalace/pull/661) | feedback addressed (threading.Lock in 8adf35a), waiting `@bensig` re-review | Graph cache with write-invalidation |
| [#673](https://github.com/milla-jovovich/mempalace/pull/673) | APPROVED by external reviewer on 2026-04-12, waiting maintainer merge | Deterministic hook saves (broader than upstream's narrower #966) |
| [#681](https://github.com/milla-jovovich/mempalace/pull/681) | clean, waiting review | Unicode checkmark → ASCII |
| [#1000](https://github.com/milla-jovovich/mempalace/pull/1000) | `MERGEABLE`, closes #823, Copilot nit addressed, rebased onto #995's new backend surface | `quarantine_stale_hnsw()` for HNSW/sqlite drift crashes |
| [#1005](https://github.com/milla-jovovich/mempalace/pull/1005) | `MERGEABLE`, Copilot review addressed (authoritative scope count via paginated `col.get`, gate "run repair" on vector underdelivery, restore palace path in CLI error) | Warnings + sqlite BM25 top-up — never silently return fewer results than scope contains |

Closed: [#626](https://github.com/milla-jovovich/mempalace/pull/626), [#633](https://github.com/milla-jovovich/mempalace/pull/633), [#662](https://github.com/milla-jovovich/mempalace/pull/662) (superseded by BM25), [#663](https://github.com/milla-jovovich/mempalace/pull/663) (upstream wrote [#757](https://github.com/milla-jovovich/mempalace/pull/757)), [#738](https://github.com/milla-jovovich/mempalace/pull/738) (docs stale), [#629](https://github.com/milla-jovovich/mempalace/pull/629) (superseded — upstream shipped batching + file locking), [#632](https://github.com/milla-jovovich/mempalace/pull/632) (superseded — `--version`, `purge`, `repair` all shipped in v3.3.0).

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
python -m pytest tests/ -q              # ~900 tests (benchmarks deselected)
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
