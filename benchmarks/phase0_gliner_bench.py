"""Phase 0 benchmark: GLiNER batched entity extraction throughput on the A5000.

Measures how many entity spans GLiNER can extract per second in batch mode.
Requires A5000 (or equivalent ≥20 GB GPU) for meaningful numbers.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

SAMPLE_TEXTS = [
    "Alice Smith joined Acme Corp in January 2025 as a senior engineer.",
    "Ben Chen decided to migrate the auth system to OAuth2 after the security audit.",
    "Carol Davis reported the incident to the CTO on March 15th.",
    "The team shipped the v3 release after Alice approved the final PR.",
    "David Lee transferred from the Berlin office to Tokyo in Q1 2026.",
] * 20  # 100 texts total

ENTITY_TYPES = ["person", "organization", "date", "location", "event"]


def run_benchmark(model_name: str, batch_size: int, n_trials: int) -> dict:
    from gliner import GLiNER  # type: ignore[import-not-found]

    model = GLiNER.from_pretrained(model_name)

    # Warmup
    model.predict_entities(SAMPLE_TEXTS[:batch_size], ENTITY_TYPES)

    latencies_ms: list[float] = []
    texts_per_sec_list: list[float] = []

    for _ in range(n_trials):
        batch = SAMPLE_TEXTS[:batch_size]
        t0 = time.monotonic()
        results = model.predict_entities(batch, ENTITY_TYPES)
        elapsed = time.monotonic() - t0
        latencies_ms.append(elapsed * 1000)
        texts_per_sec_list.append(batch_size / elapsed)

    total_spans = sum(len(r) for r in results)

    return {
        "model": model_name,
        "batch_size": batch_size,
        "entity_types": ENTITY_TYPES,
        "trials": n_trials,
        "latency_ms_p50": statistics.median(latencies_ms),
        "texts_per_sec_p50": statistics.median(texts_per_sec_list),
        "spans_last_batch": total_spans,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="urchade/gliner_multi-v2.1")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--trials", type=int, default=10)
    parser.add_argument(
        "--output", type=Path, default=Path("benchmarks/phase0_benchmarks.md"),
    )
    args = parser.parse_args(argv)

    stats = run_benchmark(args.model, args.batch_size, args.trials)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "a") as f:
        f.write("\n## GLiNER entity extraction benchmark\n\n")
        f.write(f"Model: `{stats['model']}`\n\n")
        f.write(f"- Batch size: {stats['batch_size']}\n")
        f.write(f"- Entity types: {', '.join(stats['entity_types'])}\n")
        f.write(f"- Trials: {stats['trials']}\n")
        f.write(f"- **Latency p50:** {stats['latency_ms_p50']:.0f} ms\n")
        f.write(f"- **Throughput p50:** {stats['texts_per_sec_p50']:.1f} texts/s\n")
        f.write(f"- Spans extracted (last batch): {stats['spans_last_batch']}\n")
        f.write("\n")

    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
