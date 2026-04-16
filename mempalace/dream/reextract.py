"""Dream Job A — re-extract palace drawers not yet at `version`."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from mempalace.knowledge_graph import KnowledgeGraph
from mempalace.walker.extractor.gliner_ner import GlinerNER
from mempalace.walker.extractor.pipeline import ExtractionStats, extract_drawers
from mempalace.walker.extractor.qwen_rel import QwenRelExtractor
from mempalace.walker.extractor.state import ExtractionState

log = logging.getLogger(__name__)
DREAM_LOG_PATH = Path.home() / ".mempalace" / "dream_log.jsonl"


@dataclass(slots=True)
class JobAResult:
    job: str
    version: str
    started_at: str
    elapsed_secs: float
    drawers_processed: int
    drawers_skipped: int
    triples_inserted: int
    triples_updated: int
    qwen_failures: int
    batches: int


async def run_job_a(
    palace_path: str,
    kg: KnowledgeGraph,
    version: str = "v1.0",
    batch_size: int = 500,
    wing: str | None = None,
    dry_run: bool = False,
    qwen_url: str = "http://localhost:43100",
) -> JobAResult:
    """Re-extract drawers not yet at version. Idempotent, batch-safe."""
    started_at = datetime.now(timezone.utc).isoformat()
    start = time.monotonic()

    drawers = await _load_drawers_from_palace(palace_path, wing)
    gliner = _build_gliner()
    qwen = _build_qwen(qwen_url)
    state = ExtractionState(kg)

    totals = ExtractionStats()
    batches_run = 0
    try:
        for i in range(0, len(drawers), batch_size):
            batch = drawers[i : i + batch_size]
            batches_run += 1
            stats = await extract_drawers(
                drawers=batch,
                kg=kg,
                state=state,
                gliner=gliner,
                qwen=qwen,
                extractor_version=version,
                dry_run=dry_run,
            )
            totals.drawers_processed += stats.drawers_processed
            totals.drawers_skipped += stats.drawers_skipped
            totals.triples_inserted += stats.triples_inserted
            totals.triples_updated += stats.triples_updated
            totals.qwen_failures += stats.qwen_failures
    finally:
        await qwen.aclose()

    elapsed = time.monotonic() - start
    result = JobAResult(
        job="A",
        version=version,
        started_at=started_at,
        elapsed_secs=elapsed,
        drawers_processed=totals.drawers_processed,
        drawers_skipped=totals.drawers_skipped,
        triples_inserted=totals.triples_inserted,
        triples_updated=totals.triples_updated,
        qwen_failures=totals.qwen_failures,
        batches=batches_run,
    )

    if not dry_run:
        _append_dream_log(result)

    return result


async def _load_drawers_from_palace(palace_path: str, wing: str | None = None) -> list[dict]:
    from mempalace.backends.chroma import ChromaBackend

    backend = ChromaBackend()
    return list(backend.iter_drawers(palace_path, wing=wing))


def _build_gliner() -> GlinerNER:
    return GlinerNER()


def _build_qwen(url: str) -> QwenRelExtractor:
    return QwenRelExtractor(base_url=url)


def _append_dream_log(result: JobAResult) -> None:
    try:
        DREAM_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DREAM_LOG_PATH.open("a") as f:
            f.write(json.dumps(asdict(result)) + "\n")
    except Exception as e:
        log.warning("Failed to write dream log: %s", e)
