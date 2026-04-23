#!/usr/bin/env python3
"""
NLP Provider Quality Benchmark (LongMemEval)
=============================================

Evaluates how NLP providers affect retrieval quality on the LongMemEval
benchmark dataset (https://github.com/xiaowu0162/longmemeval).

Downloads longmemeval_s_cleaned.json (~40 sessions per question, 500 questions)
from HuggingFace and runs retrieval evaluation producing Recall@k and NDCG@k
scores — the same metrics as longmemeval_bench.py.

Modes:
    raw        — baseline: raw text into ChromaDB
    aaak       — AAAK dialect compression before ingestion
    nlp_aaak   — NLP-enhanced AAAK (NLP sentence splitting + NER + compression)
    nlp_hybrid — NLP-enhanced hybrid (NLP entity extraction for keyword boosting)

Usage:
    # Run NLP-enhanced vs baseline comparison (auto-downloads dataset):
    MEMPALACE_NLP_SENTENCES=1 MEMPALACE_NLP_NER=1 \\
      python benchmarks/with-nlp-provider/bench_nlp_providers.py

    # Quick run (10 questions):
    python benchmarks/with-nlp-provider/bench_nlp_providers.py --limit 10

    # Single mode:
    python benchmarks/with-nlp-provider/bench_nlp_providers.py --mode nlp_aaak

    # Use existing dataset file:
    python benchmarks/with-nlp-provider/bench_nlp_providers.py --data data/longmemeval_s_cleaned.json

    # Smoke test (no dataset download, just validates NLP pipeline):
    python benchmarks/with-nlp-provider/bench_nlp_providers.py --self-test
"""

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

DATASET_URL = (
    "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned"
    "/resolve/main/longmemeval_s_cleaned.json"
)
DATASET_CACHE = Path(__file__).parent / "longmemeval_s_cleaned.json"


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


def download_dataset(dest=None):
    """Download longmemeval_s_cleaned.json from HuggingFace if not cached."""
    dest = Path(dest) if dest else DATASET_CACHE
    if dest.exists():
        print(f"  Dataset cached: {dest}")
        return str(dest)

    print("  Downloading LongMemEval dataset...")
    print(f"  URL: {DATASET_URL}")
    print(f"  Destination: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(DATASET_URL, str(dest))
    size_mb = dest.stat().st_size / (1024 * 1024)
    print(f"  Downloaded: {size_mb:.1f} MB")
    return str(dest)


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
    """Smoke test: validate NLP pipeline without downloading dataset."""
    from mempalace.dialect import Dialect
    from mempalace.entity_detector import extract_candidates
    from mempalace.general_extractor import extract_memories

    texts = [
        "We decided to use PostgreSQL because it handles JSON natively. "
        "The migration from MySQL took three weeks but it was worth it.",
        "Alice works at Anthropic in San Francisco. She builds AI systems. "
        "Her colleague Bob moved from Google last year.",
        "Dr. Smith went to Washington. He met with officials. The meeting lasted 2 hours.",
    ]
    d = Dialect()

    print("Smoke test — validating NLP pipeline components:\n")
    for text in texts:
        sents = d._split_sentences(text)
        entities = extract_candidates(text)
        memories = extract_memories(text, min_confidence=0.1)
        compressed = d.compress(text)
        ratio = d.compression_stats(text, compressed)["size_ratio"]
        print(f"  Text:        {text[:70]}...")
        print(f"  Sentences:   {len(sents)}")
        print(f"  Entities:    {list(entities.keys())}")
        print(f"  Memories:    {[m['memory_type'] for m in memories] if memories else '(none)'}")
        print(f"  Compression: {ratio:.1f}x")
        print()

    print("Smoke test passed. For full benchmark run without --self-test.")


def main():
    parser = argparse.ArgumentParser(
        description="NLP Provider Quality Benchmark — runs LongMemEval retrieval "
        "evaluation with and without NLP providers to measure impact on "
        "Recall@k and NDCG@k."
    )
    parser.add_argument(
        "--data",
        default=None,
        help="Path to longmemeval_s_cleaned.json. Auto-downloaded if not provided.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit to N questions (0 = all 500). Use --limit 10 for quick runs.",
    )
    parser.add_argument(
        "--granularity",
        choices=["session", "turn"],
        default="session",
    )
    parser.add_argument(
        "--mode",
        choices=["compare", "raw", "aaak", "nlp_aaak", "nlp_hybrid"],
        default="compare",
        help="'compare' runs raw + nlp_aaak + nlp_hybrid and shows all scores. "
        "Other values run a single mode.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Smoke test: validate NLP pipeline without downloading dataset.",
    )
    args = parser.parse_args()

    print_env()

    if args.self_test:
        run_self_test()
        return

    # Download or locate dataset
    data_file = args.data
    if not data_file:
        data_file = download_dataset()

    # Verify dataset
    with open(data_file, encoding="utf-8") as f:
        data = json.load(f)
    print(f"Dataset: {data_file}")
    print(f"Questions: {len(data)}")
    if args.limit:
        print(f"Limit: {args.limit}")
    print()

    # Import run_benchmark from longmemeval_bench
    from longmemeval_bench import run_benchmark

    if args.mode == "compare":
        modes = ["raw", "nlp_aaak", "nlp_hybrid"]
    else:
        modes = [args.mode]

    for mode in modes:
        print()
        print("=" * 60)
        print(f"  MODE: {mode}")
        print("=" * 60)
        run_benchmark(
            data_file,
            granularity=args.granularity,
            limit=args.limit,
            mode=mode,
        )

    if len(modes) > 1:
        print()
        print("=" * 60)
        print("  Compare Recall@k and NDCG@k scores above.")
        print("  Higher = better retrieval quality.")
        print("  NLP modes should show improvement over raw baseline.")
        print("=" * 60)


if __name__ == "__main__":
    main()
