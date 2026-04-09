#!/usr/bin/env python3
"""
NLP Provider Benchmark
======================

Benchmarks NLP providers against the legacy regex baseline.
Measures accuracy, throughput, and memory usage for each capability:
  - Sentence splitting (pySBD, spaCy, wtpsplit vs regex)
  - NER (spaCy, GLiNER vs regex pattern matching)
  - Classification (GLiNER vs keyword markers)
  - Triple extraction (GLiNER vs none)

Usage:
    # Run all benchmarks (skips unavailable providers):
    python benchmarks/with-nlp-provider/bench_nlp_providers.py

    # Run specific capability:
    python benchmarks/with-nlp-provider/bench_nlp_providers.py --capability sentences

    # Run with custom iterations:
    python benchmarks/with-nlp-provider/bench_nlp_providers.py --iterations 100
"""

import argparse
import sys
import time
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

SENTENCE_TEXTS = [
    "Dr. Smith went to Washington. He met with officials. The meeting lasted 2 hours.",
    "I don't like the new API. However, it's faster than the old one. Let's keep it for now.",
    "We decided to use PostgreSQL because it handles JSON natively. "
    "The migration from MySQL took three weeks but it was worth it. "
    "Python's SQLAlchemy ORM made the transition much smoother.",
    "Bug: the connection pool was exhausted under high load. "
    "Root cause: each request opened a new connection instead of reusing. "
    "The fix was to configure max_pool_size=20 in the database settings.",
    "Alice works at Anthropic in San Francisco. She builds AI systems. "
    "Her colleague Bob moved from Google last year. They collaborate on safety research.",
]

NER_TEXTS = [
    "Barack Obama was born in Hawaii and served as the 44th President.",
    "Alice works at Anthropic in San Francisco.",
    "Python and JavaScript are popular programming languages.",
    "The meeting with Dr. Smith is scheduled for March 15, 2025.",
    "Microsoft acquired GitHub for $7.5 billion in 2018.",
]

CLASSIFY_TEXTS = [
    ("We decided to use PostgreSQL because it handles JSON well.", "decision"),
    ("I always use black for formatting Python code.", "preference"),
    ("Finally got the tests passing after three days of debugging!", "milestone"),
    ("Bug: the API returns 500 when the payload exceeds 10MB.", "problem"),
    ("I'm so proud of what we've built together.", "emotional"),
]


def _has_package(name):
    try:
        __import__(name)
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Benchmark: Sentence Splitting
# ---------------------------------------------------------------------------


def bench_sentences(iterations):
    """Benchmark sentence splitting across providers."""
    import re

    results = {}

    # Legacy (regex)
    def legacy_split(text):
        return [s.strip() for s in re.split(r"[.!?\n]+", text) if s.strip()]

    start = time.perf_counter()
    for _ in range(iterations):
        for text in SENTENCE_TEXTS:
            legacy_split(text)
    elapsed = time.perf_counter() - start
    sample = legacy_split(SENTENCE_TEXTS[0])
    results["legacy (regex)"] = {
        "time_s": elapsed,
        "ops_per_s": (iterations * len(SENTENCE_TEXTS)) / elapsed,
        "sample_count": len(sample),
        "sample": sample[:3],
    }

    # pySBD
    if _has_package("pysbd"):
        os.environ["MEMPALACE_NLP_SENTENCES"] = "1"
        from mempalace.nlp_providers.pysbd_provider import PySBDProvider

        p = PySBDProvider()
        if p.is_available():
            # Warmup
            p.split_sentences(SENTENCE_TEXTS[0])

            start = time.perf_counter()
            for _ in range(iterations):
                for text in SENTENCE_TEXTS:
                    p.split_sentences(text)
            elapsed = time.perf_counter() - start
            sample = p.split_sentences(SENTENCE_TEXTS[0])
            results["pySBD"] = {
                "time_s": elapsed,
                "ops_per_s": (iterations * len(SENTENCE_TEXTS)) / elapsed,
                "sample_count": len(sample),
                "sample": sample[:3],
            }

    # spaCy
    if _has_package("spacy"):
        os.environ["MEMPALACE_NLP_NER"] = "1"
        from mempalace.nlp_providers.spacy_provider import SpaCyProvider

        p = SpaCyProvider()
        if p.is_available():
            p.split_sentences(SENTENCE_TEXTS[0])  # warmup

            start = time.perf_counter()
            for _ in range(iterations):
                for text in SENTENCE_TEXTS:
                    p.split_sentences(text)
            elapsed = time.perf_counter() - start
            sample = p.split_sentences(SENTENCE_TEXTS[0])
            results["spaCy"] = {
                "time_s": elapsed,
                "ops_per_s": (iterations * len(SENTENCE_TEXTS)) / elapsed,
                "sample_count": len(sample),
                "sample": sample[:3],
            }

    # wtpsplit
    if _has_package("wtpsplit"):
        os.environ["MEMPALACE_NLP_SENTENCES"] = "1"
        from mempalace.nlp_providers.wtpsplit_provider import WtpsplitProvider

        p = WtpsplitProvider()
        if p.is_available():
            p.split_sentences(SENTENCE_TEXTS[0])  # warmup

            start = time.perf_counter()
            for _ in range(iterations):
                for text in SENTENCE_TEXTS:
                    p.split_sentences(text)
            elapsed = time.perf_counter() - start
            sample = p.split_sentences(SENTENCE_TEXTS[0])
            results["wtpsplit"] = {
                "time_s": elapsed,
                "ops_per_s": (iterations * len(SENTENCE_TEXTS)) / elapsed,
                "sample_count": len(sample),
                "sample": sample[:3],
            }

    return results


