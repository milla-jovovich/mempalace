#!/usr/bin/env python3
"""
NLP Provider Benchmark
======================

Benchmarks NLP-enhanced mempalace operations against the legacy regex baseline.
Uses actual mempalace APIs (dialect, entity_detector, general_extractor, miner)
rather than reimplementing anything.

Usage:
    # Baseline (no NLP packages):
    python benchmarks/with-nlp-provider/bench_nlp_providers.py --iterations 20

    # With NLP (set env vars + install packages first):
    MEMPALACE_NLP_SENTENCES=1 MEMPALACE_NLP_NER=1 MEMPALACE_NLP_CLASSIFY=1 \
      python benchmarks/with-nlp-provider/bench_nlp_providers.py --iterations 20
"""

import argparse
import os
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

TEXTS = [
    "We decided to use PostgreSQL because it handles JSON natively. "
    "The migration from MySQL took three weeks but it was worth it. "
    "Python's SQLAlchemy ORM made the transition much smoother.",
    "Bug: the connection pool was exhausted under high load. "
    "Root cause: each request opened a new connection instead of reusing. "
    "The fix was to configure max_pool_size=20 in the database settings.",
    "Alice works at Anthropic in San Francisco. She builds AI systems. "
    "Her colleague Bob moved from Google last year. They collaborate on safety research.",
    "I don't like the new API. However, it's faster than the old one. Let's keep it for now.",
    "Finally got the tests passing after three days of debugging! "
    "The key insight was that the mock wasn't resetting between test runs.",
    "Dr. Smith went to Washington. He met with officials. The meeting lasted 2 hours.",
    "I'm so proud of what we've built together. This has been an amazing journey.",
    "I always use black for formatting Python code. Never mix tabs and spaces.",
    "Microsoft acquired GitHub for $7.5 billion in 2018. "
    "Satya Nadella called it a strategic investment in developer tools.",
    "Barack Obama was born in Hawaii and served as the 44th President of the United States.",
]


def _has_package(name):
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def _nlp_status():
    """Report which NLP features are active."""
    flags = {}
    for key in ["SENTENCES", "NEGATION", "NER", "CLASSIFY", "TRIPLES"]:
        flags[key] = os.environ.get(f"MEMPALACE_NLP_{key}", "0") == "1"
    return flags


# ---------------------------------------------------------------------------
# Benchmark: Sentence splitting via dialect._split_sentences()
# ---------------------------------------------------------------------------


def bench_sentence_splitting(iterations):
    """Benchmark dialect's sentence splitting (uses NLP when available)."""
    from mempalace.dialect import Dialect

    d = Dialect()

    # Warmup
    d._split_sentences(TEXTS[0])

    start = time.perf_counter()
    total_sentences = 0
    for _ in range(iterations):
        for text in TEXTS:
            sents = d._split_sentences(text)
            total_sentences += len(sents)
    elapsed = time.perf_counter() - start

    sample = d._split_sentences(TEXTS[0])
    return {
        "time_s": elapsed,
        "ops_per_s": (iterations * len(TEXTS)) / elapsed,
        "total_sentences": total_sentences,
        "sample_count": len(sample),
        "sample": [s[:60] for s in sample[:3]],
    }


# ---------------------------------------------------------------------------
# Benchmark: Entity extraction via entity_detector.extract_candidates()
# ---------------------------------------------------------------------------


def bench_entity_extraction(iterations):
    """Benchmark entity detection (uses NLP NER when available)."""
    from mempalace.entity_detector import extract_candidates

    # Warmup
    extract_candidates(TEXTS[0])

    start = time.perf_counter()
    total_entities = 0
    for _ in range(iterations):
        for text in TEXTS:
            candidates = extract_candidates(text)
            total_entities += len(candidates)
    elapsed = time.perf_counter() - start

    sample = extract_candidates(TEXTS[0])
    return {
        "time_s": elapsed,
        "ops_per_s": (iterations * len(TEXTS)) / elapsed,
        "total_entities": total_entities,
        "sample_entities": list(sample.keys())[:5],
    }


