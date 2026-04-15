"""Walker retrieval-recall benchmark runner.

Phase 0: baseline mode runs the existing mempalace hybrid search against
LoCoMo's multi-hop-like questions (categories 2 Temporal and 3 Temporal-
inference per benchmarks/locomo_bench.py:83). Establishes the baseline
for comparison against mempalace_walk in Phase 2.

Usage:
    python benchmarks/walk_bench.py /path/to/locomo10.json --mode baseline
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


# LoCoMo category IDs (from benchmarks/locomo_bench.py:83)
# 1 Single-hop | 2 Temporal | 3 Temporal-inference | 4 Open-domain | 5 Adversarial
MULTIHOP_LIKE_CATEGORIES = {2, 3}


@dataclass
class WalkBenchResult:
    question_id: str
    question: str
    category: int
    retrieved_ids: list[str]
    gold_evidence: list[Any]
    hit_at_1: bool
    hit_at_5: bool
    hit_at_10: bool
    latency_ms: float
    mode: str


def load_locomo_multihop_like(path: Path) -> list[dict]:
    """Load LoCoMo questions filtered to multi-hop-like categories.

    LoCoMo's `category` field is an integer (not a string). We synthesize
    question_id as f"conv{conv_idx}_qa{qa_idx}" because LoCoMo QAs lack a
    question_id field.
    """
    with open(path) as f:
        data = json.load(f)

    questions: list[dict] = []
    for conv_idx, conv in enumerate(data):
        qa_list = conv.get("qa", [])
        for qa_idx, qa in enumerate(qa_list):
            category = qa.get("category")
            if category not in MULTIHOP_LIKE_CATEGORIES:
                continue
            questions.append(
                {
                    "question_id": f"conv{conv_idx}_qa{qa_idx}",
                    "question": qa["question"],
                    "category": category,
                    "gold_evidence": qa.get("evidence", []),
                    "answer": qa.get("answer", qa.get("adversarial_answer", "")),
                }
            )
    return questions


def run_baseline(questions: list[dict], palace_path: Path | None) -> list[WalkBenchResult]:
    """Run the existing hybrid search against each question."""
    from mempalace import searcher

    results: list[WalkBenchResult] = []
    for q in questions:
        t0 = time.monotonic()
        if palace_path is None:
            hits = {"results": []}
        else:
            hits = searcher.search_memories(
                query=q["question"],
                palace_path=str(palace_path),
                n_results=10,
            )
        elapsed_ms = (time.monotonic() - t0) * 1000

        # search_memories returns no "id"/"drawer_id" key.
        # Actual keys: text, wing, room, source_file, similarity, ...
        # Hit metric = answer-text containment in retrieved chunks.
        retrieved_texts = [h.get("text", "") for h in hits.get("results", [])]
        gold_answer = str(q["answer"]).lower().strip()

        def answer_in(text: str) -> bool:
            return bool(gold_answer) and gold_answer in text.lower()

        hit_at_1 = bool(retrieved_texts[:1]) and answer_in(retrieved_texts[0])
        hit_at_5 = any(answer_in(t) for t in retrieved_texts[:5])
        hit_at_10 = any(answer_in(t) for t in retrieved_texts[:10])

        retrieved_ids = [h.get("source_file", "") for h in hits.get("results", [])]

        results.append(
            WalkBenchResult(
                question_id=q["question_id"],
                question=q["question"],
                category=q["category"],
                retrieved_ids=retrieved_ids,
                gold_evidence=list(q["gold_evidence"]),
                hit_at_1=hit_at_1,
                hit_at_5=hit_at_5,
                hit_at_10=hit_at_10,
                latency_ms=elapsed_ms,
                mode="baseline",
            )
        )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("locomo_path", type=Path)
    parser.add_argument("--mode", choices=["baseline", "walker"], default="baseline")
    parser.add_argument("--palace", type=Path, default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path; defaults to benchmarks/results_walk_locomo_<mode>.jsonl",
    )
    args = parser.parse_args(argv)

    questions = load_locomo_multihop_like(args.locomo_path)
    if not questions:
        print(
            f"No questions in LoCoMo categories {MULTIHOP_LIKE_CATEGORIES} found "
            f"in {args.locomo_path}",
            file=sys.stderr,
        )
        return 1

    if args.mode == "walker":
        print("walker mode lands in Phase 2", file=sys.stderr)
        return 2

    results = run_baseline(questions, args.palace)

    output_path = args.output or Path(
        f"benchmarks/results_walk_locomo_{args.mode}.jsonl"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        for r in results:
            f.write(json.dumps(asdict(r)) + "\n")

    n = len(results)
    hit_1 = sum(r.hit_at_1 for r in results) / n
    hit_5 = sum(r.hit_at_5 for r in results) / n
    hit_10 = sum(r.hit_at_10 for r in results) / n
    p50_ms = statistics.median(r.latency_ms for r in results)

    print(f"Mode:       {args.mode}")
    print(f"Questions:  {n}")
    print(f"Categories: {MULTIHOP_LIKE_CATEGORIES}")
    print(f"Hit@1:      {hit_1:.1%}")
    print(f"Hit@5:      {hit_5:.1%}")
    print(f"Hit@10:     {hit_10:.1%}")
    print(f"p50:        {p50_ms:.0f}ms")
    print(f"Results:    {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