# ---------------------------------------------------------------------------
# Benchmark: NER
# ---------------------------------------------------------------------------


def bench_ner(iterations):
    """Benchmark NER across providers."""
    results = {}

    # Legacy (regex pattern matching via entity_detector)
    from mempalace.entity_detector import extract_candidates

    start = time.perf_counter()
    for _ in range(iterations):
        for text in NER_TEXTS:
            extract_candidates(text)
    elapsed = time.perf_counter() - start
    sample = extract_candidates(NER_TEXTS[0])
    results["legacy (regex)"] = {
        "time_s": elapsed,
        "ops_per_s": (iterations * len(NER_TEXTS)) / elapsed,
        "entities_found": len(sample),
    }

    # spaCy
    if _has_package("spacy"):
        os.environ["MEMPALACE_NLP_NER"] = "1"
        from mempalace.nlp_providers.spacy_provider import SpaCyProvider

        p = SpaCyProvider()
        if p.is_available():
            p.extract_entities(NER_TEXTS[0])  # warmup

            start = time.perf_counter()
            for _ in range(iterations):
                for text in NER_TEXTS:
                    p.extract_entities(text)
            elapsed = time.perf_counter() - start
            sample = p.extract_entities(NER_TEXTS[0])
            results["spaCy"] = {
                "time_s": elapsed,
                "ops_per_s": (iterations * len(NER_TEXTS)) / elapsed,
                "entities_found": len(sample),
                "sample": [e["text"] for e in sample[:5]],
            }

    # GLiNER
    if _has_package("gliner"):
        os.environ["MEMPALACE_NLP_NER"] = "1"
        from mempalace.nlp_providers.gliner_provider import GLiNERProvider

        p = GLiNERProvider()
        if p.is_available():
            p.extract_entities(NER_TEXTS[0])  # warmup

            start = time.perf_counter()
            for _ in range(iterations):
                for text in NER_TEXTS:
                    p.extract_entities(text)
            elapsed = time.perf_counter() - start
            sample = p.extract_entities(NER_TEXTS[0])
            results["GLiNER"] = {
                "time_s": elapsed,
                "ops_per_s": (iterations * len(NER_TEXTS)) / elapsed,
                "entities_found": len(sample),
                "sample": [e["text"] for e in sample[:5]],
            }

    return results


# ---------------------------------------------------------------------------
# Benchmark: Classification
# ---------------------------------------------------------------------------


def bench_classify(iterations):
    """Benchmark text classification."""
    from mempalace.general_extractor import extract_memories

    results = {}

    # Legacy (regex markers)
    start = time.perf_counter()
    correct = 0
    total = 0
    for _ in range(iterations):
        for text, expected_type in CLASSIFY_TEXTS:
            memories = extract_memories(text, min_confidence=0.1)
            if memories and memories[0]["memory_type"] == expected_type:
                correct += 1
            total += 1
    elapsed = time.perf_counter() - start
    results["legacy (regex)"] = {
        "time_s": elapsed,
        "ops_per_s": total / elapsed,
        "accuracy": correct / total if total > 0 else 0,
    }

    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def print_results(capability, results):
    print(f"\n{'=' * 60}")
    print(f"  {capability.upper()}")
    print(f"{'=' * 60}")
    for provider, metrics in results.items():
        print(f"\n  {provider}:")
        for key, val in metrics.items():
            if key == "sample":
                print(f"    {key}: {val[:3]}")
            elif isinstance(val, float):
                print(f"    {key}: {val:.4f}")
            else:
                print(f"    {key}: {val}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Benchmark NLP providers vs legacy")
    parser.add_argument(
        "--capability",
        choices=["sentences", "ner", "classify", "all"],
        default="all",
        help="Which capability to benchmark",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=50,
        help="Number of iterations per benchmark",
    )
    args = parser.parse_args()

    print(f"NLP Provider Benchmark — {args.iterations} iterations")
    print("Available packages: ", end="")
    for pkg in ["pysbd", "spacy", "gliner", "wtpsplit", "onnxruntime_genai"]:
        status = "yes" if _has_package(pkg) else "no"
        print(f"{pkg}={status} ", end="")
    print()

    if args.capability in ("sentences", "all"):
        results = bench_sentences(args.iterations)
        print_results("Sentence Splitting", results)

    if args.capability in ("ner", "all"):
        results = bench_ner(args.iterations)
        print_results("Named Entity Recognition", results)

    if args.capability in ("classify", "all"):
        results = bench_classify(args.iterations)
        print_results("Classification", results)

    print("\nDone.")


if __name__ == "__main__":
    main()
