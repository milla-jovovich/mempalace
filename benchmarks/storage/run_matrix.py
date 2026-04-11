"""Run the storage benchmark matrix and emit a JSON report.

Usage:

    uv run python -m benchmarks.storage.run_matrix --scale small
    uv run python -m benchmarks.storage.run_matrix --scale medium --adapters palace
    uv run python -m benchmarks.storage.run_matrix --scale large --out results.json

The matrix:

    {palace, chroma} × {ingest, query, footprint}

Each adapter runs in isolation on a fresh store directory. The recall
gate runs first at small scale to make sure both adapters are correct —
we refuse to publish timing numbers from a known-broken adapter.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .adapters.chroma import ChromaAdapter
from .adapters.palace import PalaceAdapter
from .adapters.palace_i8 import PalaceI8Adapter
from .dataset import generate
from .interface import StoreAdapter
from . import bench_footprint, bench_ingest, bench_query, recall_gate


ADAPTER_BUILDERS: dict[str, Any] = {
    "palace": PalaceAdapter,
    "palace_par": PalaceAdapter,  # same class, parallel_query=True via kwargs
    "palace_i8": PalaceI8Adapter,
    "chroma": ChromaAdapter,
}

# Adapter-specific kwargs passed into the constructor. Anything not in
# this dict is built with just the path.
ADAPTER_KWARGS: dict[str, dict[str, Any]] = {
    "palace_par": {"parallel_query": True},
}


def _build_adapter(name: str, path: Path) -> StoreAdapter:
    cls = ADAPTER_BUILDERS[name]
    return cls(path, **ADAPTER_KWARGS.get(name, {}))


def _system_info() -> dict[str, Any]:
    import os

    info = {
        "python": platform.python_version(),
        "os": platform.system().lower(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
    }
    try:
        import numpy as np

        info["numpy"] = np.__version__
    except Exception:
        pass
    try:
        import chromadb

        info["chromadb"] = chromadb.__version__
    except Exception:
        pass
    return info


def run_once(
    adapter_name: str,
    scale: str,
    work_root: Path,
    *,
    ingest_batch: int,
    k: int,
    skip_footprint: bool,
    cache_dir: Path | None,
    compute_ground_truth: bool = True,
    warm_pages: bool = True,
    mlock: bool = False,
) -> dict[str, Any]:
    """Generate a dataset, ingest it into a fresh adapter, run all three benches.

    Returns a dict with the full per-adapter results, ready to drop into
    the final JSON report.
    """
    print(f"\n== {adapter_name} @ {scale} ==", flush=True)

    store_path = work_root / f"{adapter_name}_{scale}"
    if store_path.exists():
        shutil.rmtree(store_path)

    dataset = generate(
        scale,
        seed=1337,
        gt_k=k,
        cache_dir=cache_dir,
        compute_ground_truth=compute_ground_truth,
    )
    print(f"  dataset N={dataset.n}  Q={dataset.q}", flush=True)

    adapter = _build_adapter(adapter_name, store_path)
    try:
        print("  ingest …", end=" ", flush=True)
        ingest_res = bench_ingest.run(adapter, dataset, batch_size=ingest_batch)
        print(
            f"{ingest_res.drawers_per_sec:>10.1f} drawers/s  "
            f"rss_peak={ingest_res.rss_peak_mb:.1f} MiB  "
            f"disk={ingest_res.disk_bytes / 1024 / 1024:.1f} MiB",
            flush=True,
        )

        print("  query  …", flush=True)
        query_res = bench_query.run(
            adapter,
            dataset,
            k=k,
            warmup=10,
            warm_pages=warm_pages,
            mlock=mlock,
        )
        for shape, stats in sorted(query_res.by_shape.items()):
            print(
                f"    {shape:<12} n={stats['n']:<4} "
                f"p50={stats['p50_ms']:>8.3f} ms  "
                f"p95={stats['p95_ms']:>8.3f} ms  "
                f"p99={stats['p99_ms']:>8.3f} ms",
                flush=True,
            )

        if skip_footprint:
            footprint_res = None
            print("  footprint: skipped", flush=True)
        else:
            print("  footprint (cold-start probe) …", end=" ", flush=True)
            footprint_res = bench_footprint.run(adapter, store_path, dataset)
            print(
                f"cold_start={footprint_res.cold_start_ms:.1f} ms  "
                f"disk/drawer={footprint_res.disk_bytes_per_drawer:.0f} B",
                flush=True,
            )
    finally:
        adapter.close()

    return {
        "ingest": asdict(ingest_res),
        "query": {
            "adapter": query_res.adapter,
            "n_queries": query_res.n_queries,
            "k": query_res.k,
            "by_shape": query_res.by_shape,
            "rss_steady_mb": query_res.rss_steady_mb,
            "rss_peak_mb": query_res.rss_peak_mb,
        },
        "footprint": asdict(footprint_res) if footprint_res else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scale",
        default="small",
        choices=["small", "medium", "large", "stress", "huge"],
    )
    parser.add_argument(
        "--adapters",
        nargs="+",
        default=["palace", "chroma"],
        choices=list(ADAPTER_BUILDERS.keys()),
        help=(
            "palace=f32 sequential, palace_par=f32 with parallel_query, "
            "palace_i8=int8 quantized, chroma=ChromaDB baseline"
        ),
    )
    parser.add_argument("--ingest-batch", type=int, default=512)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--skip-gate", action="store_true")
    parser.add_argument("--skip-footprint", action="store_true")
    parser.add_argument(
        "--no-warm",
        action="store_true",
        help="Skip the page-warming pass before query timing "
        "(report cold-cache numbers — useful for regression testing)",
    )
    parser.add_argument(
        "--mlock",
        action="store_true",
        help="Also pin warmed pages with POSIX mlock() "
        "(requires adequate ulimit -l; soft-fails otherwise)",
    )
    parser.add_argument(
        "--work-root",
        type=Path,
        default=Path("/tmp/palace_bench"),
        help="Temp directory for store files (will be wiped per adapter).",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("/tmp/palace_bench_cache"),
        help="Cache directory for generated datasets.",
    )
    parser.add_argument("--out", type=Path, default=None, help="JSON report path.")
    args = parser.parse_args()

    args.work_root.mkdir(parents=True, exist_ok=True)

    # Correctness gate first. Small-scale only — we just want to catch
    # adapter bugs before we publish timings from a broken implementation.
    if not args.skip_gate:
        print("== correctness gate (small) ==", flush=True)
        gate_ds = generate("small", seed=1337, gt_k=args.k, cache_dir=args.cache_dir)
        gate_path = args.work_root / "gate"
        if gate_path.exists():
            shutil.rmtree(gate_path)
        gate_path.mkdir()
        gate_adapters: list[StoreAdapter] = [
            _build_adapter(name, gate_path / name) for name in args.adapters
        ]
        try:
            ok, _report = recall_gate.run_gate(gate_ds, gate_adapters)
        finally:
            for a in gate_adapters:
                try:
                    a.close()
                except Exception:
                    pass
        if not ok:
            print("FAIL: correctness gate failed; refusing to publish timings.")
            return 1

    # Main matrix
    results: dict[str, Any] = {
        "scale": args.scale,
        "k": args.k,
        "ingest_batch": args.ingest_batch,
        "system": _system_info(),
        "adapters": {},
    }

    # At 1M rows the ground-truth brute-force matrix is ~800 MB and the
    # gate can't run anyway. Skip ground truth for the huge scale since the
    # correctness gate already ran against small-scale data.
    compute_gt = args.scale != "huge"

    results["warm_pages"] = not args.no_warm
    results["mlock"] = args.mlock

    for adapter_name in args.adapters:
        results["adapters"][adapter_name] = run_once(
            adapter_name,
            args.scale,
            args.work_root,
            ingest_batch=args.ingest_batch,
            k=args.k,
            skip_footprint=args.skip_footprint,
            cache_dir=args.cache_dir,
            compute_ground_truth=compute_gt,
            warm_pages=not args.no_warm,
            mlock=args.mlock,
        )

    # Summary table
    print("\n== summary ==", flush=True)
    print(
        f"{'adapter':<10} {'ingest/s':>12} {'rss_peak':>12} "
        f"{'p50 unf':>10} {'p50 wing':>10} {'p50 w+r':>10} "
        f"{'disk MiB':>10} {'cold ms':>10}"
    )
    for adapter_name, block in results["adapters"].items():
        ing = block["ingest"]
        q = block["query"]["by_shape"]
        fp = block.get("footprint")
        p50_un = q.get("unfiltered", {}).get("p50_ms", float("nan"))
        p50_w = q.get("wing", {}).get("p50_ms", float("nan"))
        p50_wr = q.get("wing_room", {}).get("p50_ms", float("nan"))
        print(
            f"{adapter_name:<10} {ing['drawers_per_sec']:>12.1f} "
            f"{ing['rss_peak_mb']:>10.1f}MB "
            f"{p50_un:>10.3f} {p50_w:>10.3f} {p50_wr:>10.3f} "
            f"{ing['disk_bytes'] / 1024 / 1024:>10.2f} "
            f"{fp['cold_start_ms'] if fp else float('nan'):>10.1f}"
        )

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, indent=2))
        print(f"\nwrote {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
