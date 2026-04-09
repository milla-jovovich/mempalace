#!/usr/bin/env python3
"""
NLP Provider Quality Benchmark (LongMemEval)
=============================================

Evaluates how NLP providers affect retrieval quality on the LongMemEval dataset.
Uses the same evaluation framework as longmemeval_bench.py to produce directly
comparable Recall@k and NDCG@k scores.

NLP-enhanced modes (added to longmemeval_bench.py):
    nlp_aaak    — AAAK dialect compression with NLP sentence splitting + NER
    nlp_hybrid  — Hybrid retrieval with NLP entity extraction for keyword boosting

This script is a convenience wrapper that:
1. Runs baseline mode (raw or aaak) without NLP flags
2. Runs NLP-enhanced mode (nlp_aaak or nlp_hybrid) with current NLP flags
3. Prints a comparison table

Usage:
    # Full comparison (requires longmemeval dataset):
    MEMPALACE_NLP_SENTENCES=1 MEMPALACE_NLP_NER=1 \\
      python benchmarks/with-nlp-provider/bench_nlp_providers.py data/longmemeval_s_cleaned.json

    # Quick comparison (5 questions):
    MEMPALACE_NLP_SENTENCES=1 MEMPALACE_NLP_NER=1 \\
      python benchmarks/with-nlp-provider/bench_nlp_providers.py data/longmemeval_s_cleaned.json --limit 5

    # Run directly via longmemeval_bench.py:
    python benchmarks/longmemeval_bench.py data/longmemeval_s_cleaned.json --mode nlp_aaak
    python benchmarks/longmemeval_bench.py data/longmemeval_s_cleaned.json --mode nlp_hybrid

    # Run without dataset (smoke test):
    python benchmarks/with-nlp-provider/bench_nlp_providers.py --self-test
"""

import argparse
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))


def _has_package(name):
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def _nlp_status():
    flags = {}
    for key in ["SENTENCES", "NEGATION", "NER", "CLASSIFY", "TRIPLES"]:
        flags[key] = os.environ.get(f"MEMPALACE_NLP_{key}", "0") == "1"
    return flags


def print_env():
    """Print NLP environment status."""
    flags = _nlp_status()
    any_nlp = any(flags.values())

    print("MemPalace NLP Quality Benchmark (LongMemEval)")
    print("=" * 60)
    print(f"\nNLP mode: {'ENHANCED' if any_nlp else 'BASELINE (regex)'}")
    print("\nNLP feature flags:")
    for flag, enabled in flags.items():
        print(f"  MEMPALACE_NLP_{flag}: {'ON' if enabled else 'off'}")
    print("\nAvailable NLP packages:")
    for pkg in ["pysbd", "spacy", "gliner", "wtpsplit"]:
        status = "installed" if _has_package(pkg) else "not installed"
        print(f"  {pkg}: {status}")
    print()


def run_self_test():
    """Run self-contained quality checks without the LongMemEval dataset."""
    from mempalace.dialect import Dialect
    from mempalace.entity_detector import extract_candidates
    from mempalace.general_extractor import extract_memories

    texts = [
        "We decided to use PostgreSQL because it handles JSON natively. "
        "The migration from MySQL took three weeks but it was worth it.",
        "Alice works at Anthropic in San Francisco. She builds AI systems. "
        "Her colleague Bob moved from Google last year.",
        "I'm so proud of what we've built together. This has been an amazing journey.",
        "Dr. Smith went to Washington. He met with officials. The meeting lasted 2 hours.",
    ]

    d = Dialect()

    print("Sentence Splitting:")
    for text in texts:
        sents = d._split_sentences(text)
        print(f"  Input:  {text[:60]}...")
        print(f"  Splits: {len(sents)} sentences")
    print()

    print("Entity Extraction:")
    for text in texts:
        candidates = extract_candidates(text)
        print(f"  Input:    {text[:60]}...")
        print(f"  Entities: {list(candidates.keys())}")
    print()

    print("Memory Classification:")
    for text in texts:
        memories = extract_memories(text, min_confidence=0.1)
        types = [m["memory_type"] for m in memories] if memories else ["(none)"]
        print(f"  Input: {text[:60]}...")
        print(f"  Types: {types}")
    print()

    print("Compression Fidelity:")
    for text in texts:
        compressed = d.compress(text)
        stats = d.compression_stats(text, compressed)
        print(f"  Input:  {text[:60]}...")
        print(f"  Ratio:  {stats['size_ratio']:.2f}x")
    print()

    print("Self-test complete.")
    print("For full LongMemEval benchmark, provide a dataset file:")
    print(
        "  python benchmarks/with-nlp-provider/bench_nlp_providers.py data/longmemeval_s_cleaned.json"
    )


def main():
    parser = argparse.ArgumentParser(
        description="NLP Provider Quality Benchmark — LongMemEval-based evaluation. "
        "Compares NLP-enhanced retrieval modes against baselines."
    )
    parser.add_argument("data_file", nargs="?", help="Path to longmemeval_s_cleaned.json")
    parser.add_argument("--limit", type=int, default=0, help="Limit to N questions (0 = all)")
    parser.add_argument(
        "--granularity",
        choices=["session", "turn"],
        default="session",
    )
    parser.add_argument(
        "--mode",
        choices=["compare", "nlp_aaak", "nlp_hybrid"],
        default="compare",
        help="'compare' runs baseline+NLP and prints comparison (default). "
        "'nlp_aaak' or 'nlp_hybrid' runs a single NLP mode.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run self-contained quality checks without LongMemEval dataset",
    )
    args = parser.parse_args()

    print_env()

    if args.self_test or not args.data_file:
        if not args.data_file:
            print("No data file provided — running self-test mode.\n")
        run_self_test()
        return

    # Import run_benchmark from longmemeval_bench
    from longmemeval_bench import run_benchmark

    if args.mode == "compare":
        # Run baseline (raw) then NLP-enhanced (nlp_aaak)
        print("=" * 60)
        print("  BASELINE: raw mode")
        print("=" * 60)
        run_benchmark(
            args.data_file,
            granularity=args.granularity,
            limit=args.limit,
            mode="raw",
        )

        print("\n")
        print("=" * 60)
        print("  NLP-ENHANCED: nlp_aaak mode")
        print("=" * 60)
        run_benchmark(
            args.data_file,
            granularity=args.granularity,
            limit=args.limit,
            mode="nlp_aaak",
        )

        print("\n")
        print("=" * 60)
        print("  NLP-ENHANCED: nlp_hybrid mode")
        print("=" * 60)
        run_benchmark(
            args.data_file,
            granularity=args.granularity,
            limit=args.limit,
            mode="nlp_hybrid",
        )

        print("\n" + "=" * 60)
        print("  Compare scores above to evaluate NLP provider impact.")
        print("  Higher Recall@k and NDCG@k = better retrieval quality.")
        print("=" * 60)
    else:
        # Run single NLP mode
        run_benchmark(
            args.data_file,
            granularity=args.granularity,
            limit=args.limit,
            mode=args.mode,
        )


if __name__ == "__main__":
    main()
