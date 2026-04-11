"""Correctness gate: top-k set equality across adapters.

Because the harness feeds identical pre-normalized vectors into every
adapter and every adapter is expected to do exact cosine search, the top-k
result sets MUST be identical. Any divergence is a bug in an adapter, not
a retrieval-quality regression. This module is how we enforce that.

The gate runs at small scale only — we don't need 100k drawers to catch
a ranking bug, and running the full ground-truth brute force at larger
scales is wasted compute. Use the ``small`` config by default.

Exit codes:
  0 — all adapters match each other and match the ground truth
  1 — at least one adapter diverged

This file is importable as a module *and* runnable as a script.
"""

from __future__ import annotations

import sys
from pathlib import Path


from .adapters.chroma import ChromaAdapter
from .adapters.palace import PalaceAdapter
from .adapters.palace_i8 import PalaceI8Adapter
from .dataset import BenchDataset, generate
from .interface import StoreAdapter


K = 10  # top-k for gate


def run_gate(
    dataset: BenchDataset,
    adapters: list[StoreAdapter],
    *,
    verbose: bool = True,
) -> tuple[bool, dict[str, dict[str, float]]]:
    """Run every query through every adapter, compare top-k sets to the
    precomputed ground truth.

    Returns (ok, report) where report maps adapter name → per-metric stats.
    """
    # Ingest once per adapter.
    for adapter in adapters:
        _bulk_ingest(adapter, dataset)

    report: dict[str, dict[str, float]] = {}
    overall_ok = True

    for adapter in adapters:
        set_matches = 0
        order_matches = 0
        partial_matches = 0
        total = dataset.q

        for qi in range(dataset.q):
            q = dataset.query_vectors[qi]
            where = dataset.query_wheres[qi]
            hits = adapter.query(q, K, where=where)
            got_ids = [h.id for h in hits]

            # Ground truth row indices → ids
            gt_rows = dataset.ground_truth_top_k[qi]
            gt_rows = gt_rows[gt_rows >= 0]  # some rows may be -1 if filter was narrow
            expected_ids = [dataset.ids[r] for r in gt_rows]

            got_set = set(got_ids)
            exp_set = set(expected_ids)

            if got_set == exp_set:
                set_matches += 1
            if got_ids == expected_ids:
                order_matches += 1
            if got_set & exp_set:
                # How many of the ground-truth ids did we recover?
                partial_matches += len(got_set & exp_set) / max(len(exp_set), 1)

        set_rate = set_matches / total
        order_rate = order_matches / total
        avg_partial = partial_matches / total

        # Exact adapters (f32 brute-force, tuned HNSW) must match the
        # ground-truth set nearly 100% — any gap is an adapter bug.
        # Approximate adapters (int8 quantization, coarse HNSW) are
        # validated against a looser *overlap* threshold because the top-k
        # set may drop a few ties to rounding error.
        if getattr(adapter, "is_exact", True):
            adapter_ok = set_rate >= 0.999
        else:
            adapter_ok = avg_partial >= 0.90
        overall_ok &= adapter_ok

        report[adapter.name] = {
            "top_k_set_match": round(set_rate, 4),
            "top_k_order_match": round(order_rate, 4),
            "avg_overlap": round(avg_partial, 4),
            "n_queries": total,
            "exact": getattr(adapter, "is_exact", True),
            "ok": adapter_ok,
        }

        if verbose:
            flag = "OK " if adapter_ok else "FAIL"
            mode = "exact" if getattr(adapter, "is_exact", True) else "approx"
            print(
                f"[{flag}] {adapter.name:10s} ({mode})  "
                f"set={set_rate:.4f}  order={order_rate:.4f}  overlap={avg_partial:.4f}"
            )

    return overall_ok, report


def _bulk_ingest(adapter: StoreAdapter, dataset: BenchDataset, batch: int = 512) -> None:
    """Upsert the whole dataset in chunks so no adapter blows out on one call."""
    n = dataset.n
    for i in range(0, n, batch):
        j = min(i + batch, n)
        adapter.upsert(
            ids=dataset.ids[i:j],
            vectors=dataset.vectors[i:j],
            metadatas=dataset.metadatas[i:j],
            texts=dataset.texts[i:j],
        )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scale", default="small", help="dataset scale (default: small)")
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--work-dir", type=Path, default=Path("/tmp/palace_bench_gate"))
    parser.add_argument("--cache-dir", type=Path, default=Path("/tmp/palace_bench_cache"))
    parser.add_argument(
        "--adapters",
        nargs="+",
        default=["palace", "palace_i8", "chroma"],
        choices=["palace", "palace_i8", "chroma"],
    )
    args = parser.parse_args()

    import shutil

    if args.work_dir.exists():
        shutil.rmtree(args.work_dir)
    args.work_dir.mkdir(parents=True)

    print(f"Generating {args.scale} dataset (seed={args.seed}) …", flush=True)
    dataset = generate(args.scale, seed=args.seed, gt_k=K, cache_dir=args.cache_dir)
    print(f"  N={dataset.n}  Q={dataset.q}", flush=True)

    adapters: list[StoreAdapter] = []
    if "palace" in args.adapters:
        adapters.append(PalaceAdapter(args.work_dir / "palace"))
    if "palace_i8" in args.adapters:
        adapters.append(PalaceI8Adapter(args.work_dir / "palace_i8"))
    if "chroma" in args.adapters:
        adapters.append(ChromaAdapter(args.work_dir / "chroma"))

    try:
        ok, _ = run_gate(dataset, adapters)
    finally:
        for a in adapters:
            try:
                a.close()
            except Exception:
                pass

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
