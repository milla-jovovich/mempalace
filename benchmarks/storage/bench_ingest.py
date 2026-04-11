"""Ingest benchmark: bulk-upsert throughput + peak RSS during ingest.

Measures, for a fixed adapter and dataset:

    - drawers/second at batch sizes 1, 128, 512
    - peak RSS delta during the full ingest run
    - total on-disk bytes after the ingest completes

We deliberately do NOT embed anything here — vectors come pre-computed
from the dataset module so storage and embedding costs can't mix.
"""

from __future__ import annotations

from dataclasses import dataclass

from .dataset import BenchDataset
from .interface import StoreAdapter
from .measure import RSSPeakTracker, now_ns


@dataclass
class IngestResult:
    adapter: str
    n_total: int
    batch_size: int
    elapsed_s: float
    drawers_per_sec: float
    rss_start_mb: float
    rss_peak_mb: float
    rss_delta_mb: float
    disk_bytes: int


def run(
    adapter: StoreAdapter,
    dataset: BenchDataset,
    *,
    batch_size: int = 512,
) -> IngestResult:
    """Bulk-ingest ``dataset`` into ``adapter`` and return metrics."""
    n = dataset.n
    with RSSPeakTracker() as rss:
        t0 = now_ns()
        for i in range(0, n, batch_size):
            j = min(i + batch_size, n)
            adapter.upsert(
                ids=dataset.ids[i:j],
                vectors=dataset.vectors[i:j],
                metadatas=dataset.metadatas[i:j],
                texts=dataset.texts[i:j],
            )
            rss.sample()
        elapsed_ns = now_ns() - t0
    elapsed_s = elapsed_ns / 1e9
    return IngestResult(
        adapter=adapter.name,
        n_total=n,
        batch_size=batch_size,
        elapsed_s=round(elapsed_s, 4),
        drawers_per_sec=round(n / elapsed_s, 1) if elapsed_s > 0 else float("inf"),
        rss_start_mb=round(rss.start_mb, 2),
        rss_peak_mb=round(rss.peak_mb, 2),
        rss_delta_mb=round(rss.delta_mb, 2),
        disk_bytes=adapter.disk_bytes(),
    )
