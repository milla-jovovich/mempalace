<div align="center">

<img src="assets/mempalace_logo.png" alt="MemPalace" width="280">

# MemPalace (jphein fork)

**JP's production fork of [milla-jovovich/mempalace](https://github.com/milla-jovovich/mempalace)**

[![version-shield]][release-link]
[![python-shield]][python-link]
[![license-shield]][license-link]

</div>

---

Fork of [MemPalace v3.3.0](https://github.com/milla-jovovich/mempalace/releases/tag/v3.3.0). Running in production with 134K+ drawers across 60+ rooms. See upstream README for full feature docs.

## Why this fork exists

We surveyed the memory-system landscape in April 2026 and found no verbatim-first local system with MCP. Every alternative transforms content on write — extracted facts, knowledge graphs, tiered summaries — losing the original text.

| System | Verbatim? | Local? | MCP? | Notes |
|--------|-----------|--------|------|-------|
| **MemPalace** | Yes | Yes | Yes | What we have. 134K drawers. |
| Hindsight | No — LLM extracts facts | Yes (Docker) | Yes | Original text is lost. |
| Mem0 / OpenMemory | No — extracts "memories" | Partial | Yes | Cloud-first. |
| Cognee | No — knowledge graph | Yes | No | |
| Letta | No — tiered summarization | Yes | No | |
| engram | Structured fields, not raw | Yes | Yes | Go + SQLite FTS5. |
| CaviraOSS OpenMemory | No — temporal graph | Yes | Yes | SQL-native. |

**Verbatim storage is the actual differentiator** — not the palace hierarchy, not AAAK, not benchmarks. For recovering exact commands, error messages, code snippets, and what someone actually said, you need the original text.

### What's *not* the value

The palace hierarchy (wings/rooms/halls) causes half our fork bugs: forced classification, wing misassignment, entity-detector false positives (73 stopwords), `room=None` crashes, whole modules (`palace_graph.py`) existing to compensate. Our retrieval is vector + BM25; wing filtering is optional and rarely used. Silent hook saves use plain text — no AAAK, no room routing. **Stop investing in hierarchy; invest in retrieval.**

## Fork Changes

What this fork adds beyond upstream v3.3.0.

### Still ahead of upstream

| Area | Change | Files |
|------|--------|-------|
| **Reliability** | Epsilon mtime comparison (`abs() < 0.01` vs `==`) prevents re-mining | `palace.py`, `miner.py` |
| **Reliability** | Stale HNSW mtime detection + `mempalace_reconnect` MCP tool | `mcp_server.py` |
| **Performance** | `bulk_check_mined()` — paginated pre-fetch for concurrent mining | `palace.py`, `miner.py` |
| **Performance** | Graph cache — 60s TTL, invalidated on writes | `palace_graph.py` |
| **Performance** | L1 importance pre-filter — `importance >= 3` first, full scan fallback | `layers.py` |
| **Search** | `max_distance` parameter (cosine distance threshold, default 1.5) | `mcp_server.py`, `searcher.py` |
| **Hooks** | Silent save mode — direct Python API, deterministic, zero data loss | `hooks_cli.py` |
| **Hooks** | Tool output mining — per-tool formatting strategies in `normalize.py` | `normalize.py` |
| **Features** | Diary wing routing — derive project wing from transcript path | `hooks_cli.py`, `mcp_server.py` |

### Merged upstream (in v3.3.0)

- BLOB seq_id migration repair (#664)
- `--yes` flag for init (#682)
- Unicode `sanitize_name` (#683)
- VAR_KEYWORD kwargs check (#684)
- New MCP tools + export (via #667)

### Superseded by upstream

- Hybrid keyword fallback (`$contains`) — upstream shipped Okapi-BM25 (60/40 blend)
- Batch ChromaDB writes — upstream has file-level locking for concurrent agents
- Inline transcript mining in hooks — upstream uses `mempalace mine` in background

## Roadmap

Ordered by impact. Informed by competitive research (Karta, Hindsight, engram, context-engine, CaviraOSS) and our own usage patterns.

### Done

- Hybrid search fallback (superseded by upstream BM25)
- Graph cache with write-invalidation (shipped in this fork; #661 rebased, threading.Lock added, awaiting re-review)
- L1 importance pre-filter (#660 rebased, clean)
- Convo miner wing assignment (#659 rebased, clean)
- Silent hook saves (shipped in this fork; #673 pending rebase against #863)

### P0 — Multi-label tags *(1-2 days, additive, upstream candidate)*

Every modern memory system (Hindsight, Mem0, CaviraOSS) uses multi-label tagging instead of forced hierarchy. Add `tags` metadata (3-8 per drawer, extracted during mining via TF-IDF or longest-non-stopword heuristic — we already have `_extract_keyword` in `searcher.py`). ChromaDB `where_document` and metadata `$contains` handle the query. Makes most fork bugs about hierarchy irrelevant — a conversation about ChromaDB HNSW debugging gets `chromadb, hnsw, sqlite, python, testing` tags instead of being force-filed into one room.

### P1 — Make classification best-effort *(half day)*

Wing and room assignment should be optional metadata, not a required gate. If classification fails, store the drawer with empty wing/room and never crash on `room=None`. Default wing to source directory name (already mostly works). Remove hard failures in the entity detector. Treats hierarchy as best-effort enrichment rather than architecture.

### P2 — Decay / recency weighting *(1 day, opt-in)*

Search should favor recent/frequently-accessed memories. Add `last_accessed` and `access_count` to drawer metadata; post-process results with a decay curve. Reference: [context-engine](https://github.com/Emmimal/context-engine) has a ~200-line exponential decay implementation that ports directly. Ship as opt-in with conservative defaults — too aggressive loses valuable old memories. Also add `mempalace prune --stale-days 180 --dry-run` CLI.

### P3 — Feedback loops *(1-2 days)*

Tier 1 (ship first): `mempalace_rate_memory(drawer_id, useful: bool)` MCP tool. Useful memories rank higher, flagged-not-useful get demoted. Tier 2 (later): query history table + implicit echo/fizzle signals once there's enough data. Hindsight calls this "reflect" — synthesizing across memories to identify what's useful.

### P4 — KG auto-population + entity resolution *(1.5 days)*

The knowledge graph has 5 MCP tools and a SQLite backend but ~zero data. Hooks should extract `subject/predicate/object` triples on every save using heuristics (no LLM — `project → has_file → path`, `session → discussed → room` patterns). Normalize entity IDs (lowercase, strip punctuation, collapse whitespace). Alias table + Levenshtein < 2 for fuzzy matches. Prerequisite for contradiction detection.

### P5 — Temporal fact validity *(1 day, depends on P4)*

KG triples get `valid_from` / `valid_to` timestamps. On write, close any existing triple with the same subject+predicate before opening a new one. Enables contradiction surfacing (`SELECT ... WHERE valid_to IS NULL GROUP BY subject, predicate HAVING COUNT(*) > 1`). Reference: Zep/Graphiti's temporal graph model.

### P6 — Input sanitization on writes *(half day)*

Strip known injection patterns (role-play instructions, "ignore previous instructions"). Flag with `sanitized: true` metadata rather than blocking. Length cap at 10K chars. Low priority while we're local-only; matters if the MCP server is ever exposed more broadly.

### Deprioritized

- **AAAK work** — upstream's problem; we store verbatim.
- **Hierarchy improvements** — tunnels, closets, new room types. The hierarchy isn't the value.
- **Benchmark work** — our value is "134K drawers of verbatim local history with fast search", not upstream's LongMemEval score.
- **Full architecture rewrite** — not worth the migration cost.
- **Dual-granularity ANN, dream engine, foresight signals** — Karta-inspired features that require LLM calls on every write. Our zero-LLM philosophy makes these opt-in at best.
- **FTS5 parallel index** — right idea (engram proves it), but significant infrastructure alongside ChromaDB. Revisit after tags and decay are proven.

## Open problems

### Auto-surfacing context Claude doesn't know to ask for

Claude frequently makes wrong assumptions when the correct info exists in MemPalace, because it doesn't know to search. This is a **consumption problem, not a storage problem** — the write path (hooks, mining) is solid; the read path works when triggered. The gap is automatic surfacing at the moment of need.

What didn't work: SessionStart pre-loading, auto-memory bridges, PreCompact re-reads, CLAUDE.md instructions to "always query mempalace". What might work: [engram](https://github.com/NickCirv/engram)-style file-read interception that injects MemPalace context alongside code structure ([discussion #798](https://github.com/MemPalace/mempalace/discussions/798)). Only covers code-level assumptions, not workflow/config. No memory system has solved this well — it's the unsolved problem of the [OSS Insight Agent Memory Race](https://ossinsight.io/blog/agent-memory-race-2026).

### Stale auto-loaded docs

Knowledge lives across 7+ layers: global CLAUDE.md, project CLAUDE.md, auto-memory (14 files), docs/, superpowers specs, code comments, MemPalace. The auto-loaded layers go stale and actively mislead Claude. Ironically MemPalace is the only layer that *can't* go stale (verbatim + timestamped) but it's the only one that's never auto-loaded.

**Fix before any fork feature work:** audit every auto-loaded layer, date-stamp facts that can change, reduce duplication (one home per fact). Planned `/verify-docs` slash command pattern-matches version strings, file paths, PR numbers, URLs, and verifies against current state — then integrates into `/housekeep`. Cleaning stale docs prevents more wrong assumptions than any amount of auto-querying.

### Two-layer memory architecture

Claude Code has two complementary memory layers, used in tandem:

| Layer | Storage | Size | Consolidation | Purpose |
|-------|---------|------|---------------|---------|
| **Auto-memory** | `~/.claude/projects/*/memory/*.md` | ~dozens of files | None (manual writes) | Preferences, feedback, context |
| **MemPalace** | `~/.mempalace/palace/` (ChromaDB) | 134K+ drawers | None (write-only archive) | Verbatim conversations, tool output, code |

Neither has automatic consolidation. Claude Code has unreleased "Auto Dream" consolidation code behind a disabled feature flag ([#38461](https://github.com/anthropics/claude-code/issues/38461)) — if it ships, it covers only the lightweight layer. MemPalace decay (P2) and feedback (P3) remain the right priorities for the verbatim archive.

## Open upstream PRs

| PR | Status | Description |
|----|--------|-------------|
| [#629](https://github.com/milla-jovovich/mempalace/pull/629) | dirty, lower priority | Batch writes, concurrent mining |
| [#632](https://github.com/milla-jovovich/mempalace/pull/632) | dirty, lower priority | Repair, purge, --version |
| [#659](https://github.com/milla-jovovich/mempalace/pull/659) | clean, waiting review | Diary wing parameter |
| [#660](https://github.com/milla-jovovich/mempalace/pull/660) | clean, waiting review | L1 importance pre-filter |
| [#661](https://github.com/milla-jovovich/mempalace/pull/661) | feedback addressed, waiting re-review | Graph cache with write-invalidation |
| [#673](https://github.com/milla-jovovich/mempalace/pull/673) | needs semantic rebase against #863 | Deterministic hook saves |
| [#681](https://github.com/milla-jovovich/mempalace/pull/681) | clean, waiting review | Unicode checkmark → ASCII |

Closed: #626, #633, #662 (superseded by BM25), #663 (upstream wrote #757), #738 (docs stale).

## Setup

```bash
git clone https://github.com/jphein/mempalace.git
cd mempalace
python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"

mempalace init ~/Projects --yes
mempalace mine ~/Projects/myproject
mempalace status
```

## Development

```bash
source venv/bin/activate
python -m pytest tests/ -q              # ~900 tests (benchmarks deselected)
mempalace status                         # palace health
ruff check . && ruff format --check .    # lint + format
```

## License

MIT — see [LICENSE](LICENSE).

<!-- Link Definitions -->
[version-shield]: https://img.shields.io/badge/version-3.3.0-4dc9f6?style=flat-square&labelColor=0a0e14
[release-link]: https://github.com/MemPalace/mempalace/releases
[python-shield]: https://img.shields.io/badge/python-3.9+-7dd8f8?style=flat-square&labelColor=0a0e14&logo=python&logoColor=7dd8f8
[python-link]: https://www.python.org/
[license-shield]: https://img.shields.io/badge/license-MIT-b0e8ff?style=flat-square&labelColor=0a0e14
[license-link]: https://github.com/jphein/mempalace/blob/main/LICENSE
