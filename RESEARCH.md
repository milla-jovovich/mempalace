# Retrieval Optimization: Hybrid Lexical-Semantic Search

## Summary
This implementation introduces a hybrid retrieval strategy to MemPalace. By combining vector-based similarity search (ChromaDB) with lexical search (SQLite FTS5) and merging the results using Reciprocal Rank Fusion (RRF), we address observed limitations in retrieving exact technical identifiers and code symbols.

## Observed Retrieval Characteristics
In testing with technical datasets, vector-only models may occasionally fail to prioritize exact string matches (such as specific Git hashes or unique function names) when the query possesses low semantic overlap with the surrounding context. 

## Implementation: Reciprocal Rank Fusion (RRF)
We utilize a dual-engine approach:
1.  **Lexical Indexing:** An SQLite FTS5 virtual table mirrors the content of the document store, providing a keyword-based index.
2.  **Hybrid Searcher:** A module that queries both the vector and lexical stores in parallel.
3.  **Fusion Algorithm:** Results are combined using the RRF algorithm ($Score = \sum 1 / (k + rank)$). This method allows for the integration of disparate scoring systems (vector distance vs. BM25) without requiring parameter normalization.

## Benchmark Data
The following metrics were recorded on a local memory palace (4,344 drawers) using a set of 15 technical targets (e.g., specific API keys, file paths, and function signatures):

| Metric | Vector Only (Baseline) | Hybrid (RRF) | Delta |
|---|---|---|---|
| Mean Reciprocal Rank (MRR) | 0.5395 | 0.8833 | +63.7% |
| Hit@1 Accuracy | 46.7% | 80.0% | +33.3% |

*Detailed results and the reproduction suite are available in the `/eval` directory.*

## Technical Integration
- **Atomicity:** The `mcp_server.py` was updated to perform dual-writes to both storage layers.
- **Overhead:** Retrieval fusion introduces an average latency of <5ms.
