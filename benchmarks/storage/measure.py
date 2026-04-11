"""Timing and memory measurement helpers.

Kept in its own module so every bench file uses the exact same primitives.
"""

from __future__ import annotations

import gc
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from statistics import median

import psutil


_process = psutil.Process(os.getpid())


def rss_mb() -> float:
    """Resident set size in MiB, sampled now."""
    return _process.memory_info().rss / (1024 * 1024)


def now_ns() -> int:
    """Monotonic counter in nanoseconds — use for timing, never wall clock."""
    return time.perf_counter_ns()


@dataclass
class RSSPeakTracker:
    """Tracks the high-water mark of RSS during a block.

    psutil doesn't give us a free kernel-level peak, so we poll at every
    ``sample()`` call. Callers should invoke ``sample()`` at iteration
    boundaries inside a loop. Worst-case we miss a transient spike
    between samples — good enough for the orders of magnitude we care
    about (tens of MiB).
    """

    start_mb: float = 0.0
    peak_mb: float = 0.0

    def __enter__(self) -> "RSSPeakTracker":
        gc.collect()
        self.start_mb = rss_mb()
        self.peak_mb = self.start_mb
        return self

    def sample(self) -> float:
        cur = rss_mb()
        if cur > self.peak_mb:
            self.peak_mb = cur
        return cur

    def __exit__(self, *exc) -> None:
        self.sample()

    @property
    def delta_mb(self) -> float:
        return self.peak_mb - self.start_mb


@contextmanager
def timed():
    """Context manager that yields a dict with {ns: int}; filled on exit."""
    out = {"ns": 0}
    t0 = now_ns()
    try:
        yield out
    finally:
        out["ns"] = now_ns() - t0


def percentiles(values_ns: list[int]) -> dict[str, float]:
    """p50/p95/p99 in milliseconds from a list of nanosecond samples."""
    if not values_ns:
        return {"p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "mean_ms": 0.0}
    s = sorted(values_ns)
    n = len(s)
    p50 = s[min(n - 1, int(0.50 * n))]
    p95 = s[min(n - 1, int(0.95 * n))]
    p99 = s[min(n - 1, int(0.99 * n))]
    mean = sum(s) / n
    return {
        "p50_ms": round(p50 / 1e6, 4),
        "p95_ms": round(p95 / 1e6, 4),
        "p99_ms": round(p99 / 1e6, 4),
        "mean_ms": round(mean / 1e6, 4),
        "median_ms": round(median(s) / 1e6, 4),
    }
