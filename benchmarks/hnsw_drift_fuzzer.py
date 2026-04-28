#!/usr/bin/env python3
"""hnsw_drift_fuzzer.py — measure the chromadb HNSW drift window.

Adds a drawer with a known sentinel, then loops a query for that
sentinel until the drawer surfaces. Records the time-to-first-hit and
classifies any errors that fired during the loop. Repeats N times and
emits a JSON report with timing histograms and error classifications.

The drift window we're measuring is the gap between an `add()` call and
when the new document is consistently visible in HNSW search. That gap
is small in normal operation but it widens to "Error finding id"
territory when the on-disk HNSW segment drifts vs chroma.sqlite3 (see
chroma-core/chroma#2594, mempalace #823).

Usage:
    python benchmarks/hnsw_drift_fuzzer.py [--iterations N] [--max-poll-ms MS]
                                           [--poll-interval-ms MS]
                                           [--out report.json]
                                           [--palace PATH]

If --palace is omitted, a fresh tmpdir-backed palace is used (which is
the right default for this tool — we want to characterize chromadb's
own behavior, not a particular palace's accumulated state).

Single-threaded for v1. Future passes can layer on:
- closet collection queries during drift (currently we exercise
  mempalace_drawers only)
- concurrent adds + searches (threading) to surface race conditions
- delete + search (the inverse race)
- large batch add (50+) then immediate search
"""

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
import uuid
from typing import Any


def add_one_drawer(collection, sentinel: str) -> str:
    """Add a drawer whose document body contains ``sentinel``.

    Returns the drawer id used.
    """
    drawer_id = f"fuzz_{uuid.uuid4().hex[:12]}"
    doc = (
        f"This is a drift-fuzzer drawer. Sentinel: {sentinel}. "
        f"It exists only to be searched. Some filler text follows so the "
        f"embedding has more than the sentinel to chew on, otherwise the "
        f"index can quirk on near-empty documents."
    )
    collection.add(
        documents=[doc],
        metadatas=[{"wing": "fuzzer", "room": "drift", "added_by": "fuzzer", "sentinel": sentinel}],
        ids=[drawer_id],
    )
    return drawer_id


def search_for_sentinel(collection, sentinel: str, n_results: int = 5) -> dict:
    """Query for the sentinel and report (found, error, raw_distance).

    "found" is True when the sentinel appears in any returned document.
    "error" is the exception class+message if the query raised; None
    otherwise. "raw_distance" is the closest distance seen, or None.
    """
    try:
        r = collection.query(
            query_texts=[f"sentinel {sentinel}"],
            n_results=n_results,
            include=["documents", "distances"],
        )
    except Exception as e:
        cls = type(e).__name__
        return {"found": False, "error": f"{cls}: {e}", "raw_distance": None}

    docs = (r.get("documents") or [[]])[0]
    dists = (r.get("distances") or [[]])[0]
    found = any(sentinel in (d or "") for d in docs)
    raw = min(dists) if dists else None
    return {"found": found, "error": None, "raw_distance": raw}


def measure_one_drift_window(
    collection, max_poll_ms: float, poll_interval_ms: float
) -> dict:
    """One iteration: add a drawer with a fresh sentinel, then poll
    search until the sentinel surfaces or the timeout fires.
    """
    sentinel = f"S{uuid.uuid4().hex[:8]}"
    t_add_start = time.perf_counter()
    drawer_id = add_one_drawer(collection, sentinel)
    t_add_end = time.perf_counter()

    found_at_ms: float | None = None
    errors: list[dict] = []
    polls = 0
    deadline = t_add_end + (max_poll_ms / 1000.0)

    while True:
        polls += 1
        result = search_for_sentinel(collection, sentinel)
        elapsed_ms = (time.perf_counter() - t_add_end) * 1000.0
        if result["error"]:
            errors.append({"at_ms": elapsed_ms, "error": result["error"]})
        if result["found"]:
            found_at_ms = elapsed_ms
            break
        if time.perf_counter() >= deadline:
            break
        time.sleep(poll_interval_ms / 1000.0)

    return {
        "drawer_id": drawer_id,
        "sentinel": sentinel,
        "add_duration_ms": (t_add_end - t_add_start) * 1000.0,
        "drift_window_ms": found_at_ms,        # None means never visible within timeout
        "polls": polls,
        "errors": errors,
        "outcome": "found" if found_at_ms is not None else "timeout",
    }


