# MemPalace v4 Benchmark Results

> LongMemEval (500 questions), run 2026-04-10, on the `feat/multishare` branch.
> Hardware: same machine, single-threaded.

## Headline

| Backend + Embedder | R@5 | R@10 | NDCG@5 | NDCG@10 | ms/query |
|---|---|---|---|---|---|
| **ChromaDB + MiniLM** (v3.x baseline) | 0.966 | 0.982 | 0.888 | 0.889 | 1165 |
| **LanceDB + MiniLM** (v4.0 default) | **0.966** | **0.982** | **0.888** | **0.889** | **638** |
| **LanceDB + BGE-small** (v4.0 bge-small) | 0.962 | 0.978 | **0.895** | **0.893** | 2624 |

### Key findings

1. **Zero retrieval regression.** LanceDB + MiniLM produces **identical**
   Recall@5/10 and NDCG scores to the ChromaDB baseline (0.966 R@5).

2. **1.8× faster queries.** LanceDB averages 638ms/query vs ChromaDB's
   1165ms — an 83% throughput improvement with cosine distance.

3. **BGE-small trades R@5 for NDCG.** The higher-quality BGE model has
   slightly lower R@5 (0.962 vs 0.966 — a 2-question difference on 500)
   but **higher NDCG** (0.895 vs 0.888), meaning the relevant results it
   does find are ranked better.  It's slower (2.6s/query) because the model
   is larger.

## Per-type Breakdown (Recall@5)

| Question Type | ChromaDB+MiniLM | Lance+MiniLM | Lance+BGE-small |
|---|---|---|---|
| knowledge-update | 1.000 | 1.000 | 0.987 |
| multi-session | 0.992 | 0.992 | 0.985 |
| single-session-assistant | 0.964 | 0.964 | 0.964 |
| single-session-preference | 0.967 | 0.967 | 0.867 |
| single-session-user | 0.914 | 0.914 | **0.957** |
| temporal-reasoning | 0.947 | 0.947 | 0.947 |

BGE-small notably improves `single-session-user` (+4.3 points) but
regresses on `single-session-preference` (−10 points).  The MiniLM
default remains the safer all-around choice for this benchmark.

## Reproduce

```bash
# Download data
mkdir -p /tmp/longmemeval-data
curl -fsSL -o /tmp/longmemeval-data/longmemeval_s_cleaned.json \
  https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json

# Quick test (20 questions, ~2 minutes)
python benchmarks/longmemeval_v4.py /tmp/longmemeval-data/longmemeval_s_cleaned.json --mode quick --limit 20

# Full comparison (500 questions, ~45 minutes)
python benchmarks/longmemeval_v4.py /tmp/longmemeval-data/longmemeval_s_cleaned.json --mode all

# Compare all embedders (500 questions, ~2 hours)
python benchmarks/longmemeval_v4.py /tmp/longmemeval-data/longmemeval_s_cleaned.json --mode embedders

# Custom embedder
python benchmarks/longmemeval_v4.py DATA --mode lance-custom --embedder "intfloat/e5-base-v2"
```

## Raw Results

Full per-question data: `benchmarks/results_v4_comparison.json`