# ---------------------------------------------------------------------------
# Benchmark: Memory classification via general_extractor.extract_memories()
# ---------------------------------------------------------------------------


def bench_classification(iterations):
    """Benchmark memory type classification (uses NLP when available)."""
    from mempalace.general_extractor import extract_memories

    # Warmup
    extract_memories(TEXTS[0])

    start = time.perf_counter()
    total_memories = 0
    type_counts = {}
    for _ in range(iterations):
        for text in TEXTS:
            memories = extract_memories(text, min_confidence=0.1)
            total_memories += len(memories)
            for m in memories:
                mt = m["memory_type"]
                type_counts[mt] = type_counts.get(mt, 0) + 1
    elapsed = time.perf_counter() - start

    return {
        "time_s": elapsed,
        "ops_per_s": (iterations * len(TEXTS)) / elapsed,
        "total_memories": total_memories,
        "type_distribution": type_counts,
    }


# ---------------------------------------------------------------------------
# Benchmark: Dialect compress/decompress (end-to-end)
# ---------------------------------------------------------------------------


def bench_dialect_roundtrip(iterations):
    """Benchmark dialect compression + decode (uses NLP internally)."""
    from mempalace.dialect import Dialect

    d = Dialect()

    # Warmup
    compressed = d.compress(TEXTS[0])
    d.decode(compressed)

    start = time.perf_counter()
    total_ratio = 0.0
    count = 0
    for _ in range(iterations):
        for text in TEXTS:
            compressed = d.compress(text)
            d.decode(compressed)
            if compressed and text:
                total_ratio += len(compressed) / len(text)
                count += 1
    elapsed = time.perf_counter() - start

    return {
        "time_s": elapsed,
        "ops_per_s": (iterations * len(TEXTS)) / elapsed,
        "avg_compression_ratio": total_ratio / count if count else 0,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def print_results(capability, results):
    print(f"\n{'=' * 60}")
    print(f"  {capability}")
    print(f"{'=' * 60}")
    for key, val in results.items():
        if isinstance(val, list):
            print(f"    {key}: {val}")
        elif isinstance(val, float):
            print(f"    {key}: {val:.4f}")
        elif isinstance(val, dict):
            print(f"    {key}:")
            for k, v in val.items():
                print(f"      {k}: {v}")
        else:
            print(f"    {key}: {val}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Benchmark mempalace with/without NLP providers")
    parser.add_argument(
        "--iterations",
        type=int,
        default=50,
        help="Number of iterations per benchmark (default: 50)",
    )
    args = parser.parse_args()

    print(f"MemPalace NLP Benchmark — {args.iterations} iterations")
    print()

    # Report NLP status
    flags = _nlp_status()
    print("NLP feature flags:")
    for flag, enabled in flags.items():
        print(f"  MEMPALACE_NLP_{flag}: {'ON' if enabled else 'off'}")

    print()
    print("Available NLP packages:")
    for pkg in ["pysbd", "spacy", "gliner", "wtpsplit", "onnxruntime_genai"]:
        status = "installed" if _has_package(pkg) else "not installed"
        print(f"  {pkg}: {status}")

    print()
    print("-" * 60)

    results = bench_sentence_splitting(args.iterations)
    print_results("Sentence Splitting (dialect._split_sentences)", results)

    results = bench_entity_extraction(args.iterations)
    print_results("Entity Extraction (entity_detector.extract_candidates)", results)

    results = bench_classification(args.iterations)
    print_results("Memory Classification (general_extractor.extract_memories)", results)

    results = bench_dialect_roundtrip(args.iterations)
    print_results("Dialect Compress/Decompress Roundtrip", results)

    print("Done.")


if __name__ == "__main__":
    main()
