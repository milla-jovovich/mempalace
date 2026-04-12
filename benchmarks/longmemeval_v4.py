#!/usr/bin/env python3
"""
longmemeval_v4.py — LongMemEval benchmark for MemPalace v4.0
==============================================================

Runs the same LongMemEval benchmark as the original longmemeval_bench.py but
uses the new db.py abstraction + pluggable embedders.  Produces side-by-side
comparison with the legacy ChromaDB baseline.

Modes:
    lance-default   — LanceDB + all-MiniLM-L6-v2 (Phase 1 default)
    lance-bge       — LanceDB + BAAI/bge-small-en-v1.5
    chroma-default  — ChromaDB + built-in all-MiniLM-L6-v2 (v3.x baseline)

Usage:
    # Quick validation (20 questions)
    python benchmarks/longmemeval_v4.py /tmp/longmemeval-data/longmemeval_s_cleaned.json --limit 20

    # Full benchmark — one embedder
    python benchmarks/longmemeval_v4.py DATA --mode lance-default

    # Full comparison — all modes
    python benchmarks/longmemeval_v4.py DATA --mode all

    # Specific embedder
    python benchmarks/longmemeval_v4.py DATA --mode lance --embedder bge-small
"""

import json
import math
import sys
import tempfile
import time
import argparse
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Metrics ───────────────────────────────────────────────────────────────────


def dcg(relevances, k):
    return sum(rel / math.log2(i + 2) for i, rel in enumerate(relevances[:k]))


def ndcg(rankings, correct_ids, corpus_ids, k):
    relevances = [1.0 if corpus_ids[idx] in correct_ids else 0.0 for idx in rankings[:k]]
    ideal = sorted(relevances, reverse=True)
    idcg = dcg(ideal, k)
    return dcg(relevances, k) / idcg if idcg > 0 else 0.0


# ── Collection factories ─────────────────────────────────────────────────────


def _make_lance_collection(embedder_name="all-MiniLM-L6-v2"):
    """Create a fresh ephemeral LanceDB collection."""
    from mempalace.embeddings import get_embedder
    from mempalace.db import LanceCollection
    import lancedb

    tmpdir = tempfile.mkdtemp()
    db = lancedb.connect(tmpdir)
    embedder = get_embedder({"embedder": embedder_name})

    return LanceCollection(db, "bench", embedder)


def _make_chroma_collection():
    """Create a fresh ephemeral ChromaDB collection (baseline)."""
    import chromadb

    client = chromadb.EphemeralClient()
    try:
        client.delete_collection("bench")
    except Exception:
        pass
    return client.create_collection("bench"), client


# ── Per-question retrieval ────────────────────────────────────────────────────


def retrieve_lance(entry, embedder_name="all-MiniLM-L6-v2", n_results=50):
    """Ingest + retrieve using LanceDB + specified embedder."""
    sessions = entry["haystack_sessions"]
    session_ids = entry["haystack_session_ids"]
    dates = entry["haystack_dates"]

    corpus, corpus_ids, corpus_ts = [], [], []
    for session, sid, dt in zip(sessions, session_ids, dates):
        user_turns = [t["content"] for t in session if t["role"] == "user"]
        if user_turns:
            corpus.append("\n".join(user_turns))
            corpus_ids.append(sid)
            corpus_ts.append(dt)

    if not corpus:
        return [], corpus, corpus_ids

    col = _make_lance_collection(embedder_name)
    col.upsert(
        documents=corpus,
        ids=[f"doc_{i}" for i in range(len(corpus))],
        metadatas=[
            {"corpus_id": cid, "timestamp": ts, "wing": "bench", "room": "bench", "source_file": ""}
            for cid, ts in zip(corpus_ids, corpus_ts)
        ],
    )

    results = col.query(
        query_texts=[entry["question"]],
        n_results=min(n_results, len(corpus)),
        include=["distances", "metadatas"],
    )

    doc_id_to_idx = {f"doc_{i}": i for i in range(len(corpus))}
    ranked = [doc_id_to_idx[rid] for rid in results["ids"][0]]
    seen = set(ranked)
    for i in range(len(corpus)):
        if i not in seen:
            ranked.append(i)

    return ranked, corpus, corpus_ids


