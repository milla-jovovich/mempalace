#!/usr/bin/env python3
"""
Triple Extraction Quality Benchmark
====================================

Compares triple extraction quality across three approaches:
1. Legacy (no NLP) — entity co-occurrence heuristic via extract_candidates()
2. GLiNER2 — zero-shot NER + relation extraction
3. SLM (Phi-3.5 Mini) — prompted triple extraction

Each approach is evaluated against hand-labeled ground truth triples
on conversational/knowledge-management text similar to what MemPalace
ingests in practice.

Metrics:
- Precision: fraction of extracted triples that match ground truth
- Recall: fraction of ground truth triples that were extracted
- F1: harmonic mean of precision and recall

Usage:
    python benchmarks/bench_triples.py
    python benchmarks/bench_triples.py --provider gliner
    python benchmarks/bench_triples.py --provider slm
    python benchmarks/bench_triples.py --provider legacy
    python benchmarks/bench_triples.py --provider all
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# Ground truth: (text, expected_triples) pairs
# Each triple is (subject, predicate, object) — fuzzy-matched
GROUND_TRUTH = [
    {
        "text": (
            "Alice works at Anthropic in San Francisco. "
            "She joined the AI safety team in January 2024."
        ),
        "triples": [
            ("Alice", "works at", "Anthropic"),
            ("Anthropic", "located in", "San Francisco"),
            ("Alice", "joined", "AI safety team"),
        ],
    },
    {
        "text": (
            "We decided to use PostgreSQL instead of MySQL for the new project. "
            "Bob recommended it because of better JSON support."
        ),
        "triples": [
            ("We", "decided to use", "PostgreSQL"),
            ("Bob", "recommended", "PostgreSQL"),
        ],
    },
    {
        "text": (
            "The backend team migrated the API from REST to GraphQL last month. "
            "Performance improved by 40 percent after the migration."
        ),
        "triples": [
            ("backend team", "migrated", "API"),
            ("API", "migrated from", "REST"),
            ("API", "migrated to", "GraphQL"),
        ],
    },
    {
        "text": (
            "Dr. Smith presented the quarterly results to the board on Thursday. "
            "Revenue grew 15 percent year over year."
        ),
        "triples": [
            ("Dr. Smith", "presented", "quarterly results"),
            ("Dr. Smith", "presented to", "board"),
        ],
    },
    {
        "text": (
            "I switched from VS Code to Neovim for my daily coding. "
            "The Lua configuration took a weekend to set up but it was worth it."
        ),
        "triples": [
            ("I", "switched from", "VS Code"),
            ("I", "switched to", "Neovim"),
        ],
    },
    {
        "text": (
            "Sarah manages the frontend team at Google. "
            "Her team built the new dashboard using React and TypeScript."
        ),
        "triples": [
            ("Sarah", "manages", "frontend team"),
            ("Sarah", "works at", "Google"),
            ("team", "built", "dashboard"),
        ],
    },
    {
        "text": (
            "The company moved from AWS to GCP in Q3 2024. "
            "Cloud costs dropped by 30 percent after the migration."
        ),
        "triples": [
            ("company", "moved from", "AWS"),
            ("company", "moved to", "GCP"),
        ],
    },
    {
        "text": (
            "Mark trained the new machine learning model on 10 million documents. "
            "It achieved 95 percent accuracy on the test set."
        ),
        "triples": [
            ("Mark", "trained", "machine learning model"),
        ],
    },
]


def _fuzzy_match_triple(extracted, expected):
    """Check if an extracted triple fuzzy-matches an expected one.

    Matching is case-insensitive and checks if key terms from the expected
    triple appear in the extracted triple's fields.
    """
    e_subj = extracted.get("subject", "").lower()
    e_pred = extracted.get("predicate", extracted.get("relation", "")).lower()
    e_obj = extracted.get("object", "").lower()

    gt_subj, gt_pred, gt_obj = [s.lower() for s in expected]

    # Subject match: key words from ground truth appear in extracted
    subj_words = [w for w in gt_subj.split() if len(w) > 2]
    subj_match = any(w in e_subj for w in subj_words) if subj_words else True

    # Object match
    obj_words = [w for w in gt_obj.split() if len(w) > 2]
    obj_match = any(w in e_obj for w in obj_words) if obj_words else True

    # Predicate match: at least one key word overlaps
    pred_words = [w for w in gt_pred.split() if len(w) > 2]
    pred_match = any(w in e_pred for w in pred_words) if pred_words else True

    return subj_match and obj_match and pred_match


def _extract_legacy(text):
    """Legacy approach: entity co-occurrence pairs."""
    from mempalace.entity_detector import extract_candidates

    candidates = extract_candidates(text)
    names = list(candidates.keys())
    triples = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            triples.append({"subject": names[i], "predicate": "co-occurs", "object": names[j]})
    return triples


def _extract_gliner(text):
    """GLiNER2 triple extraction."""
    from mempalace.nlp_providers.registry import get_registry

    registry = get_registry()
    provider = registry._load_provider("gliner")
    if provider and provider.is_available() and "triples" in provider.capabilities:
        return provider.extract_triples(text)
    return None


def _extract_slm(text):
    """SLM (Phi-3.5 Mini) triple extraction."""
    from mempalace.nlp_providers.registry import get_registry

    registry = get_registry()
    provider = registry._load_provider("slm")
    if provider and provider.is_available() and "triples" in provider.capabilities:
        return provider.extract_triples(text)
    return None


def evaluate_provider(name, extract_fn):
    """Evaluate a triple extraction approach against ground truth."""
    total_precision_hits = 0
    total_extracted = 0
    total_recall_hits = 0
    total_expected = 0
    total_time = 0

    print(f"\n{'─' * 60}")
    print(f"  Provider: {name}")
    print(f"{'─' * 60}")

    for i, entry in enumerate(GROUND_TRUTH):
        text = entry["text"]
        expected = entry["triples"]

        start = time.perf_counter()
        extracted = extract_fn(text)
        elapsed = time.perf_counter() - start
        total_time += elapsed

        if extracted is None:
            print(f"  [{i + 1}] SKIPPED (provider not available)")
            return None

        # Precision: how many extracted triples match ground truth
        precision_hits = 0
        for et in extracted:
            if any(_fuzzy_match_triple(et, gt) for gt in expected):
                precision_hits += 1

        # Recall: how many ground truth triples were found
        recall_hits = 0
        for gt in expected:
            if any(_fuzzy_match_triple(et, gt) for et in extracted):
                recall_hits += 1

        total_precision_hits += precision_hits
        total_extracted += len(extracted)
        total_recall_hits += recall_hits
        total_expected += len(expected)

        prec = precision_hits / len(extracted) if extracted else 0
        rec = recall_hits / len(expected) if expected else 0

        print(
            f"  [{i + 1}] extracted={len(extracted):2d}  "
            f"precision={prec:.2f}  recall={rec:.2f}  "
            f"({elapsed * 1000:.0f}ms)"
        )

    # Aggregate scores
    precision = total_precision_hits / total_extracted if total_extracted else 0
    recall = total_recall_hits / total_expected if total_expected else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

    print(f"\n  {'=' * 50}")
    print(f"  {name} RESULTS:")
    print(f"  Precision:  {precision:.3f}  ({total_precision_hits}/{total_extracted})")
    print(f"  Recall:     {recall:.3f}  ({total_recall_hits}/{total_expected})")
    print(f"  F1:         {f1:.3f}")
    print(f"  Total time: {total_time:.2f}s ({total_time / len(GROUND_TRUTH) * 1000:.0f}ms/text)")
    print(f"  {'=' * 50}")

    return {"precision": precision, "recall": recall, "f1": f1, "time": total_time}


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Triple Extraction Quality Benchmark")
    parser.add_argument(
        "--provider",
        choices=["legacy", "gliner", "slm", "all"],
        default="all",
        help="Which provider to benchmark (default: all)",
    )
    args = parser.parse_args()

    print("Triple Extraction Quality Benchmark")
    print("=" * 60)
    print(f"  Test cases: {len(GROUND_TRUTH)}")
    print(f"  Total ground-truth triples: {sum(len(e['triples']) for e in GROUND_TRUTH)}")

    providers = {
        "legacy": ("Legacy (co-occurrence)", _extract_legacy),
        "gliner": ("GLiNER2 (zero-shot)", _extract_gliner),
        "slm": ("SLM / Phi-3.5 Mini (prompted)", _extract_slm),
    }

    if args.provider == "all":
        selected = list(providers.items())
    else:
        selected = [(args.provider, providers[args.provider])]

    results = {}
    for key, (name, fn) in selected:
        result = evaluate_provider(name, fn)
        if result:
            results[key] = result

    if len(results) > 1:
        print(f"\n{'=' * 60}")
        print("  COMPARISON SUMMARY")
        print(f"{'=' * 60}")
        print(f"  {'Provider':<30} {'Precision':>9} {'Recall':>8} {'F1':>8} {'Time':>8}")
        print(f"  {'─' * 58}")
        for key, r in results.items():
            name = providers[key][0]
            print(
                f"  {name:<30} {r['precision']:>9.3f} {r['recall']:>8.3f} "
                f"{r['f1']:>8.3f} {r['time']:>7.2f}s"
            )
        print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
