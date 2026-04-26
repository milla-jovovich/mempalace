# Downstream eval findings — what familiar v0.2.1 + multipass surfaced

**Date:** 2026-04-26
**Source:** familiar.realm.watch v0.2.0 → v0.2.1 release cycle, evaluated with multipass-structural-memory-eval against a live 151K-drawer ChromaDB-backed mempalace.
**Status:** Research notes. Not a fork-ahead change. May inform future mempalace work.

## Why this lives here

mempalace's default embedder (nomic-embed-text v1.5) and HNSW startup behavior were both cross-cut by issues found while evaluating a *downstream consumer* (familiar). The findings belong with mempalace because the root behaviors are mempalace's, even though the fixes shipped in the consumer.

## Finding 1 — nomic-embed-text v1.5 is punctuation-sensitive at the trailing position

A 30-question diagnostic corpus run through familiar's `/api/familiar/eval` endpoint scored `q13_graphpalace` as recall=0.0 even after writing a literally-matching drawer to the palace via `POST /memory`. Direct mempalace `/search` ranked the drawer at sim=0.562 (#1). The same query through familiar returned different drawers entirely with top sims around 0.42.

Diagnostic: the only difference between the two queries was a trailing `?`. Familiar passed the user's literal question (`What is GraphPalace and how does its pheromone model work?`); the manual probe dropped the question mark. nomic-embed-text v1.5 produces meaningfully different embeddings for `What is X` vs `What is X?` — enough to drop a known-good top-1 hit out of top-5.

### Fix (downstream — already shipped)

`familiar` v0.2.1 strips trailing `?!.,;:` at the palace-client layer before embedding. Internal punctuation (apostrophes, commas) is preserved.

```ts
const normalizedQ = opts.query.replace(/[?!.,;:]+\s*$/, "").trim();
```

### Implication for mempalace

mempalace's MCP `mempalace_search` and `/search` HTTP endpoint pass the query string straight to the embedder. Any consumer that submits natural-language questions (which is nearly all of them — Claude Code, palace-daemon, MCP agents) is at risk of the same off-by-one ranking shifts.

**Options** (in order of intrusiveness):

1. **Document the gotcha.** Add a one-paragraph note in the README's `mempalace_search` section. Lowest effort, highest reach.
2. **Normalize at the embedder boundary.** A small helper around the embed call that strips trailing sentence terminators. Mempalace controls this; consumers benefit transparently. Risk: minimal — internal punctuation untouched.
3. **Provide a `normalize_query=True` parameter** on the search APIs, defaulting to True, that consumers can opt out of for adversarial test cases.

**Recommendation**: option 2 is small, safe, and matches the punctuation-stripping pattern that's already proven correct in familiar v0.2.1. Worth a follow-on PR after the v3.1.1 stability patch lands.

## Finding 2 — HNSW segment load on cold start scales with drawer count

palace-daemon was observed taking ~4:48 to bind port 8085 after `systemctl --user restart` on the live 151K-drawer palace, before serving any requests. The python process was at 71% CPU throughout — not hung, just loading HNSW segments from disk into memory.

This caused two cascading problems:

- palace-daemon's `auto-repair-if-empty.sh` ExecStartPost script gave up at 30s ("daemon never came up — bailing"). Fix: bumped to 240s default, env-overrideable. Committed in palace-daemon `252ebf1`.
- familiar's healthcheck briefly (during the 4-minute window) showed `palace_daemon.recall_quality = probe_error` even though the daemon was correctly initializing. Familiar's existing distinction between `probe_error` and `empty_hnsw` made this readable from the consumer side.

### Implication for mempalace

The startup-time-per-drawer relationship isn't documented, but it's now a knob that affects every operator running a >100K-drawer palace:

- Surface palace-load progress via a startup log line every N segments. Even a "loaded 50K/150K" progress hint would let operators distinguish "daemon hung" from "daemon working hard."
- Consider a `mempalace status` CLI command that returns load-completion status without serving search traffic.
- The Postgres backend (#665) likely changes this characteristic significantly — segment-from-disk goes away, replaced by index page warmup. Worth measuring.

## Finding 3 — kind=content filter is load-bearing on autobiographical palaces

This is already addressed in mempalace via the `kind` parameter on `/search` (jphein-fork commit) and the recovery-collection migration (Phase D). Reaffirmed during today's eval: on JP's 151K-drawer palace where Stop-hook checkpoints make up the majority of writes, **every consumer that doesn't pass `kind=content` will see checkpoint fragments dominate vector similarity**. Familiar v0.2 hard-codes `kind=content` in palace-client.ts; this is the right call and should remain.

The implication for mempalace: the `kind` parameter is not optional UX. It's load-bearing, and the default (no filter / both kinds) becomes wrong as soon as Stop-hook activity grows. Consider making `kind=content` the default for the `/search` endpoint or at least surfacing a warning when `kind=all` is requested on a palace with >50% checkpoint drawers.

## Finding 4 — substring-on-context_string scoring is sufficient MVP signal

multipass-structural-memory-eval shipped a `FamiliarAdapter` that returns `context_string` (the rendered system prompt) as the scoring target. The eval substring-matches `expected_sources` against that string. No LLM judge, no entity matching, no semantic similarity — just literal substrings.

This worked. The 30-question corpus produced reproducible signal across two adapters (`familiar` and `mempalace-daemon`) and surfaced both palace gaps (q12 rlm flipped 0.0→1.0 after writing a drawer) and pipeline gaps (q13 GraphPalace stayed 0.0 because of the punctuation issue).

### Implication for mempalace

If mempalace adds its own eval suite (e.g., for verifying that Postgres-backend retrieval matches ChromaDB-backend retrieval on the same corpus), substring scoring is a fine starting point. A 30-question corpus per palace is cheap to author and makes regression testing across backends concrete.

## Cross-references

- familiar design spec: `~/Projects/familiar.realm.watch/docs/superpowers/specs/2026-04-23-familiar-realm-watch-design.md` — see "v0.2 retrospective" section
- multipass adapter design: `~/Projects/multipass-structural-memory-eval/docs/superpowers/specs/2026-04-26-familiar-adapter-design.md`
- multipass lessons: `~/Projects/multipass-structural-memory-eval/docs/ideas.md` — see "Lessons from the first live eval"
- palace-daemon auto-repair: `~/Projects/palace-daemon/scripts/auto-repair-if-empty.sh`