def summarize(results: list[dict]) -> dict:
    """Aggregate per-iteration results into the report's summary block."""
    found = [r for r in results if r["outcome"] == "found"]
    timeouts = [r for r in results if r["outcome"] == "timeout"]
    drift_ms = [r["drift_window_ms"] for r in found if r["drift_window_ms"] is not None]

    # Error classification — group by the exception class and message
    # prefix so "Error finding id 12 in segment ..." and "Error finding
    # id 99 in segment ..." count as the same kind.
    error_classes: dict[str, int] = {}
    for r in results:
        for e in r["errors"]:
            msg = e["error"]
            head = msg.split(" in ")[0][:80]
            error_classes[head] = error_classes.get(head, 0) + 1

    summary: dict[str, Any] = {
        "iterations": len(results),
        "found": len(found),
        "timed_out": len(timeouts),
        "error_total": sum(len(r["errors"]) for r in results),
        "error_classes": error_classes,
    }
    if drift_ms:
        summary["drift_ms_min"] = min(drift_ms)
        summary["drift_ms_max"] = max(drift_ms)
        summary["drift_ms_mean"] = statistics.mean(drift_ms)
        summary["drift_ms_median"] = statistics.median(drift_ms)
        if len(drift_ms) >= 2:
            summary["drift_ms_stdev"] = statistics.stdev(drift_ms)
    return summary


def open_collection(palace_path: str):
    """Open or create the drawer collection at ``palace_path``."""
    from mempalace.palace import get_collection

    return get_collection(palace_path, create=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--iterations", type=int, default=20,
                   help="how many add-then-search rounds to run (default 20)")
    p.add_argument("--max-poll-ms", type=float, default=2000.0,
                   help="give up on a single round after this many ms (default 2000)")
    p.add_argument("--poll-interval-ms", type=float, default=10.0,
                   help="sleep between polls within a round (default 10)")
    p.add_argument("--palace", default=None,
                   help="palace path; default = fresh tmpdir per run")
    p.add_argument("--out", default=None,
                   help="path to write JSON report; default = stdout")
    args = p.parse_args(argv)

    using_tmp = args.palace is None
    palace_path = args.palace or tempfile.mkdtemp(prefix="hnsw_drift_fuzzer_")
    try:
        collection = open_collection(palace_path)

        results: list[dict] = []
        for i in range(args.iterations):
            r = measure_one_drift_window(collection, args.max_poll_ms, args.poll_interval_ms)
            results.append(r)
            sys.stderr.write(
                f"[{i+1}/{args.iterations}] {r['outcome']:>7s}  "
                f"drift={r['drift_window_ms']!s:>8s}ms  polls={r['polls']:>3d}  "
                f"errors={len(r['errors'])}\n"
            )

        report = {
            "palace_path": palace_path,
            "fresh_tmpdir": using_tmp,
            "iterations": args.iterations,
            "max_poll_ms": args.max_poll_ms,
            "poll_interval_ms": args.poll_interval_ms,
            "summary": summarize(results),
            "results": results,
        }
        out = json.dumps(report, indent=2, default=str)
        if args.out:
            with open(args.out, "w") as f:
                f.write(out)
            sys.stderr.write(f"\nWrote report to {args.out}\n")
        else:
            print(out)
        return 0
    finally:
        if using_tmp and os.path.isdir(palace_path):
            import shutil
            try:
                shutil.rmtree(palace_path)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
