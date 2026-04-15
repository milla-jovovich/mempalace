"""Phase 0 benchmark: measured vLLM Qwen 2.5-7B AWQ throughput on the A5000.

Uses vLLM's RequestMetrics API (arrival_time, first_token_ts, last_token_ts)
to separate prefill from generation latency. No heuristic splits.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path


REALISTIC_PROMPT = (
    "You are a knowledge graph walker. Given a query, a subgraph of "
    "candidate entities and their typed edges, and a handful of drawer "
    "previews, select the entity chain that best answers the query.\n\n"
    "Query: What did Ben decide about the auth approach Alice proposed?\n\n"
    "Candidate entities (top 20 by PPR):\n"
    + "\n".join(f"  ent_{i:03d}  (type=person|topic, name=Entity_{i})" for i in range(20))
    + "\n\nEdges:\n"
    + "\n".join(
        f"  ent_{i:03d} --predicate_{i}--> ent_{(i+1) % 20:03d}  "
        "(valid 2026-01-01, conf 0.85)"
        for i in range(30)
    )
    + "\n\nDrawer previews:\n"
    + "\n".join(
        f"  drw_{i:03d}: " + "lorem ipsum dolor sit amet consectetur " * 15
        for i in range(10)
    )
    + '\n\nTask: Output the chain as JSON: {"chain": [...]}\n'
)


def run_benchmark(model_id: str, n_trials: int) -> dict:
    from vllm import LLM, SamplingParams  # type: ignore[import-not-found]

    llm = LLM(model=model_id, dtype="auto", gpu_memory_utilization=0.6)
    sampling = SamplingParams(temperature=0.0, max_tokens=80)

    # Warmup trial (not counted)
    llm.generate([REALISTIC_PROMPT], sampling)

    prefill_ms_list: list[float] = []
    gen_ms_list: list[float] = []
    total_ms_list: list[float] = []
    prompt_tokens = 0
    gen_tokens = 0

    for _ in range(n_trials):
        outputs = llm.generate([REALISTIC_PROMPT], sampling)
        out = outputs[0]
        prompt_tokens = len(out.prompt_token_ids)
        gen_tokens = len(out.outputs[0].token_ids)

        metrics = getattr(out, "metrics", None)
        if metrics is None:
            print(
                "vLLM output has no metrics attribute — cannot separate "
                "prefill from generation latency. Upgrade vLLM or re-measure.",
                file=sys.stderr,
            )
            sys.exit(2)

        arrival = metrics.arrival_time
        first_token = metrics.first_token_ts    # correct field name (not first_token_time)
        finished = metrics.last_token_ts        # correct field name (not finished_time)
        if arrival is None or first_token is None or finished is None:
            print(
                "vLLM metrics incomplete (arrival/first_token/finished). "
                "Cannot compute prefill/gen split.",
                file=sys.stderr,
            )
            sys.exit(2)

        prefill_ms = (first_token - arrival) * 1000
        gen_ms = (finished - first_token) * 1000
        total_ms = (finished - arrival) * 1000
        prefill_ms_list.append(prefill_ms)
        gen_ms_list.append(gen_ms)
        total_ms_list.append(total_ms)

    return {
        "model": model_id,
        "prompt_tokens": prompt_tokens,
        "gen_tokens": gen_tokens,
        "trials": n_trials,
        "prefill_ms_p50": statistics.median(prefill_ms_list),
        "gen_ms_p50": statistics.median(gen_ms_list),
        "total_ms_p50": statistics.median(total_ms_list),
        "total_ms_p95": sorted(total_ms_list)[int(0.95 * n_trials)] if n_trials >= 20 else None,
        "prefill_tok_per_sec": prompt_tokens / (statistics.median(prefill_ms_list) / 1000),
        "gen_tok_per_sec": gen_tokens / (statistics.median(gen_ms_list) / 1000),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct-AWQ")
    parser.add_argument("--trials", type=int, default=10)
    parser.add_argument(
        "--output", type=Path, default=Path("benchmarks/phase0_benchmarks.md"),
    )
    args = parser.parse_args(argv)

    stats = run_benchmark(args.model, args.trials)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "a") as f:
        f.write("\n## vLLM walker benchmark\n\n")
        f.write(f"Model: `{stats['model']}`\n\n")
        f.write(f"- Prompt tokens: {stats['prompt_tokens']}\n")
        f.write(f"- Generated tokens: {stats['gen_tokens']}\n")
        f.write(f"- Trials: {stats['trials']}\n")
        f.write(f"- **Prefill p50:** {stats['prefill_ms_p50']:.0f} ms "
                f"({stats['prefill_tok_per_sec']:.0f} tok/s)\n")
        f.write(f"- **Generation p50:** {stats['gen_ms_p50']:.0f} ms "
                f"({stats['gen_tok_per_sec']:.0f} tok/s)\n")
        f.write(f"- **Total p50:** {stats['total_ms_p50']:.0f} ms\n")
        if stats["total_ms_p95"] is not None:
            f.write(f"- Total p95: {stats['total_ms_p95']:.0f} ms\n")
        f.write("\n")

    print(json.dumps(stats, indent=2))

    if stats["total_ms_p50"] > 1500:
        print(
            f"\n⚠️  total p50 {stats['total_ms_p50']:.0f}ms exceeds 1500ms budget.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
