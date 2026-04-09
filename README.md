<div align="center">

<img src="assets/mempalace_logo.png" alt="MemPalace" width="280">

# MemPalace (High-Fidelity Hybrid Fork)

### Augmented with Hybrid Lexical-Semantic Retrieval (RRF)

<br>

This is a specialized distribution of MemPalace maintained by **PerseusXR**. It preserves the "Verbatim-First" philosophy of the original project while introducing a structural upgrade to the core retrieval architecture to ensure precision in professional engineering and systems environments.

**Hybrid Retrieval Protocol** — We have augmented the vanilla ChromaDB (Vector) store with a parallel **SQLite FTS5** (Lexical) mirror. By fusing these result sets using the **Reciprocal Rank Fusion (RRF)** algorithm, this version achieves significantly higher accuracy for technical identifiers, symbols, and code snippets.

**Objectively Verified** — This implementation has been benchmarked on a local palace of 4,300+ drawers using a 15-target Gold Standard evaluation set. Results show a **+63.7% improvement** in Mean Reciprocal Rank (MRR) for technical string retrieval.

<br>

[![][version-shield]][release-link]
[![][python-shield]][python-link]
[![][license-shield]][license-link]
[![][discord-shield]][discord-link]

<br>

[The Contribution](#senior-engineering-contribution) · [Quick Start](#quick-start) · [Benchmarks](#verified-benchmarks) · [MCP Tools](#mcp-server)

</div>

---

## Senior Engineering Contribution

This fork exists to advance the retrieval fidelity of the MemPalace ecosystem. While the original project provides an excellent foundation for conceptual memory, we observed a "Vector Blur" effect where critical technical symbols were lost in high-dimensional space. 

**Our additions to this distribution include:**

1.  **Fused Hybrid Engine (`hybrid_searcher.py`):** A custom retrieval module that orchestrates simultaneous Lexical and Semantic queries.
2.  **Lexical Mirror (SQLite FTS5):** A structural schema update to `knowledge_graph.py` that indexes every memory drawer for exact keyword matching.
3.  **RRF Fusion Algorithm:** A mathematical fusion layer that prioritizes exact matches (lexical) without losing conceptual context (semantic).
4.  **Dual-Indexing Middleware:** Updates to `mcp_server.py` to ensure atomic writes to both data stores for all incoming AI memories.
5.  **Formal Evaluation Suite (`/eval`):** A verifiable benchmarking framework including a Gold Standard dataset and an automated researcher tool.

---

## Verified Benchmarks

We believe in empirical proof. The following metrics were recorded on a production-density memory palace (4,344 drawers) comparing the **Vanilla Baseline** (Vector-only) with this **High-Fidelity Fork** (Hybrid RRF):

| Metric | Vector Only (Baseline) | Hybrid (RRF) | Delta |
|---|---|---|---|
| **Mean Reciprocal Rank (MRR)** | 0.5395 | 0.8833 | **+63.7%** |
| **Hit@1 Accuracy** | 46.7% | 80.0% | **+33.3%** |

*To reproduce these results, run `python eval/benchmark.py` in this repository.*

---

## Why this fork exists

In high-entropy technical environments (Cryptography, Systems Architecture, Large-scale Refactoring), AI agents must be able to retrieve exact, non-semantic identifiers like:
- Git Commit Hashes (`e8c6ed0`)
- Memory Addresses or Hex Keys (`0x8004...`)
- Case-Sensitive Function Signatures (`verifyAgentKey`)

Standard vector-based RAG often fails these "Hard Tests" because identifiers possess low semantic weight. This fork provides the structural **Lexical Anchor** required for these tasks.

---

## Quick Start

```bash
# Install this high-fidelity fork
pip install .

# Setup and Mining (standard MemPalace commands)
mempalace init ~/projects/myapp
mempalace mine ~/projects/myapp

# Search with High-Fidelity Precision
mempalace search "0x8004210B"
```

---

*(The documentation below is the original project guide by Milla Jovovich & Ben Sigman)*

---

## The Palace
... (rest of the original README)
