"""Fine-grained profiler for PalaceStore.query().

Breaks the query hot path into 11 phases and reports per-query time +
percentage of total for each. Runs across small/medium/large/stress at
all three filter shapes (unfiltered, wing, wing_room).

Instrumentation has ~25-50 µs/query overhead from perf_counter_ns calls.
At small scale that's a meaningful fraction of total query time; the
percentages remain directionally correct but absolute µs are biased
upward. For absolute numbers use bench_query.py; for *where time goes*
this is the right tool.

Usage:
    uv run python -m benchmarks.storage.profile_query
    uv run python -m benchmarks.storage.profile_query --scales small medium
    uv run python -m benchmarks.storage.profile_query --n-queries 200
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from palace_store.store import VECTOR_DTYPE, QueryResult

from .adapters.palace import PalaceAdapter
from .dataset import SCALE_CONFIGS, generate
from .recall_gate import _bulk_ingest


PHASES = [
    "01_shard_selection",  # wings list construction (dict.keys() copy)
    "02_shard_setup",      # per-shard: dict lookups for shard/buf/mask/labels
    "03_matmul",           # BLAS sgemv via np.matmul(out=)
    "04_mask_build",       # assemble alive mask (live & room_ok)
    "05_mask_apply",       # np.putmask(scores, ~alive, -inf)
    "06_count_alive",      # int(np.count_nonzero(alive))
    "07_argpartition",     # top-k selection
    "08_candidate_build",  # per-shard: append (score, wing, row) tuples
    "09_merge_sort",       # global candidate sort + slice to k
    "10_sql_hydrate",      # _lookup_candidates SQL JOIN
    "11_result_build",     # QueryResult dataclass construction
]


def _instrumented_query(
    store,
    query_vector: np.ndarray,
    k: int,
    where: dict[str, Any] | None,
    timings: dict[str, list[int]],
) -> list[QueryResult]:
    """Replica of PalaceStore.query() with perf_counter_ns at every phase.

    Writes per-phase durations (in ns) into the ``timings`` dict by
    appending to per-phase lists. The total wall-clock is written to
    the ``00_total`` key.
    """
    clock = time.perf_counter_ns
    total_start = clock()

    if query_vector.dtype != VECTOR_DTYPE:
        query_vector = query_vector.astype(VECTOR_DTYPE, copy=False)

    where = where or {}
    wing_filter = where.get("wing")
    room_filter = where.get("room")

    # 01 shard_selection
    t0 = clock()
    if wing_filter is not None:
        wings = [wing_filter] if wing_filter in store._shards else []
    else:
        wings = list(store._shards.keys())
    timings["01_shard_selection"].append(clock() - t0)

    if not wings:
        timings["00_total"].append(clock() - total_start)
        return []

    neg_inf = np.float32(-np.inf)
    candidates: list[tuple[float, str, int]] = []

    for wing in wings:
        # 02 shard_setup
        t0 = clock()
        shard = store._shards[wing]
        n_rows = shard.num_rows()
        if n_rows == 0:
            timings["02_shard_setup"].append(clock() - t0)
            continue
        scores = store._score_bufs.get(wing)
        if scores is None or scores.shape[0] != n_rows:
            scores = np.empty(n_rows, dtype=VECTOR_DTYPE)
            store._score_bufs[wing] = scores
        live = store._live_masks.get(wing)
        labels = store._room_labels.get(wing) if room_filter is not None else None
        timings["02_shard_setup"].append(clock() - t0)

        # 03 matmul
        t0 = clock()
        shard.compute_scores(query_vector, scores)
        timings["03_matmul"].append(clock() - t0)

        # 04 mask_build
        t0 = clock()
        if live is None or len(live) < n_rows:
            alive = np.zeros(n_rows, dtype=bool)
            if live is not None:
                alive[: len(live)] = live
        else:
            alive = live[:n_rows]
        if room_filter is not None:
            if labels is None or len(labels) < n_rows:
                room_ok = np.zeros(n_rows, dtype=bool)
                if labels is not None:
                    room_ok[: len(labels)] = labels == room_filter
            else:
                room_ok = labels[:n_rows] == room_filter
            alive = alive & room_ok
        timings["04_mask_build"].append(clock() - t0)

        # 05 mask_apply
        t0 = clock()
        np.putmask(scores, ~alive, neg_inf)
        timings["05_mask_apply"].append(clock() - t0)

        # 06 count_alive
        t0 = clock()
        n_alive = int(np.count_nonzero(alive))
        timings["06_count_alive"].append(clock() - t0)

        if n_alive == 0:
            continue

        # 07 argpartition
        t0 = clock()
        k_local = min(k, n_alive)
        if k_local < n_rows:
            part = np.argpartition(-scores, k_local - 1)[:k_local]
            order = part[np.argsort(-scores[part])]
        else:
            order = np.argsort(-scores)[:k_local]
        timings["07_argpartition"].append(clock() - t0)

        # 08 candidate_build
        t0 = clock()
        for row in order:
            s = float(scores[row])
            if s == float("-inf"):
                continue
            candidates.append((s, wing, int(row)))
        timings["08_candidate_build"].append(clock() - t0)

    if not candidates:
        timings["00_total"].append(clock() - total_start)
        return []

    # 09 merge_sort
    t0 = clock()
    candidates.sort(key=lambda t: -t[0])
    candidates = candidates[:k]
    timings["09_merge_sort"].append(clock() - t0)

    # 10 sql_hydrate
    t0 = clock()
    keys = [(w, r) for _, w, r in candidates]
    rows = store._lookup_candidates(keys)
    timings["10_sql_hydrate"].append(clock() - t0)

    # 11 result_build
    t0 = clock()
    row_by_key = {(r["wing"], r["shard_row"]): r for r in rows}
    results: list[QueryResult] = []
    for score, wing, row in candidates:
        r = row_by_key.get((wing, row))
        if r is None:
            continue
        results.append(
            QueryResult(
                id=r["id"],
                score=score,
                text=r["text"],
                wing=r["wing"],
                room=r["room"],
                metadata=json.loads(r["extra_json"]) if r["extra_json"] else {},
            )
        )
    timings["11_result_build"].append(clock() - t0)

    timings["00_total"].append(clock() - total_start)
    return results


def profile_scale(
    scale: str,
    n_queries: int,
    work_root: Path,
) -> dict[str, Any]:
    """Profile one scale across all three query shapes."""
    print(f"\n=== {scale} (N={SCALE_CONFIGS[scale]['drawers']}, "
          f"wings={SCALE_CONFIGS[scale]['wings']}) ===")

    store_path = work_root / f"palace_{scale}"
    if store_path.exists():
        shutil.rmtree(store_path)

    ds = generate(scale, seed=1337, compute_ground_truth=False)
    adapter = PalaceAdapter(store_path)

    print(f"  ingesting N={ds.n}...", end=" ", flush=True)
    t0 = time.perf_counter_ns()
    _bulk_ingest(adapter, ds, batch=512)
    print(f"{(time.perf_counter_ns() - t0) / 1e9:.1f}s")

    store = adapter._store
    print("  warming pages...", flush=True)
    store.warm_pages()

    # Bucket queries by shape
    shape_queries = {
        "unfiltered": [
            (qi, w) for qi, w in enumerate(ds.query_wheres) if w is None
        ],
        "wing": [
            (qi, w)
            for qi, w in enumerate(ds.query_wheres)
            if w is not None and "room" not in w
        ],
        "wing_room": [
            (qi, w)
            for qi, w in enumerate(ds.query_wheres)
            if w is not None and "room" in w
        ],
    }

    # Warmup run (not counted)
    for qi in range(min(30, ds.q)):
        _instrumented_query(
            store,
            ds.query_vectors[qi],
            10,
            ds.query_wheres[qi],
            defaultdict(list),
        )

    scale_report: dict[str, Any] = {
        "scale": scale,
        "n": ds.n,
        "wings": SCALE_CONFIGS[scale]["wings"],
        "shapes": {},
    }

    for shape_name, shape_q in shape_queries.items():
        if not shape_q:
            continue

        timings: dict[str, list[int]] = defaultdict(list)
        # Run n_queries (cycling through the shape's queries)
        for i in range(n_queries):
            qi, where = shape_q[i % len(shape_q)]
            _instrumented_query(
                store,
                ds.query_vectors[qi],
                10,
                where,
                timings,
            )

        totals = timings["00_total"]
        total_median_ns = sorted(totals)[len(totals) // 2]
        total_sum_ns = sum(totals)

        print(
            f"\n  shape={shape_name} "
            f"(n_queries={n_queries}, median={total_median_ns / 1000:.1f} µs/query)"
        )
        print(f"  {'phase':<22} {'µs/query':>10} {'%total':>8} {'calls':>8}")
        print(f"  {'-' * 22} {'-' * 10} {'-' * 8} {'-' * 8}")

        shape_report: dict[str, Any] = {
            "n_queries": n_queries,
            "median_total_us": round(total_median_ns / 1000, 2),
            "phases": {},
        }

        for phase in PHASES:
            samples = timings.get(phase, [])
            if not samples:
                continue
            phase_total_ns = sum(samples)
            per_query_us = phase_total_ns / n_queries / 1000
            pct = phase_total_ns / total_sum_ns * 100 if total_sum_ns > 0 else 0.0
            n_calls_per_query = len(samples) / n_queries
            print(
                f"  {phase:<22} {per_query_us:>10.2f} {pct:>7.1f}% "
                f"{n_calls_per_query:>8.1f}"
            )
            shape_report["phases"][phase] = {
                "per_query_us": round(per_query_us, 2),
                "pct_of_total": round(pct, 2),
                "calls_per_query": round(n_calls_per_query, 2),
            }

        scale_report["shapes"][shape_name] = shape_report

    adapter.close()
    return scale_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scales",
        nargs="+",
        default=["small", "medium", "large", "stress"],
        choices=list(SCALE_CONFIGS.keys()),
    )
    parser.add_argument(
        "--n-queries",
        type=int,
        default=500,
        help="Number of queries per shape (cycled from dataset)",
    )
    parser.add_argument(
        "--work-root",
        type=Path,
        default=Path("/tmp/palace_profile"),
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    args.work_root.mkdir(parents=True, exist_ok=True)

    results = {
        "n_queries_per_shape": args.n_queries,
        "scales": {},
    }

    for scale in args.scales:
        results["scales"][scale] = profile_scale(
            scale, args.n_queries, args.work_root
        )

    if args.out:
        args.out.write_text(json.dumps(results, indent=2))
        print(f"\nwrote {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
