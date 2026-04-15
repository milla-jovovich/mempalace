# walk_regression.jsonl — Curation Guide

## Purpose

`walk_regression.jsonl` is the fixed regression suite for the MemPalace Walk subsystem. Its job is to catch regressions as the walker evolves across phases: if a question that passed at Phase 0 baseline silently breaks in Phase 2 or later, this file exposes it. Unlike the full LoCoMo benchmark (which measures aggregate recall across hundreds of questions), the regression file is curated by hand to cover the specific retrieval patterns the walker is designed to improve — temporal lookups and temporal-inference chains.

## Entry Format

Each line is a self-contained JSON object with these fields:

- `question_id` — stable identifier (e.g. `reg_001`). Never reuse or renumber IDs; retired entries should be deleted, not renumbered.
- `question` — the natural-language question exactly as it would be asked by a user or an LLM evaluation harness.
- `expected_entity` — the primary entity the question is about, in lowercase (e.g. `alice`). Used by the harness to scope graph traversal in walker mode.
- `expected_predicate` — the KG predicate type the question exercises (e.g. `works_at`, `decided`, `reports_to`). Documents the retrieval pattern, not a hard assertion.
- `category` — LoCoMo-compatible integer: `2` = Temporal, `3` = Temporal-inference. Only categories 2 and 3 belong in this file.
- `notes` — one-line description of what makes this question representative or tricky.

## Adding Good Questions

A good regression entry covers a pattern that has either (a) caused a real retrieval failure in the past or (b) represents a boundary case for the walker's graph traversal logic. Prefer questions where the answer requires crossing at least one temporal boundary — a date range, a "before/after" qualifier, or a state change. The entity and predicate fields should map to something that can realistically appear in a `KnowledgeGraph` triple so the walker test harness can verify graph coverage. Use real-sounding but fictional names (Alice, Ben, Carol, David) rather than generic placeholders.

## What Makes a Bad Entry

Avoid single-hop factual questions that a plain BM25 keyword search would trivially answer — those belong in the full LoCoMo suite, not here. Do not add questions whose answers cannot be expressed as a KG predicate-object pair (open-ended opinion questions, subjective summaries). Do not duplicate an existing pattern just with different names; each entry should exercise a structurally distinct retrieval path. Finally, never add entries whose `expected_entity` or `expected_predicate` cannot be produced by the current `entity_detector.py` / `knowledge_graph.py` pipeline, or the regression will be untestable.

## Maintenance

Run `python benchmarks/walk_bench.py` in regression mode (Phase 2+) after any change to `searcher.py`, `knowledge_graph.py`, or the walker subcommand to confirm no entries have regressed. If a question becomes permanently unresolvable due to a schema change, remove the entry and document the removal in the commit message. The file should stay small (10–30 entries); bulk additions belong in the full LoCoMo dataset.