def retrieve_chroma(entry, n_results=50):
    """Ingest + retrieve using ChromaDB (v3.x baseline)."""
    sessions = entry["haystack_sessions"]
    session_ids = entry["haystack_session_ids"]
    dates = entry["haystack_dates"]

    corpus, corpus_ids, corpus_ts = [], [], []
    for session, sid, dt in zip(sessions, session_ids, dates):
        user_turns = [t["content"] for t in session if t["role"] == "user"]
        if user_turns:
            corpus.append("\n".join(user_turns))
            corpus_ids.append(sid)
            corpus_ts.append(dt)

    if not corpus:
        return [], corpus, corpus_ids

    col, client = _make_chroma_collection()
    col.add(
        documents=corpus,
        ids=[f"doc_{i}" for i in range(len(corpus))],
        metadatas=[{"corpus_id": cid, "timestamp": ts} for cid, ts in zip(corpus_ids, corpus_ts)],
    )

    results = col.query(
        query_texts=[entry["question"]],
        n_results=min(n_results, len(corpus)),
        include=["distances", "metadatas"],
    )

    doc_id_to_idx = {f"doc_{i}": i for i in range(len(corpus))}
    ranked = [doc_id_to_idx[rid] for rid in results["ids"][0]]
    seen = set(ranked)
    for i in range(len(corpus)):
        if i not in seen:
            ranked.append(i)

    # Cleanup
    try:
        client.delete_collection("bench")
    except Exception:
        pass

    return ranked, corpus, corpus_ids


# ── Benchmark runner ──────────────────────────────────────────────────────────


def run_single_mode(data, mode_name, retrieve_fn, ks=(5, 10)):
    """Run one mode across all questions and return metrics."""
    metrics = {f"recall@{k}": [] for k in ks}
    metrics.update({f"ndcg@{k}": [] for k in ks})
    per_type = defaultdict(lambda: {f"recall@{k}": [] for k in ks})
    times = []

    for i, entry in enumerate(data):
        qtype = entry["question_type"]
        answer_sids = set(entry["answer_session_ids"])

        t0 = time.time()
        ranked, corpus, corpus_ids = retrieve_fn(entry)
        elapsed = time.time() - t0
        times.append(elapsed)

        if not ranked:
            continue

        for k in ks:
            top_k = set(corpus_ids[idx] for idx in ranked[:k])
            recall = float(any(sid in top_k for sid in answer_sids))
            ndcg_score = ndcg(ranked, answer_sids, corpus_ids, k)
            metrics[f"recall@{k}"].append(recall)
            metrics[f"ndcg@{k}"].append(ndcg_score)
            per_type[qtype][f"recall@{k}"].append(recall)

        if (i + 1) % 25 == 0 or i == 0:
            r5 = sum(metrics["recall@5"]) / len(metrics["recall@5"])
            avg_ms = sum(times) / len(times) * 1000
            print(f"  [{i + 1:4}/{len(data)}] {mode_name:20s}  R@5={r5:.3f}  avg={avg_ms:.0f}ms")

    # Aggregate
    summary = {}
    for key, vals in metrics.items():
        summary[key] = sum(vals) / len(vals) if vals else 0.0
    summary["avg_ms"] = sum(times) / len(times) * 1000 if times else 0
    summary["total_s"] = sum(times)
    summary["per_type"] = {}
    for qtype, type_metrics in per_type.items():
        summary["per_type"][qtype] = {
            k: sum(v) / len(v) if v else 0.0 for k, v in type_metrics.items()
        }

    return summary


