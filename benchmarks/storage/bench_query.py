"""Query benchmark: latency distribution + RSS during query phase.

Assumes the adapter has already been ingested. Runs the dataset's query
set (mix of unfiltered, wing-filtered, wing+room-filtered) and reports
latency percentiles grouped by filter shape.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .dataset import BenchDataset
from .interface import StoreAdapter
from .measure import RSSPeakTracker, now_ns, percentiles, rss_mb


@dataclass
class QueryResult:
    adapter: str
    n_queries: int
    k: int
    by_shape: dict[str, dict[str, Any]] = field(default_factory=dict)
    rss_steady_mb: float = 0.0
    rss_peak_mb: float = 0.0


def _shape_key(where: dict[str, Any] | None) -> str:
    if not where:
        return "unfiltered"
    if "room" in where:
        return "wing_room"
    return "wing"


def run(
    adapter: StoreAdapter,
    dataset: BenchDataset,
    *,
    k: int = 10,
    warmup: int = 10,
    warm_pages: bool = True,
    mlock: bool = False,
) -> QueryResult:
    # Warm the adapter's on-disk state into the page cache (no-op for
    # adapters that don't use mmap). Without this, the first queries
    # pay mmap first-touch cost and the p99 tail reflects paging, not
    # compute.
    if warm_pages:
        adapter.warm(mlock=mlock)

    # Warmup queries: run a few more after the warm pass to prime any
    # JIT paths / Python caches / query-plan caches. Timings discarded.
    for qi in range(min(warmup, dataset.q)):
        adapter.query(dataset.query_vectors[qi], k, where=dataset.query_wheres[qi])

    by_shape_ns: dict[str, list[int]] = defaultdict(list)
    by_shape_count: dict[str, int] = defaultdict(int)

    with RSSPeakTracker() as rss:
        for qi in range(dataset.q):
            where = dataset.query_wheres[qi]
            shape = _shape_key(where)
            t0 = now_ns()
            adapter.query(dataset.query_vectors[qi], k, where=where)
            elapsed_ns = now_ns() - t0
            by_shape_ns[shape].append(elapsed_ns)
            by_shape_count[shape] += 1
            if qi % 25 == 0:
                rss.sample()

    by_shape: dict[str, dict[str, Any]] = {}
    for shape, samples in by_shape_ns.items():
        by_shape[shape] = {
            "n": by_shape_count[shape],
            **percentiles(samples),
        }

    return QueryResult(
        adapter=adapter.name,
        n_queries=dataset.q,
        k=k,
        by_shape=by_shape,
        rss_steady_mb=round(rss_mb(), 2),
        rss_peak_mb=round(rss.peak_mb, 2),
    )
