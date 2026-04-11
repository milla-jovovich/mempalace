# Fork Improvements — TODO

Gaps identified from [lhl/agentic-memory analysis](https://github.com/lhl/agentic-memory/blob/main/ANALYSIS-mempalace.md) cross-referenced against our own codebase audit and the full [agentic-memory survey](https://github.com/lhl/agentic-memory) (2026-04-11).

**Why we're staying on MemPalace:** It's the only MCP-native local memory system that works with Claude Code today. Every alternative (Karta, Gigabrain, ByteRover, Codex memory, OpenViking) would need an MCP wrapper written before it could be used. The gaps below are real but fixable.

**Patterns to steal from the survey:**
- [Karta](https://github.com/rohithzr/karta) — contradiction detection, dream engine feedback loop, foresight signals, dual-granularity search, 14-step read pipeline with abstention
- [Gigabrain](https://github.com/legendaryvibecoder/gigabrain) — 30+ junk filter patterns on write, event-sourced audit trail, nightly 8-stage maintenance
- [Codex memory](https://github.com/openai/codex) — citation-driven retention (usage_count from retrieval → selection → pruning), two-phase extraction→consolidation
- [ByteRover CLI](https://github.com/campfirein/byterover-cli) — 5-tier progressive retrieval (exact cache → fuzzy cache → index → LLM → agentic)

Items ordered by implementation priority: quick wins first, then feature gaps, then deeper work.

---

## 0. ~~Fix convo_miner wing assignment~~ ✓ (b7376ee)

**Bug:** Auto-mined conversation transcripts all land in generic `sessions` wing. The project name is in the path (`~/.claude/projects/-home-jp-Projects-kiyo-xhci-fix/`) but `convo_miner.py:250` derives the wing from the parent directory name, losing project context. Manual `add_drawer` calls to project-specific wings work, but auto-mined content is unfindable by project.

**Files:**
- Modify: `mempalace/convo_miner.py` — `mine_convos()` wing derivation
- Modify: `mempalace/hooks_cli.py` — hook auto-mine wing parameter
- Test: `tests/test_convo_miner.py`

**Approach:**
1. When source path matches `~/.claude/projects/-home-*-Projects-<name>/`, extract `<name>` as the wing
2. Fallback to current behavior (directory name) for non-Claude-Code paths
3. Hook auto-mine should pass the derived project wing, not hardcoded `sessions`

**Why this first:** This is a bug, not a feature request. Auto-mined content is going to the wrong wing, making per-project search fail. Discovered when searching `wing: "kiyo-xhci-fix"` returned 0 results despite 335 mempalace mentions in the session transcript.

---

## 1. ~~Hybrid search fallback~~ ✓ (b7376ee)

**Gap:** ChromaDB vector-only search. Exact-match queries ("error code E4021") rely entirely on embedding proximity, which misses when semantic meaning doesn't cluster near the literal string.

**Files:**
- Modify: `mempalace/searcher.py` — `search_memories()`
- Modify: `mempalace/mcp_server.py` — `tool_search()` schema (add `keyword` param)
- Test: `tests/test_searcher.py`

**Approach:**
1. After vector search, if top result distance > 1.0 (poor match), re-query with `where_document={"$contains": keyword}` as a keyword fallback
2. Extract keyword: longest non-stopword token from query, or explicit `keyword` param
3. Merge + deduplicate results (union, sort by distance)
4. ChromaDB `where_document` is already built-in — zero new dependencies

**Why this first:** Lowest risk, highest immediate value. Pure additive — doesn't change existing search behavior for good queries. Covers the class of failures where users search for specific error codes, config keys, or exact phrases.

---

## 2. Graph cache with write-invalidation (half day)

**Gap:** `palace_graph.py:build_graph()` scans every drawer's metadata in 1000-item batches on every call. O(n) per graph build, no caching. At 50K+ drawers this is seconds per MCP tool call for traverse/tunnels/graph_stats.

**Files:**
- Modify: `mempalace/palace_graph.py` — add module-level cache
- Test: `tests/test_palace_graph.py`

**Approach:**
1. Module-level `_graph_cache = {"nodes": None, "edges": None, "built_at": 0.0}`
2. `build_graph()` checks cache age — if < TTL (e.g., 60s), return cached
3. `invalidate_graph_cache()` function, called from `palace.py` on any upsert/delete
4. MCP server's `_metadata_cache` invalidation pattern already exists — mirror it

**Why:** Silent perf regression that gets worse as the palace grows. Fix is ~30 lines and eliminates redundant full-scans during multi-tool MCP conversations.

---

## 3. L1 loading optimization (half day)

**Gap:** L1 layer loads top-15 drawers by importance by iterating *all* metadata. O(n) on every wake-up. The analysis flags this as a scale concern at 100K+ drawers.

**Files:**
- Modify: `mempalace/layers.py` — L1 loading function
- Test: `tests/test_layers.py`

**Approach:**
1. Use ChromaDB `where={"importance": {"$gte": threshold}}` to pre-filter before sorting — only scan drawers with importance metadata set
2. If too few results, fall back to current full scan
3. Alternative: maintain a small SQLite "pinned" index (top-100 by importance) updated on writes — avoids ChromaDB scan entirely

**Why:** Every MCP session start pays this cost. At current scale (~50K drawers) it's tolerable but growing. Fix before it becomes noticeable.

---

## 4. Decay / recency weighting (1 day)

**Gap:** All memories are equally weighted forever. No recency signal, no TTL, no age-based scoring. Palace gets noisier over time with no self-curation. Mnemosyne and Memoria both have this — MemPalace doesn't.

**Files:**
- Modify: `mempalace/searcher.py` — post-processing in `search_memories()`
- Modify: `mempalace/mcp_server.py` — `tool_search()` to update `last_accessed`
- Modify: `mempalace/palace.py` — upsert to set `last_accessed` on creation
- New: `mempalace/decay.py` — decay curve + prune CLI
- Test: `tests/test_decay.py`

**Approach:**
1. Add `last_accessed` (ISO timestamp) and `access_count` (int) to drawer metadata
2. On search hit: `col.update(ids=[id], metadatas=[{...existing, "last_accessed": now, "access_count": n+1}])`
3. Post-process search results: `adjusted_distance = distance * decay_penalty(age, access_count)`
4. Decay curve: configurable via `~/.mempalace/config.json`, default OFF (opt-in)
5. CLI: `mempalace prune --stale-days 180 --min-accesses 0 --dry-run` — lists/removes never-accessed old drawers

**Design decisions needed:**
- Decay curve shape: linear, exponential, or step function?
- Should `access_count` boost resist decay (frequently accessed = sticky)?
- Should decay apply to KG triples too, or just drawers?
- Default: off (preserve current behavior) or on (opinionated)?

**Why:** The "write-only archive" problem. Without decay, retrieval quality degrades as the palace fills. But tuning matters — too aggressive loses valuable old memories. Ship as opt-in with conservative defaults.

---

## 5. Feedback loops (1-2 days)

**Gap:** No "was this useful?" signal. No echo/fizzle tracking. The system can't learn which memories matter. Every retrieved memory is treated identically regardless of whether it helped.

**Files:**
- New: `mempalace/feedback.py` — rating storage + query history
- Modify: `mempalace/mcp_server.py` — new `mempalace_rate_memory` tool + query log
- Modify: `mempalace/searcher.py` — feedback-aware ranking
- Test: `tests/test_feedback.py`

**Approach — two tiers:**

### Tier 1: Manual rating (easy, 2-3 hours)
1. New MCP tool: `mempalace_rate_memory(drawer_id, useful: bool)`
2. Store `useful_count` / `not_useful_count` in drawer metadata
3. Search results boost: useful memories rank higher, flagged-not-useful get demoted
4. CLI: `mempalace feedback --stats` — show most/least useful memories

### Tier 2: Implicit signals (harder, 1+ day)
1. Query history table (SQLite): query text, returned drawer IDs, timestamp
2. Track which drawers get repeatedly retrieved for different queries (echo = broadly useful)
3. Track which drawers are retrieved but never rated useful (fizzle = noise)
4. Auto-adjust ranking weights based on echo/fizzle ratio
5. Weekly digest: "these 10 memories are never useful, consider pruning"

**Ship Tier 1 first.** Tier 2 depends on having enough query history to be meaningful — needs weeks of usage data before the signals are useful.

---

## 6. KG entity resolution (1 day)

**Gap:** Entity ID is a naive slug (`alice_obrien`). No fuzzy matching, no alias table. Adding a KG triple with slightly different spelling creates a duplicate entity. The analysis calls this "fragility."

**Files:**
- Modify: `mempalace/knowledge_graph.py` — entity lookup + alias table
- Test: `tests/test_knowledge_graph.py`

**Approach:**
1. New `entity_aliases` table: `(alias TEXT, canonical_id TEXT)`
2. On `add_entity` / `add_triple`: check aliases before creating new entity
3. Fuzzy match: normalize (lowercase, strip punctuation, collapse whitespace) then check Levenshtein distance < 2
4. MCP tool: `mempalace_kg_merge(entity_a, entity_b)` — merge two entities that are the same person/thing
5. On query: resolve through aliases transparently

**Why:** Anyone adding KG triples manually (via MCP) will hit this. "Alice O'Brien" vs "alice" vs "Alice" shouldn't be three entities.

---

## 7. Input sanitization on writes (half day)

**Gap:** No content sanitization on `add_drawer`. Prompt injection surface — an adversarial memory could instruct the AI. The analysis flags this as a security concern.

**Files:**
- New: `mempalace/sanitizer.py` — content sanitizer
- Modify: `mempalace/mcp_server.py` — `tool_add_drawer()`, `tool_update_drawer()`
- Modify: `mempalace/palace.py` — `upsert_drawers()`
- Test: `tests/test_sanitizer.py`

**Approach:**
1. Strip known injection patterns: system prompt overrides, role-play instructions, "ignore previous instructions"
2. Flag but don't block: add `sanitized: true` metadata if content was modified
3. Length cap: reject drawers > 10K chars (chunking should prevent this, but belt+suspenders)
4. Log sanitization events for audit

**Why:** Low effort, reduces attack surface. Not critical today (write access is local) but matters if the MCP server is ever exposed more broadly.

---

## Upstream PR candidates

Items 1-3 (hybrid search, graph cache, L1 optimization) are pure improvements with no design controversy — good PR material if upstream is receptive.

Items 4-5 (decay, feedback) are opinionated — better as fork features first, upstreamed after proven.

Items 6-7 (entity resolution, sanitization) could go either way.

## Future: Karta-inspired features (after TODOs 0-7)

These are more ambitious features inspired by [Karta's architecture](https://github.com/lhl/agentic-memory/blob/main/ANALYSIS-karta.md). Not immediate work, but worth tracking.

### Contradiction detection
KG triples with conflicting values (e.g., two different `works_at` for the same entity) should be flagged, not silently accumulated. Requires entity resolution (#6) first. Karta's approach: dream engine scans clusters, LLM detects conflicts, contradiction notes are force-injected into retrieval.

**Simpler version for us:** SQL query for entities with multiple open triples on the same predicate. No LLM needed — just `SELECT * FROM triples WHERE subject=? AND predicate=? AND valid_to IS NULL GROUP BY predicate HAVING COUNT(*) > 1`. Surface via `mempalace_kg_query` as a warning.

### Foresight signals
Karta stores forward-looking predictions ("this project will need X") with TTL expiry windows. During retrieval, active predictions get a score boost. Expired ones are pruned by the dream engine.

**Simpler version for us:** New metadata field `prediction_ttl` on drawers. Drawers with expired TTL get demoted in search. Could be useful for project planning memories that have a natural expiry.

### Query classification
Karta classifies queries into 6 modes (Standard, Recency, Breadth, Computation, Temporal, Existence) via embedding similarity to prototype centroids, then adjusts retrieval behavior per mode.

**Simpler version for us:** Keyword heuristics. If query contains "how many" → widen n_results. If query contains "when" or "latest" → boost recency. If query contains "all" or "everything about" → search multiple wings. No embeddings needed.

## Not pursuing (and why)

- **AAAK overhaul**: upstream's problem, not ours. We store verbatim.
- **Multi-collection sharding**: premature. Single collection works to ~500K drawers.
- **LLM-based extraction**: deliberate design choice. Zero-LLM write path is a feature, not a bug. If we add LLM extraction, it should be opt-in and additive, not replacing the deterministic pipeline.
- **Dream engine (Karta-style)**: Fascinating but requires LLM calls on every dream pass. Karta's 7-type inference engine is 952 lines of Rust prompting GPT — beautiful architecture, wrong cost model for us. Our zero-LLM philosophy means we'd need a local model or explicit opt-in.
- **Dual-granularity ANN**: Karta searches notes AND atomic facts in parallel, expanding fact hits to parent notes. Would require a second ChromaDB collection for facts. Premature — fix basic search quality (#1 hybrid) first.
- **Full event sourcing (Gigabrain-style)**: Append-only event log for every write/reject/dedup. Overkill for local use. Our provenance metadata (source_file, filed_at, added_by) covers 80% of the audit need.
