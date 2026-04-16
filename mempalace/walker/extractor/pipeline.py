"""Async orchestrator: GLiNER batch -> Qwen per-drawer -> upsert_triple -> mark_extracted."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from mempalace.knowledge_graph import KnowledgeGraph
from mempalace.walker.extractor.gliner_ner import GlinerNER
from mempalace.walker.extractor.qwen_rel import QwenRelExtractor, Triple
from mempalace.walker.extractor.state import ExtractionState

log = logging.getLogger(__name__)


@dataclass(slots=True)
class ExtractionStats:
    drawers_processed: int = 0
    drawers_skipped: int = 0
    entities_found: int = 0
    triples_inserted: int = 0
    triples_updated: int = 0
    qwen_failures: int = 0
    elapsed_secs: float = 0.0
    # Note: circuit_open_events intentionally omitted in Phase 1 — the
    # pipeline cannot observe breaker state from inside. Wire up in Phase 2.


async def extract_drawers(
    drawers: list[dict],
    kg: KnowledgeGraph,
    state: ExtractionState,
    gliner: GlinerNER,
    qwen: QwenRelExtractor,
    extractor_version: str = "v1.0",
    concurrency: int = 4,
    dry_run: bool = False,
) -> ExtractionStats:
    """Run the extraction pipeline over drawers. Per-drawer atomicity."""
    stats = ExtractionStats()
    start = time.monotonic()

    if not drawers:
        stats.elapsed_secs = time.monotonic() - start
        return stats

    drawer_by_id = {d["id"]: d for d in drawers}
    unextracted_ids = state.unextracted_ids(list(drawer_by_id.keys()), extractor_version)
    stats.drawers_skipped = len(drawers) - len(unextracted_ids)

    if not unextracted_ids:
        stats.elapsed_secs = time.monotonic() - start
        return stats

    unextracted = [drawer_by_id[i] for i in unextracted_ids]
    texts = [d["text"] for d in unextracted]

    loop = asyncio.get_running_loop()
    entities_per_drawer = await loop.run_in_executor(
        None, gliner.extract_batch, texts
    )

    stats_lock = asyncio.Lock()
    sem = asyncio.Semaphore(concurrency)

    async def process(drawer, entities):
        async with sem:
            await _process_single(
                drawer, entities, kg, state, qwen,
                extractor_version, dry_run, stats, stats_lock,
            )

    await asyncio.gather(*[
        process(d, ents) for d, ents in zip(unextracted, entities_per_drawer)
    ])

    stats.elapsed_secs = time.monotonic() - start
    return stats


async def _process_single(
    drawer, entities, kg, state, qwen,
    version, dry_run, stats, stats_lock,
):
    drawer_id = drawer["id"]
    text = drawer["text"]
    entity_count = len(entities)

    async with stats_lock:
        stats.entities_found += entity_count

    if entity_count == 0:
        async with stats_lock:
            stats.drawers_processed += 1
        if not dry_run:
            state.mark_extracted(drawer_id, version, triple_count=0, entity_count=0)
        return

    try:
        triples: list[Triple] = await qwen.extract(text, entities)
    except Exception as e:
        log.warning("Qwen extract failed for %s: %s", drawer_id, e)
        async with stats_lock:
            stats.qwen_failures += 1
        triples = []

    if dry_run:
        for t in triples:
            print(f"[DRY] {drawer_id}: {t.subject} -[{t.predicate}]-> {t.object}")
        async with stats_lock:
            stats.drawers_processed += 1
        return

    all_ok = True
    inserted_n = 0
    updated_n = 0
    source_tag = f"extractor_{version}"
    for t in triples:
        try:
            result = kg.upsert_triple(
                subject=t.subject,
                predicate=t.predicate,
                obj=t.object,
                source=source_tag,
                source_drawer_ids=[drawer_id],
            )
            if result.inserted:
                inserted_n += 1
            elif result.updated:
                updated_n += 1
        except Exception as e:
            log.error("upsert_triple failed on %s: %s", drawer_id, e)
            all_ok = False

    async with stats_lock:
        stats.triples_inserted += inserted_n
        stats.triples_updated += updated_n

    if all_ok:
        async with stats_lock:
            stats.drawers_processed += 1
        state.mark_extracted(
            drawer_id, version,
            triple_count=len(triples), entity_count=entity_count,
        )
    else:
        log.warning("Drawer %s had upsert failures — not marking extracted", drawer_id)
