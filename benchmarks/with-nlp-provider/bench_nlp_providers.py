#!/usr/bin/env python3
"""
NLP Provider Quality Benchmark (LongMemEval)
=============================================

Evaluates how NLP providers affect retrieval quality on the LongMemEval dataset.
Extends longmemeval_bench.py with NLP-enhanced ingestion modes.

NLP-enhanced modes:
    nlp-aaak    — AAAK dialect compression with NLP sentence splitting + NER
    nlp-hybrid  — Hybrid retrieval with NLP entity extraction for keyword boosting

Compares NLP-enhanced results against baseline modes from longmemeval_bench.py
to measure whether NLP providers improve Recall@k and NDCG@k.

Usage:
    # Compare baseline vs NLP-enhanced (requires longmemeval dataset):
    python benchmarks/with-nlp-provider/bench_nlp_providers.py data/longmemeval_s_cleaned.json

    # Quick smoke test (5 questions):
    python benchmarks/with-nlp-provider/bench_nlp_providers.py data/longmemeval_s_cleaned.json --limit 5

    # NLP-enhanced AAAK only:
    MEMPALACE_NLP_SENTENCES=1 MEMPALACE_NLP_NER=1 \
      python benchmarks/with-nlp-provider/bench_nlp_providers.py data/longmemeval_s_cleaned.json --mode nlp-aaak

    # Run without dataset (self-contained quality checks):
    python benchmarks/with-nlp-provider/bench_nlp_providers.py --self-test
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import from longmemeval_bench
sys.path.insert(0, str(Path(__file__).parent.parent))
from longmemeval_bench import (
    _fresh_collection,
    build_palace_and_retrieve,
    build_palace_and_retrieve_aaak,
    build_palace_and_retrieve_hybrid,
    evaluate_retrieval,
    session_id_from_corpus_id,
)


# =============================================================================
# NLP-ENHANCED RETRIEVAL MODES
# =============================================================================


def build_palace_and_retrieve_nlp_aaak(entry, granularity="session", n_results=50):
    """
    NLP-enhanced AAAK mode: uses NLP providers for better sentence splitting,
    entity detection, and compression during AAAK ingestion.

    When NLP flags are enabled:
    - MEMPALACE_NLP_SENTENCES=1: pySBD/wtpsplit for sentence boundaries
    - MEMPALACE_NLP_NER=1: spaCy/GLiNER for named entity recognition
    - MEMPALACE_NLP_CLASSIFY=1: NLP-assisted memory type classification

    The Dialect.compress() method automatically uses NLP providers when available
    and flags are set, so this mode benefits from NLP transparently.
    """
    from mempalace.dialect import Dialect
    from mempalace.entity_detector import extract_candidates

    # Pre-scan for entities across all sessions to build entity codes
    all_text = []
    sessions = entry["haystack_sessions"]
    for session in sessions:
        for turn in session:
            if turn["role"] == "user":
                all_text.append(turn["content"])
    combined = " ".join(all_text[:20])  # First 20 turns for entity detection
    candidates = extract_candidates(combined)

    # Build entity code map from detected entities
    entity_codes = {}
    for name in list(candidates.keys())[:20]:  # Cap at 20 entities
        code = name[:3].upper()
        if code not in entity_codes.values():
            entity_codes[name] = code

    dialect = Dialect(entities=entity_codes)

    corpus = []
    corpus_compressed = []
    corpus_ids = []
    corpus_timestamps = []

    session_ids = entry["haystack_session_ids"]
    dates = entry["haystack_dates"]

    for sess_idx, (session, sess_id, date) in enumerate(zip(sessions, session_ids, dates)):
        if granularity == "session":
            user_turns = [t["content"] for t in session if t["role"] == "user"]
            if user_turns:
                doc = "\n".join(user_turns)
                compressed = dialect.compress(doc, metadata={"date": date})
                corpus.append(doc)
                corpus_compressed.append(compressed)
                corpus_ids.append(sess_id)
                corpus_timestamps.append(date)
        else:
            turn_num = 0
            for turn in session:
                if turn["role"] == "user":
                    compressed = dialect.compress(turn["content"])
                    corpus.append(turn["content"])
                    corpus_compressed.append(compressed)
                    corpus_ids.append(f"{sess_id}_turn_{turn_num}")
                    corpus_timestamps.append(date)
                    turn_num += 1

    if not corpus:
        return [], corpus, corpus_ids, corpus_timestamps

    collection = _fresh_collection()
    collection.add(
        documents=corpus_compressed,
        ids=[f"doc_{i}" for i in range(len(corpus_compressed))],
        metadatas=[
            {"corpus_id": cid, "timestamp": ts} for cid, ts in zip(corpus_ids, corpus_timestamps)
        ],
    )

    query = entry["question"]
    results = collection.query(
        query_texts=[query],
        n_results=min(n_results, len(corpus)),
        include=["distances", "metadatas"],
    )

    result_ids = results["ids"][0]
    doc_id_to_idx = {f"doc_{i}": i for i in range(len(corpus))}
    ranked_indices = [doc_id_to_idx[rid] for rid in result_ids]

    seen = set(ranked_indices)
    for i in range(len(corpus)):
        if i not in seen:
            ranked_indices.append(i)

    return ranked_indices, corpus, corpus_ids, corpus_timestamps


def build_palace_and_retrieve_nlp_hybrid(
    entry, granularity="session", n_results=50, hybrid_weight=0.30
):
    """
    NLP-enhanced hybrid mode: uses NLP entity extraction to improve keyword
    boosting in the hybrid retrieval pipeline.

    When NLP NER is active, entity names detected by spaCy/GLiNER are added
    to the keyword overlap computation, improving recall for entity-centric
    questions like "What did Alice do?" or "Tell me about the GraphQL project."
    """
    import re

    from mempalace.entity_detector import extract_candidates

    STOP_WORDS = {
        "what",
        "when",
        "where",
        "who",
        "how",
        "which",
        "did",
        "do",
        "was",
        "were",
        "have",
        "has",
        "had",
        "is",
        "are",
        "the",
        "a",
        "an",
        "my",
        "me",
        "i",
        "you",
        "your",
        "their",
        "it",
        "its",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "ago",
        "last",
        "that",
        "this",
        "there",
        "about",
        "get",
        "got",
        "give",
        "gave",
        "buy",
        "bought",
        "made",
        "make",
    }

    def extract_keywords(text):
        words = re.findall(r"\b[a-z]{3,}\b", text.lower())
        return [w for w in words if w not in STOP_WORDS]

    def keyword_overlap(query_kws, query_entities, doc_text):
        doc_lower = doc_text.lower()
        if not query_kws and not query_entities:
            return 0.0
        # Standard keyword overlap
        total = len(query_kws) + len(query_entities)
        hits = sum(1 for kw in query_kws if kw in doc_lower)
        # Entity overlap (higher weight — entities are more specific)
        hits += sum(2 for ent in query_entities if ent.lower() in doc_lower)
        total += len(query_entities)  # extra weight
        return hits / total if total else 0.0

    # Extract entities from the question using NLP
    question = entry["question"]
    query_entities = list(extract_candidates(question).keys())

    corpus = []
    corpus_ids = []
    corpus_timestamps = []

    sessions = entry["haystack_sessions"]
    session_ids = entry["haystack_session_ids"]
    dates = entry["haystack_dates"]

    for sess_idx, (session, sess_id, date) in enumerate(zip(sessions, session_ids, dates)):
        if granularity == "session":
            user_turns = [t["content"] for t in session if t["role"] == "user"]
            if user_turns:
                doc = "\n".join(user_turns)
                corpus.append(doc)
                corpus_ids.append(sess_id)
                corpus_timestamps.append(date)
        else:
            turn_num = 0
            for turn in session:
                if turn["role"] == "user":
                    corpus.append(turn["content"])
                    corpus_ids.append(f"{sess_id}_turn_{turn_num}")
                    corpus_timestamps.append(date)
                    turn_num += 1

    if not corpus:
        return [], corpus, corpus_ids, corpus_timestamps

    collection = _fresh_collection()
    collection.add(
        documents=corpus,
        ids=[f"doc_{i}" for i in range(len(corpus))],
        metadatas=[
            {"corpus_id": cid, "timestamp": ts} for cid, ts in zip(corpus_ids, corpus_timestamps)
        ],
    )

    query_keywords = extract_keywords(question)
    results = collection.query(
        query_texts=[question],
        n_results=min(n_results, len(corpus)),
        include=["distances", "metadatas", "documents"],
    )

    result_ids = results["ids"][0]
    distances = results["distances"][0]
    documents = results["documents"][0]
    doc_id_to_idx = {f"doc_{i}": i for i in range(len(corpus))}

    scored = []
    for rid, dist, doc in zip(result_ids, distances, documents):
        idx = doc_id_to_idx[rid]
        overlap = keyword_overlap(query_keywords, query_entities, doc)
        fused_dist = dist * (1.0 - hybrid_weight * overlap)
        scored.append((idx, fused_dist))

    scored.sort(key=lambda x: x[1])
    ranked_indices = [idx for idx, _ in scored]

    seen = set(ranked_indices)
    for i in range(len(corpus)):
        if i not in seen:
            ranked_indices.append(i)

    return ranked_indices, corpus, corpus_ids, corpus_timestamps


# =============================================================================
# SELF-TEST (runs without LongMemEval dataset)
# =============================================================================

SELF_TEST_TEXTS = [
    "We decided to use PostgreSQL because it handles JSON natively. "
    "The migration from MySQL took three weeks but it was worth it.",
    "Alice works at Anthropic in San Francisco. She builds AI systems. "
    "Her colleague Bob moved from Google last year.",
    "I'm so proud of what we've built together. This has been an amazing journey.",
    "Dr. Smith went to Washington. He met with officials. The meeting lasted 2 hours.",
]


def run_self_test():
    """Run self-contained quality checks without the LongMemEval dataset."""
    from mempalace.dialect import Dialect
    from mempalace.entity_detector import extract_candidates
    from mempalace.general_extractor import extract_memories

    flags = _nlp_status()
    any_nlp = any(flags.values())
    mode = "NLP-ENHANCED" if any_nlp else "BASELINE (regex)"

    print(f"Self-test mode: {mode}")
    print()

    # Sentence splitting quality
    d = Dialect()
    print("Sentence Splitting:")
    for text in SELF_TEST_TEXTS:
        sents = d._split_sentences(text)
        print(f"  Input:  {text[:60]}...")
        print(f"  Output: {len(sents)} sentences")
        for s in sents:
            print(f"    - {s[:80]}")
    print()

    # Entity extraction quality
    print("Entity Extraction:")
    for text in SELF_TEST_TEXTS:
        candidates = extract_candidates(text)
        print(f"  Input:    {text[:60]}...")
        print(f"  Entities: {list(candidates.keys())}")
    print()

    # Classification quality
    print("Memory Classification:")
    for text in SELF_TEST_TEXTS:
        memories = extract_memories(text, min_confidence=0.1)
        types = [m["memory_type"] for m in memories] if memories else ["(none)"]
        print(f"  Input: {text[:60]}...")
        print(f"  Types: {types}")
    print()

    # Compression roundtrip
    print("Compression Fidelity:")
    for text in SELF_TEST_TEXTS:
        compressed = d.compress(text)
        stats = d.compression_stats(text, compressed)
        print(f"  Input:  {text[:60]}...")
        print(f"  Output: {compressed[:80]}...")
        print(f"  Ratio:  {stats['size_ratio']:.2f}x")
    print()

    print("Self-test complete.")


# =============================================================================
# BENCHMARK RUNNER
# =============================================================================


def _nlp_status():
    flags = {}
    for key in ["SENTENCES", "NEGATION", "NER", "CLASSIFY", "TRIPLES"]:
        flags[key] = os.environ.get(f"MEMPALACE_NLP_{key}", "0") == "1"
    return flags


def _has_package(name):
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def run_benchmark_mode(data, mode_name, retrieve_fn, granularity="session", ks=(1, 3, 5, 10)):
    """Run a single benchmark mode and return metrics."""
    metrics = defaultdict(list)
    per_type = defaultdict(lambda: defaultdict(list))
    hits = 0
    total = 0

    start_time = time.perf_counter()

    for i, entry in enumerate(data):
        qtype = entry.get("question_type", "unknown")
        answer_sids = set(entry["answer_session_ids"])

        rankings, corpus, corpus_ids, corpus_timestamps = retrieve_fn(
            entry, granularity=granularity
        )

        if not rankings:
            continue

        total += 1
        session_level_ids = [session_id_from_corpus_id(cid) for cid in corpus_ids]

        for k in ks:
            ra, rl, nd = evaluate_retrieval(rankings, answer_sids, session_level_ids, k)
            metrics[f"recall_any@{k}"].append(ra)
            metrics[f"ndcg_any@{k}"].append(nd)

        if metrics["recall_any@5"][-1] > 0:
            hits += 1

        per_type[qtype]["recall_any@5"].append(metrics["recall_any@5"][-1])
        per_type[qtype]["recall_any@10"].append(metrics["recall_any@10"][-1])

    elapsed = time.perf_counter() - start_time

    # Compute averages
    avg_metrics = {}
    for key, values in metrics.items():
        avg_metrics[key] = sum(values) / len(values) if values else 0

    return {
        "mode": mode_name,
        "total": total,
        "hits_at_5": hits,
        "elapsed_s": round(elapsed, 1),
        "metrics": avg_metrics,
        "per_type": {
            qtype: {k: sum(v) / len(v) for k, v in vals.items()} for qtype, vals in per_type.items()
        },
    }


def print_comparison(results_list):
    """Print side-by-side comparison of multiple modes."""
    print(f"\n{'=' * 80}")
    print("  COMPARISON: NLP Provider Impact on Retrieval Quality")
    print(f"{'=' * 80}\n")

    # Header
    modes = [r["mode"] for r in results_list]
    header = f"{'Metric':<25}" + "".join(f"{m:>15}" for m in modes)
    print(header)
    print("-" * len(header))

    # Key metrics
    for metric in ["recall_any@1", "recall_any@3", "recall_any@5", "recall_any@10"]:
        row = f"{metric:<25}"
        for r in results_list:
            val = r["metrics"].get(metric, 0)
            row += f"{val:>14.3f} "
        print(row)

    print()
    for metric in ["ndcg_any@5", "ndcg_any@10"]:
        row = f"{metric:<25}"
        for r in results_list:
            val = r["metrics"].get(metric, 0)
            row += f"{val:>14.3f} "
        print(row)

    print()
    row = f"{'Time (s)':<25}"
    for r in results_list:
        row += f"{r['elapsed_s']:>14.1f} "
    print(row)

    row = f"{'Hits@5':<25}"
    for r in results_list:
        row += f"{r['hits_at_5']:>11}/{r['total']} "
    print(row)

    # Per-type breakdown
    all_types = sorted(set(t for r in results_list for t in r["per_type"]))
    if all_types:
        print("\n  PER-TYPE BREAKDOWN (recall_any@10):")
        for qtype in all_types:
            row = f"    {qtype:<30}"
            for r in results_list:
                val = r["per_type"].get(qtype, {}).get("recall_any@10", 0)
                row += f"{val:>10.3f} "
            print(row)

    print(f"\n{'=' * 80}\n")


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="NLP Provider Quality Benchmark — LongMemEval-based evaluation"
    )
    parser.add_argument("data_file", nargs="?", help="Path to longmemeval_s_cleaned.json")
    parser.add_argument("--limit", type=int, default=0, help="Limit to N questions (0 = all)")
    parser.add_argument(
        "--granularity",
        choices=["session", "turn"],
        default="session",
        help="Retrieval granularity (default: session)",
    )
    parser.add_argument(
        "--mode",
        choices=["all", "nlp-aaak", "nlp-hybrid", "compare"],
        default="compare",
        help="Mode: 'compare' runs baseline+NLP and shows comparison (default), "
        "'nlp-aaak' or 'nlp-hybrid' runs a single NLP mode, "
        "'all' runs all modes",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run self-contained quality checks without LongMemEval dataset",
    )
    args = parser.parse_args()

    # Report environment
    flags = _nlp_status()
    any_nlp = any(flags.values())
    print("MemPalace NLP Quality Benchmark (LongMemEval)")
    print("=" * 60)
    print(f"\nNLP mode: {'ENHANCED' if any_nlp else 'BASELINE (regex)'}")
    print("NLP feature flags:")
    for flag, enabled in flags.items():
        print(f"  MEMPALACE_NLP_{flag}: {'ON' if enabled else 'off'}")
    print("\nAvailable NLP packages:")
    for pkg in ["pysbd", "spacy", "gliner", "wtpsplit"]:
        status = "installed" if _has_package(pkg) else "not installed"
        print(f"  {pkg}: {status}")

    if args.self_test or not args.data_file:
        if not args.data_file:
            print("\nNo data file provided — running self-test mode.")
            print("For full benchmark: provide path to longmemeval_s_cleaned.json\n")
        run_self_test()
        return

    # Load dataset
    print(f"\nLoading dataset: {args.data_file}")
    with open(args.data_file) as f:
        data = json.load(f)
    if args.limit > 0:
        data = data[: args.limit]
    print(f"  {len(data)} questions loaded\n")

    results = []

    if args.mode in ("compare", "all"):
        # Run baseline modes
        print("Running: raw (baseline)...")
        results.append(run_benchmark_mode(data, "raw", build_palace_and_retrieve, args.granularity))

        print("Running: aaak (baseline)...")
        results.append(
            run_benchmark_mode(data, "aaak", build_palace_and_retrieve_aaak, args.granularity)
        )

        if args.mode == "all":
            print("Running: hybrid (baseline)...")
            results.append(
                run_benchmark_mode(
                    data, "hybrid", build_palace_and_retrieve_hybrid, args.granularity
                )
            )

    if args.mode in ("compare", "all", "nlp-aaak"):
        print("Running: nlp-aaak (NLP-enhanced)...")
        results.append(
            run_benchmark_mode(
                data, "nlp-aaak", build_palace_and_retrieve_nlp_aaak, args.granularity
            )
        )

    if args.mode in ("compare", "all", "nlp-hybrid"):
        print("Running: nlp-hybrid (NLP-enhanced)...")
        results.append(
            run_benchmark_mode(
                data, "nlp-hybrid", build_palace_and_retrieve_nlp_hybrid, args.granularity
            )
        )

    if len(results) > 1:
        print_comparison(results)
    elif results:
        r = results[0]
        print(f"\n{'=' * 60}")
        print(f"  RESULTS — {r['mode']} mode")
        print(f"{'=' * 60}")
        for key, val in r["metrics"].items():
            print(f"  {key}: {val:.3f}")
        print(f"  Time: {r['elapsed_s']:.1f}s")
        print(f"  Hits@5: {r['hits_at_5']}/{r['total']}")

    print("\nDone.")


if __name__ == "__main__":
    main()
