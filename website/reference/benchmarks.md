# Benchmarks

Curated summary of MemPalace benchmark results. For the full 725-line progression with every experiment, see [`benchmarks/BENCHMARKS.md`](https://github.com/MemPalace/mempalace/blob/main/benchmarks/BENCHMARKS.md) in the repository.

## The Core Finding

MemPalace's benchmarked raw baseline stores the source text and searches it with ChromaDB's default embeddings. No extraction layer or summarization step is required for that baseline.

**And it scores 96.6% on LongMemEval.**

## LongMemEval Results

| Mode | R@5 | LLM Required | Cost/query |
|------|-----|-------------|------------|
| Raw ChromaDB | **96.6%** | None | $0 |
| Hybrid v3 + rerank | 99.4% | Haiku | ~$0.001 |
| Palace + rerank | 99.4% | Haiku | ~$0.001 |
| **Hybrid v4 + rerank** | **100%** | Haiku | ~$0.001 |

The 96.6% raw score requires no API key, no cloud, and no LLM at any stage. The 100% result uses optional Haiku reranking.

### Per-Category Breakdown (Raw, 96.6%)

| Question Type | R@5 | Count |
|---------------|-----|-------|
| Knowledge update | 99.0% | 78 |
| Multi-session | 98.5% | 133 |
| Temporal reasoning | 96.2% | 133 |
| Single-session user | 95.7% | 70 |
| Single-session preference | 93.3% | 30 |
| Single-session assistant | 92.9% | 56 |

### Held-Out Validation

**98.4% R@5** on 450 questions that hybrid_v4 was never tuned on — confirming the improvements generalize.

## Comparison vs Published Systems

| System | LongMemEval R@5 | API Required | Cost |
|--------|----------------|--------------|------|
| **MemPalace (hybrid)** | **100%** | Optional | Free |
| Supermemory ASMR | ~99% | Yes | — |
| **MemPalace (raw)** | **96.6%** | **None** | **Free** |
| Mastra | 94.87% | Yes | API costs |
| Hindsight | 91.4% | Yes | API costs |
| Mem0 | ~85% | Yes | $19–249/mo |

## Other Benchmarks

### ConvoMem (Salesforce, 75K+ QA pairs)

| System | Score |
|--------|-------|
| **MemPalace** | **92.9%** |
| Gemini (long context) | 70–82% |
| Block extraction | 57–71% |
| Mem0 (RAG) | 30–45% |

On this benchmark, MemPalace materially outperforms the Mem0 result cited in the comparison table.

### LoCoMo (1,986 multi-hop QA pairs)

| Mode | R@10 | LLM |
|------|------|-----|
| Hybrid v5 + Sonnet rerank (top-50) | **100%** | Sonnet |
| bge-large + Haiku rerank (top-15) | 96.3% | Haiku |
| Hybrid v5 (top-10, no rerank) | **88.9%** | None |
| Session, no rerank (top-10) | 60.3% | None |

### MemBench (ACL 2025, 8,500 items)

**80.3% R@5** overall. Strongest categories: aggregative (99.3%), comparative (98.4%), lowlevel_rec (99.8%).

## Reproducing Results

All benchmarks are reproducible with public datasets:

```bash
git clone https://github.com/MemPalace/mempalace.git
cd mempalace
pip install chromadb pyyaml

# Download LongMemEval data
curl -fsSL -o /tmp/longmemeval_s_cleaned.json \
  https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json

# Run raw baseline (96.6%, no API key needed)
python benchmarks/longmemeval_bench.py /tmp/longmemeval_s_cleaned.json
```

::: tip
Results are deterministic. Same data + same script = same result every time. Every result JSONL file contains every question, every retrieved document, every score.
:::

For complete reproduction instructions, benchmark integrity notes, and the full score progression, see the [full benchmark documentation](https://github.com/MemPalace/mempalace/blob/main/benchmarks/BENCHMARKS.md).