def run_benchmark(data_file, modes, limit=0, out_file=None, embedder=None):
    """Run benchmark across multiple modes and produce comparison."""
    with open(data_file) as f:
        data = json.load(f)

    if limit > 0:
        data = data[:limit]

    print(f"\n{'=' * 70}")
    print("  MemPalace LongMemEval Benchmark (v4)")
    print(f"{'=' * 70}")
    print(f"  Questions:  {len(data)}")
    print(f"  Modes:      {', '.join(modes)}")
    print(f"  Timestamp:  {datetime.now().isoformat()}")
    print(f"{'=' * 70}\n")

    all_results = {}

    for mode in modes:
        print(f"\n── {mode} {'─' * (55 - len(mode))}\n")

        MODE_DISPATCH = {
            "chroma-default": lambda entry: retrieve_chroma(entry),
            "lance-default": lambda entry: retrieve_lance(entry, "all-MiniLM-L6-v2"),
            "lance-bge-small": lambda entry: retrieve_lance(entry, "BAAI/bge-small-en-v1.5"),
            "lance-bge-base": lambda entry: retrieve_lance(entry, "BAAI/bge-base-en-v1.5"),
            "lance-nomic": lambda entry: retrieve_lance(entry, "nomic-ai/nomic-embed-text-v1.5"),
        }

        if mode in MODE_DISPATCH:
            fn = MODE_DISPATCH[mode]
        elif mode.startswith("lance-"):
            emb = embedder or mode.split("lance-", 1)[1]

            def fn(entry, _e=emb):
                return retrieve_lance(entry, _e)
        else:
            print(f"  Unknown mode: {mode}, skipping.")
            continue

        summary = run_single_mode(data, mode, fn)
        all_results[mode] = summary

    # ── Print comparison table ────────────────────────────────────────

    print(f"\n\n{'=' * 70}")
    print("  RESULTS COMPARISON")
    print(f"{'=' * 70}\n")

    header = f"  {'Mode':25s} {'R@5':>8s} {'R@10':>8s} {'NDCG@5':>8s} {'NDCG@10':>8s} {'ms/q':>8s}"
    print(header)
    print(f"  {'─' * 65}")

    for mode, s in all_results.items():
        print(
            f"  {mode:25s} {s.get('recall@5', 0):8.3f} {s.get('recall@10', 0):8.3f} "
            f"{s.get('ndcg@5', 0):8.3f} {s.get('ndcg@10', 0):8.3f} {s.get('avg_ms', 0):8.0f}"
        )

    # Per-type breakdown
    all_types = set()
    for s in all_results.values():
        all_types.update(s.get("per_type", {}).keys())

    if all_types:
        print("\n  Per-type Recall@5:")
        print(f"  {'Type':30s}", end="")
        for mode in all_results:
            print(f" {mode[:12]:>12s}", end="")
        print()
        print(f"  {'─' * (30 + 13 * len(all_results))}")

        for qtype in sorted(all_types):
            print(f"  {qtype:30s}", end="")
            for mode, s in all_results.items():
                v = s.get("per_type", {}).get(qtype, {}).get("recall@5", 0)
                print(f" {v:12.3f}", end="")
            print()

    print(f"\n{'=' * 70}\n")

    # Save results
    if out_file:
        with open(out_file, "w") as f:
            json.dump(all_results, f, indent=2)
        print(f"  Results saved to {out_file}\n")

    return all_results


# ── CLI ───────────────────────────────────────────────────────────────────────

MODE_PRESETS = {
    "all": ["chroma-default", "lance-default", "lance-bge-small"],
    "quick": ["chroma-default", "lance-default"],
    "embedders": ["lance-default", "lance-bge-small", "lance-bge-base", "lance-nomic"],
}


def main():
    parser = argparse.ArgumentParser(description="MemPalace v4 LongMemEval Benchmark")
    parser.add_argument("data_file", help="Path to longmemeval_s_cleaned.json")
    parser.add_argument(
        "--mode",
        default="all",
        help="Mode(s): all, quick, embedders, or comma-separated "
        "(chroma-default, lance-default, lance-bge-small, lance-bge-base, lance-nomic)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Limit questions (0=all)")
    parser.add_argument("--out", default=None, help="Output JSON file for results")
    parser.add_argument("--embedder", default=None, help="Custom embedder for lance-custom mode")
    args = parser.parse_args()

    if args.mode in MODE_PRESETS:
        modes = MODE_PRESETS[args.mode]
    else:
        modes = [m.strip() for m in args.mode.split(",")]

    run_benchmark(
        args.data_file, modes, limit=args.limit, out_file=args.out, embedder=args.embedder
    )


if __name__ == "__main__":
    main()
